# Snowhush hub

A tiny WebSocket server on this machine that lets Snowhush, a Firefox extension and Unity scripts talk to each other.
Snowhush connects to it as a client and lets snow settle on the rectangles the others report.

```
Firefox extension ──┐
                    ├── ws://127.0.0.1:8765 (hub.py) ── Snowhush (Windows)
Unity script ───────┘
```

## Try it

```
pip install websockets
python hub.py                  # the hub
python fake_client.py --scroll # stands in for the extension: a bar of snow-catching rectangle
```

Start Snowhush with the hub's address in its environment (off otherwise):

```
set SNOWHUSH_HUB=ws://127.0.0.1:8765
Snowhush.exe
```

Only `ws://` addresses on this machine (`127.0.0.1`, `localhost`, `[::1]`) are accepted.

## Messages

JSON text. Whatever one client sends, the hub passes to all the others.

```json
{"type":"surfaces","source":"firefox","rects":[{"id":"nav","x":100,"y":200,"w":600,"h":48,"radius":8}]}
{"type":"clear","source":"firefox"}
```

- Coordinates are **physical pixels on the virtual desktop, y pointing down**, like Windows reports its windows.
  In Firefox that is `window.mozInnerScreenX/Y + element.getBoundingClientRect() * devicePixelRatio`.
- A `surfaces` message replaces everything the same `source` sent before; `clear` removes it.
- `id` keeps the snow with its rectangle from one message to the next.
- Up to 512 rectangles per source; they need room above them and at least about 80 × 16 DIPs to catch snow.
- When the hub goes away, its snow drops; Snowhush reconnects by itself.

Snowhush sends `{"type":"hello","role":"snowhush"}` when it connects.

## Not yet

- Windows in front of the browser don't hide the snow on page elements: report rectangles only while the page is visible and focused.
- No setting in the tray menu; the hub is switched on by the environment variable.
