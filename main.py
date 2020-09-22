# -*- coding: utf-8 -*-

# If you're interested in development, my test server is often up
# at 51.161.34.235 - registration is done on login, so login with
# whatever username you'd like; the cert is Akatsuki's.

__all__ = ()

if __name__ != '__main__':
    raise Exception('main.py is meant to be run directly!')

import asyncio
import importlib
import aiohttp
import orjson # faster & more accurate than stdlib json
import cmyui # web & db
import time
import sys
import os

from console import *
from handlers import *

from objects import glob
from objects.player import Player
from objects.channel import Channel
from constants.privileges import Privileges
from constants import regexes

# Set CWD to /gulag.
os.chdir(os.path.dirname(os.path.realpath(__file__)))

async def handle_conn(conn: cmyui.AsyncConnection) -> None:
    if 'Host' not in conn.headers:
        await conn.send(400, b'Missing required headers.')
        return

    st = time.time_ns()
    handler = None

    # Match the host & uri to the correct handlers.
    if regexes.bancho_domain.match(conn.headers['Host']):
        if conn.path == '/':
            handler = handle_bancho

    elif conn.headers['Host'] == 'osu.ppy.sh':
        if conn.path.startswith('/web/'):
            handler = handle_web
        elif conn.path.startswith('/ss/'):
            handler = handle_ss # screenshots
        elif conn.path.startswith('/d/'):
            handler = handle_dl # osu!direct
        elif conn.path.startswith('/api/'):
            handler = handle_api # gulag!api

    elif conn.headers['Host'] == 'a.ppy.sh':
        handler = handle_avatar # avatars

    if handler:
        # We have a handler for this request.
        await handler(conn)
    else:
        # We have no such handler.
        await plog(f'Unhandled {conn.path}.', Ansi.LIGHT_RED)
        await conn.send(400, b'Request handler not implemented.')

    time_taken = (time.time_ns() - st) / 1000 # nanos -> micros
    time_str = (f'{time_taken:.2f}μs' if time_taken < 1000
           else f'{time_taken / 1000:.2f}ms')

    await plog(f'Handled in {time_str}.', Ansi.LIGHT_CYAN)

async def run_server(addr: cmyui.Address) -> None:
    glob.version = cmyui.Version(2, 4, 3)
    glob.http = aiohttp.ClientSession(json_serialize=orjson.dumps)

    glob.db = cmyui.AsyncSQLPool()
    await glob.db.connect(**glob.config.mysql)

    # Aika
    glob.bot = Player(id = 1, name = 'Aika', priv = Privileges.Normal)
    glob.bot.ping_time = 0x7fffffff

    await glob.bot.stats_from_sql_full() # no need to get friends
    await glob.players.add(glob.bot)

    # Add all channels from db.
    async for chan in glob.db.iterall('SELECT * FROM channels'):
        await glob.channels.add(Channel(**chan))

    async with cmyui.AsyncTCPServer(addr) as serv:
        await plog(f'Gulag v{glob.version} online!', Ansi.LIGHT_GREEN)
        async for conn in serv.listen(glob.config.max_conns):
            asyncio.create_task(handle_conn(conn))

# Use uvloop if available (much faster).
if spec := importlib.util.find_spec('uvloop'):
    module = importlib.util.module_from_spec(spec)
    sys.modules['uvloop'] = module
    spec.loader.exec_module(module)

    asyncio.set_event_loop_policy(module.EventLoopPolicy())

asyncio.run(run_server(glob.config.server_addr))
