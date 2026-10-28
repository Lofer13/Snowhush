"""Snowhush hub: a WebSocket server on this machine that passes messages between programs.

Everything one client sends goes to every other client: Snowhush listens for the "surfaces" and "clear" messages of
a Firefox extension or a Unity script, and those can listen to each other. Messages are JSON text, see
src/remote.rs for the ones Snowhush understands.

    pip install websockets
    python hub.py                # ws://127.0.0.1:8765
    python hub.py --port 9000

Then start Snowhush with SNOWHUSH_HUB=ws://127.0.0.1:8765 in its environment.
"""

import argparse
import asyncio
import json
import logging

from websockets.asyncio.server import serve

MAX_MESSAGE = 1 << 20

clients = set()
# The last "surfaces" message of each source, for a client that connects later: Snowhush after a restart, say.
latest = {}


def remember(message):
    try:
        data = json.loads(message)
        source = data["source"]
        if data["type"] == "surfaces":
            latest[source] = message
        elif data["type"] == "clear":
            latest.pop(source, None)
    except (ValueError, KeyError, TypeError):
        pass


async def handle(connection):
    clients.add(connection)
    for message in list(latest.values()):
        await connection.send(message)
    logging.info("connected: %s (%d clients)", connection.remote_address, len(clients))
    try:
        async for message in connection:
            remember(message)
            others = [client for client in clients if client is not connection]
            for client in others:
                try:
                    await client.send(message)
                except Exception:
                    # A client that went away is dropped by its own handler.
                    pass
    finally:
        clients.discard(connection)
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
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        asyncio.run(main(arguments.host, arguments.port))
    except KeyboardInterrupt:
        pass
