"""
docs:
this is the aiohttp session module of the entire system
* hosts the aiohttp.ClientSession object
* acts as the router function for different messages received from the queue to the appropriate endpoints
* acts as the receiver for data from the api ### TODO: implement message handling to go to the 
# TODO: documentation
"""

# third-party
import logging
import aiohttp
import asyncio
import time
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Any

# internal core modules
import src.data.requests as requests

# internal helpers, configurations
from utils import log_config, map_sensor_payload, map_sink_payload, get_from_queue
from settings import APPConfigurations, Topics, APIRoutes, Broker

__log__ = log_config(logging.getLogger(__name__))

# TODO: documentation
# TODO: implement return request response status (i.e code, status literal, etc.)
async def __router__(semaphore: asyncio.Semaphore, msg: Dict, client_session: aiohttp.ClientSession) -> Any:
    # NOTE:
    # ----- msg keys -> {priorty, topic, payload, timestamp}

    if not client_session:
        __log__.error(f"Error at aioclient.__router__(), client_session is empty!")
        return

    async with semaphore:
        if msg['topic'] == '/dev/test':
            foo = 'foo'

        if msg['topic'] == f"{Broker.ROOT_TOPIC}{Topics.SENSOR_DATA}":
            data = map_sensor_payload(msg['payload'])
            stat, body = await requests.post_req(session=client_session, url=f'{APIRoutes.BASE_URL}{APIRoutes.SENSOR_DATA}', data=data)

        if msg['topic'] == f"{Broker.ROOT_TOPIC}{Topics.SINK_DATA}":
            data = map_sink_payload(msg['payload'])
            #return # wala lang sa kapoy paman
            # TODO: api
            #__log__.debug(f"Received sink node data: {msg['payload']}")
            stat, body = await requests.post_req(session=client_session, url=f'{APIRoutes.BASE_URL}{APIRoutes.SINK_DATA}', data=data)

# TODO: documentation
async def start(queue: multiprocessing.Queue) -> None:
    semaphore = asyncio.Semaphore(APPConfigurations.GLOBAL_SEMAPHORE_COUNT)

    # acquire the current running event loop
    # this is important to allow to run non-blocking message retrieval in the executor
    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.get_running_loop()
    except Exception as e:
        __log__.error(f"Failed to get running event loop @ PID {os.getpid()} (aioclient child process): {e}")
        return
    
    # acquire a aiohttp.ClientSession object
    # in order to allow non-blocking http requests to execute
    client: aiohttp.ClientSession | None = None
    try:
        client = aiohttp.ClientSession()
    except Exception as e:
        __log__.error(f"Failed to create ClientSession object @ PID {os.getpid()} (aioclient child process): {e}")
        return

    if loop and client:
        __log__.info(f"AioHTTP Session Client subprocess active @ PID {os.getpid()}")
        try:
            with ThreadPoolExecutor() as pool:
                while True:
                    item = await loop.run_in_executor(pool, get_from_queue, queue, __name__) # non-blocking message retrieval

                    # if an item is retrieved
                    if item:
                        __log__.debug(f"aioHTTPClient @ PID {os.getpid()} received message from queue (topic: {item['topic']})")
                        asyncio.create_task(__router__(semaphore, item, client))

        except KeyboardInterrupt or asyncio.CancelledError:
            # close the aiohttp session client
            await client.close()
            raise