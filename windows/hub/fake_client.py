"""Stands in for the Firefox extension: sends a few rectangles to the hub, so the snow settles on them.

    python fake_client.py                         # a bar near the middle of a 1920x1080 display
    python fake_client.py --x 400 --y 300 --w 800 --h 60 --hold 30
    python fake_client.py --clear                 # takes the snow off them again

Coordinates are physical pixels of the virtual desktop, y pointing down.
"""

import argparse
import asyncio
import json
import time

from websockets.asyncio.client import connect


async def main(arguments):
    async with connect(arguments.url) as hub:
        if arguments.clear:
            await hub.send(json.dumps({"type": "clear", "source": arguments.source}))
            return
        rect = {"id": "demo", "x": arguments.x, "y": arguments.y, "w": arguments.w, "h": arguments.h, "radius": 10}
        message = json.dumps({"type": "surfaces", "source": arguments.source, "rects": [rect]})
        await hub.send(message)
        print(f"sent {rect}, holding for {arguments.hold} s")
        # Moves up and down to show the snow follows it: a page being scrolled does just that.
        started = time.monotonic()
        while time.monotonic() - started < arguments.hold:
            await asyncio.sleep(0.05)
            if arguments.scroll:
                rect["y"] = arguments.y + 80 * (1 + __import__("math").sin((time.monotonic() - started) / 2))
                await hub.send(json.dumps({"type": "surfaces", "source": arguments.source, "rects": [rect]}))
        await hub.send(json.dumps({"type": "clear", "source": arguments.source}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--source", default="fake")
    parser.add_argument("--x", type=float, default=560)
    parser.add_argument("--y", type=float, default=400)
    parser.add_argument("--w", type=float, default=800)
    parser.add_argument("--h", type=float, default=60)
    parser.add_argument("--hold", type=float, default=20)
    parser.add_argument("--scroll", action="store_true", help="move the rectangle up and down")
    parser.add_argument("--clear", action="store_true")
    asyncio.run(main(parser.parse_args()))
