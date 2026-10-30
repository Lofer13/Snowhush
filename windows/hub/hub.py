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

Then start Snowhush with SNOWHUSH_HUB=ws://127.0.0.1:8765 in its environment, or put that address in
%LOCALAPPDATA%\\Snowhush\\hub.txt.

The same port also answers plain HTTP, for trying things out:
    http://127.0.0.1:8765/test      a page with every kind of element, and who is connected (also /test2, /test3)
    http://127.0.0.1:8765/status    the same as JSON
"""

import argparse
import asyncio
import json
import logging
import pathlib

from websockets.asyncio.server import broadcast, serve
from websockets.exceptions import InvalidStatus

MAX_MESSAGE = 1 << 20

clients = set()
# The last "surfaces" message of each source, for a client that connects later: Snowhush after a restart, say.
latest = {}
# Which connection last sent each source, and the clears waiting for a source whose sender went away.
owners = {}
waiting = {}
roles = {}  # connection -> what it said it is in its "hello": "snowhush" for the program itself
grace = 3.0
PAGES = {"/", "/test", "/test2", "/test3"}


class QuietHttp(logging.Filter):
    """websockets reports every plain page or status it serves as a failed handshake, with a traceback."""

    def filter(self, record):
        if record.exc_info and isinstance(record.exc_info[1], InvalidStatus):
            return False
        return not record.getMessage().startswith("connection rejected (")


def who(connection):
    """What is on the other end, as far as it says: the Firefox extension has an extension origin."""
    origin = connection.request.headers.get("Origin") if connection.request else None
    if origin and origin.startswith("moz-extension://"):
        return "the Firefox extension"
    return origin or "a program"


def track(connection, message):
    """Notes what a message from this connection says about its source."""
    try:
        data = json.loads(message)
        kind = data["type"]
        source = data.get("source")
    except (ValueError, KeyError, TypeError, AttributeError):
        return
    if kind == "hello":
        roles[connection] = str(data.get("role", ""))[:32]
        logging.info("hello from %s", "Snowhush" if roles[connection] == "snowhush" else roles[connection] or "someone")
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


def status():
    sources = {}
    for source, message in latest.items():
        try:
            data = json.loads(message)
            sources[source] = {"rects": len(data.get("rects", [])), "hidden": len(data.get("hidden", []))}
        except ValueError:
            pass
    return {
        "clients": len(clients),
        "snowhush": "snowhush" in roles.values(),
        "sources": sources,
    }


def reply(connection, body, content_type):
    response = connection.respond(200, body)
    del response.headers["Content-Type"]  # respond() sets one, and setting another would add a second
    response.headers["Content-Type"] = content_type
    response.headers["Cache-Control"] = "no-store"
    return response


def answer(connection, request):
    """The plain HTTP side: the test page and the status. Not a WebSocket handshake."""
    path = request.path.split("?")[0]
    if path in PAGES:
        try:
            body = pathlib.Path(__file__).with_name("test.html").read_text(encoding="utf-8")
        except OSError:
            return connection.respond(404, "test.html is not next to hub.py\n")
        return reply(connection, body, "text/html; charset=utf-8")
    if path == "/status":
        return reply(connection, json.dumps(status()), "application/json")
    return connection.respond(404, "Not found\n")


async def handle(connection):
    clients.add(connection)
    for message in list(latest.values()):
        await connection.send(message)
    logging.info("connected: %s, %s (%d clients)", who(connection), connection.remote_address, len(clients))
    try:
        async for message in connection:
            track(connection, message)
            # Doesn't wait for anyone: a client that doesn't read (a script that only sends) must not hold up the others.
            broadcast([client for client in clients if client is not connection], message)
    finally:
        clients.discard(connection)
        roles.pop(connection, None)
        forget(connection)
        logging.info("disconnected: %s (%d clients)", connection.remote_address, len(clients))


async def main(host, port):
    logging.getLogger("websockets.server").addFilter(QuietHttp())
    # Browsers let any web page open a WebSocket to localhost, so a page could talk to this hub.
    # Only an extension or a program is welcome: no Origin header, or one from an extension.
    def allowed(connection, request):
        if request.headers.get("Upgrade", "").lower() != "websocket":
            return answer(connection, request)
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
