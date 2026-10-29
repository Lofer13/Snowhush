"""Snowhush hub: a WebSocket server on this machine that passes messages between programs.

Everything one client sends goes to every other client: Snowhush listens for the "surfaces" and "clear" messages of
a Firefox extension or a Unity script, and those can listen to each other. Messages are JSON text, see
src/remote.rs for the ones Snowhush understands.

When a client goes away without saying so (Firefox closed, Unity quit or crashed), the hub says it for it: a "clear"
for each source it sent, after a short grace period so that a client that comes right back, as Unity does after
recompiling scripts, keeps its snow.

    pip install websockets
    python hub.py                # ws://127.0.0.1:8765
    python hub.py --port 9000

Then start Snowhush with SNOWHUSH_HUB=ws://127.0.0.1:8765 in its environment.
"""

import argparse
import asyncio
import json
import logging

from websockets.asyncio.server import broadcast, serve

MAX_MESSAGE = 1 << 20

clients = set()
# The last "surfaces" message of each source, for a client that connects later: Snowhush after a restart, say.
latest = {}
# Which connection last sent each source, and the clears waiting for a source whose sender went away.
owners = {}
waiting = {}
grace = 3.0


def track(connection, message):
    """Notes what a message from this connection says about its source."""
    try:
        data = json.loads(message)
        source = data["source"]
        kind = data["type"]
    except (ValueError, KeyError, TypeError):
        return
    if not isinstance(source, str):
        return
    if kind == "surfaces":
        latest[source] = message
        owners[source] = connection
    elif kind == "clear":
        latest.pop(source, None)
        owners.pop(source, None)
    else:
        return
    # Someone is sending it again, or took it back: no clear for it from an earlier disconnect.
    timer = waiting.pop(source, None)
    if timer is not None:
        timer.cancel()


def forget(connection):
    """The connection went away: its sources are cleared after the grace period, unless sent again by then."""
    for source in [source for source, owner in owners.items() if owner is connection]:
        del owners[source]
        loop = asyncio.get_running_loop()
        waiting[source] = loop.call_later(grace, clear, source)


def clear(source):
    waiting.pop(source, None)
    if source in owners:
        return
    latest.pop(source, None)
    logging.info("cleared %s: its client went away", source)
    broadcast(clients, json.dumps({"type": "clear", "source": source}))


async def handle(connection):
    clients.add(connection)
    for message in list(latest.values()):
        await connection.send(message)
    logging.info("connected: %s (%d clients)", connection.remote_address, len(clients))
    try:
        async for message in connection:
            track(connection, message)
            # Doesn't wait for anyone: a client that doesn't read (a script that only sends) must not hold up the others.
            broadcast([client for client in clients if client is not connection], message)
    finally:
        clients.discard(connection)
        forget(connection)
        logging.info("disconnected: %s (%d clients)", connection.remote_address, len(clients))


async def main(host, port):
    # Browsers let any web page open a WebSocket to localhost, so a page could talk to this hub.
    # Only an extension or a program is welcome: no Origin header, or one from an extension.
    def allowed(connection, request):
        origin = request.headers.get("Origin")
        if origin and not origin.startswith(("moz-extension://", "chrome-extension://")):
            logging.warning("refused origin %s", origin)
            return connection.respond(403, "Forbidden\n")
        return None

    async with serve(handle, host, port, max_size=MAX_MESSAGE, process_request=allowed):
        logging.info("hub on ws://%s:%d", host, port)
        await asyncio.get_running_loop().create_future()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--grace", type=float, default=3.0, help="seconds before the sources of a lost client are cleared")
    arguments = parser.parse_args()
    grace = arguments.grace
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(main(arguments.host, arguments.port))
    except KeyboardInterrupt:
        pass
