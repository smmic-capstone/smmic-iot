# third-party
import multiprocessing
import asyncio
import logging
import os
import random
import heapq
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any, Dict

# internal helpers, configs
from utils import log_config, set_priority, priority, get_from_queue
from settings import APPConfigurations, Topics, Broker
import src.data.sysmonitor as sysmonitor 

__log__ = log_config(logging.getLogger(__name__))

# unimplemented priority class for tasks
# not sure how to implement this yet
# TODO: look into task prioritization
class __prioritized_task__:
    def __init__(self, priority: int, task: Callable):
        self.priority = priority
        self.task = task

    def __lt__(self, other):
        return self.priority < other.priority

# for topic '/dev/test'
# a simple dummy function made to test concurrent task management
async def __dev_test_task__(msg: dict) -> None:
    # simulate task delay
    duration = random.randint(1, 10)
    await asyncio.sleep(duration)
    __log__.debug(f"Task done @ PID {os.getpid()} (dev_test_task()): [timestamp: {msg['timestamp']}, topic: {msg['topic']}, payload: {msg['payload']}] after {duration} seconds")

# - description:
# * delegates task to the proper process / function
#
# - parameters:
# * aio_queue: the message queue to send items to the aiohttp client
# * hardware_queue: the message queue to send items to the hardware process
async def __delegator__(semaphore: asyncio.Semaphore, msg: Dict, aio_queue: multiprocessing.Queue, hardware_queue: multiprocessing.Queue) -> Any:
    aio_queue_topics = [f'{Broker.ROOT_TOPIC}{Topics.SENSOR_DATA}', f'{Broker.ROOT_TOPIC}{Topics.SINK_DATA}'] # TODO: update the registered topics here
    hardware_queue_topics = [f'{Broker.ROOT_TOPIC}{Topics.IRRIGATION}'] # TODO: implement this
    test_topics = ['/dev/test']

    async with semaphore:

        if msg['topic'] in test_topics:
            await __dev_test_task__(msg)

        if msg['topic'] in aio_queue_topics:
            return __msg_to_queue__(aio_queue, msg)
                # TODO: refactor to implement proper return value

        if msg['topic'] in hardware_queue_topics:
            return __msg_to_queue__(hardware_queue, msg)            

# internal function to put messages to queue
# abstract function that handles putting messages to queue primarily used by the delegator
def __msg_to_queue__(queue: multiprocessing.Queue, msg: Dict[str, Any]) -> bool:
    if not queue:
        __log__.error(f"Invalid queue object {queue}! @ PID {os.getpid()} (taskmanager.__msg_to_queue__)")
        return False
    
    try:
        queue.put(msg)
        return True
    except Exception as e:
        __log__.error(f"Failed to put message to queue @ PID {os.getpid()} (taskmanager.__msg_to_queue)")
        return False

# start the taskmanager process
#
# - parameters:
# * msg_queue: the message queue that the mqtt client sends messages to. items from this queue are identified and delegated in this task manager module
# * aio_queue: the queue that the task manager will send request tasks to, received by the aioclient submodule from the 'data' module
# * hardware_queue: hardware tasks are put into this queue by the task manager. received by the hardware module
#
async def start(msg_queue: multiprocessing.Queue, aio_queue: multiprocessing.Queue, hardware_queue: multiprocessing.Queue, sys_queue: multiprocessing.Queue) -> None:
    # testing out this semaphore count
    # if the system experiences delay or decrease in performance, try to lessen this amount
    semaphore = asyncio.Semaphore(APPConfigurations.GLOBAL_SEMAPHORE_COUNT)
    # TODO: look into this priority queue
    # priority_queue = asyncio.PriorityQueue()

    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.get_running_loop()
    except Exception as e:
        __log__.error(f"Failed to get running event loop @ PID {os.getpid()} taskmanager child process: {e}")
        return

    if loop:
        __log__.info(f"Task Manager subprocess active @ PID {os.getpid()}")
        # use the threadpool executor to run the monitoring function that retrieves data from the queue
        try:
            # start the sysmonitor coroutine
            sysmonitor_t = loop.create_task(sysmonitor.start(sys_queue=sys_queue, msg_queue=msg_queue))
            with ThreadPoolExecutor() as pool:
                while True:
                    # run message retrieval from queue in non-blocking way
                    msg = await loop.run_in_executor(pool, get_from_queue, msg_queue, __name__)

                    # if a message is retrieved, create a task to handle that message
                    # TODO: implement task handling for different types of messages
                    if msg:
                        __log__.debug(f"Module {__name__} at PID {os.getpid()} received message from queue (topic: {msg['topic']})")

                        # assign a priority for the task
                        _priority = set_priority(msg['topic'])

                        if not _priority:
                            __log__.debug(f"Cannot assert priority of message from topic: {msg['topic']}, setting priority to moderate instead")
                            _priority = priority.MODERATE

                        asyncio.create_task(__delegator__(semaphore=semaphore, msg=msg, aio_queue=aio_queue, hardware_queue=hardware_queue))

                    await asyncio.sleep(0.05)
                    
        except KeyboardInterrupt or asyncio.CancelledError:
            sysmonitor_t.cancel()
            try:
                loop.run_until_complete(sysmonitor_t)
            except asyncio.CancelledError:
                pass
            raise