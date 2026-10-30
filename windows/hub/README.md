# Snowhush hub

A tiny WebSocket server on this machine that lets Snowhush, a Firefox extension and Unity scripts talk to each other.
Snowhush connects to it as a client and lets snow settle on the rectangles the others report.

```
Firefox extension ──┐
                    ├── ws://127.0.0.1:8765 (hub.py) ── Snowhush (Windows)
Unity scripts ──────┘
```

- `hub.py`: the hub.
- `firefox/`: the Firefox extension, snow on the elements of web pages (see `firefox/README.md`).
- `unity/`: scripts for the Unity Editor's windows and for UI in a built player (see `unity/README.md`).
- `fake_client.py`: draws invisible windows by hand, to try Snowhush without any of the above, and `--mirror`
  to check where the others say their rectangles are.

## Try it

```
pip install websockets pillow
python hub.py           # the hub
python fake_client.py   # stands in for the extension, see below
```

`fake_client.py` covers the desktop with a dimmed, low quality picture of your screen. Press and drag to draw a rectangle
(green: snow can settle on it, red: too small); let go and the picture disappears, leaving an **invisible window** that
Snowhush puts snow on. A small panel lets you draw more, undo, clear all or quit.

- `--mode windows` (default) makes a **real window** for each rectangle, so even a Snowhush without these changes
  sees it, and no hub is needed. No border, no title bar, no taskbar button, never takes focus. Snowhush skips
  windows that are click-through by style, mostly transparent or cut out by a colour key (they are overlays and
  widgets, not something snow rests on), so the window avoids all of that: nothing is drawn into it (so it is invisible),
  and its shape is cut down to a 2 px strip along the top edge (so the rest is click-through). Needs only `pip install pillow`.
- `--mode hub` sends the rectangles to the hub for a Snowhush started with `SNOWHUSH_HUB`.
- `--show` makes the windows visible (blue boxes). If snow lands on those but not on the invisible ones, Snowhush
  skips the invisible ones; if it lands on neither, "Snow on Windows" is off, "Behind Windows" is on, or it isn't this build.
- `--demo` sends a bar moving up and down to the hub, without any window.

If no snow settles, check that:
- Snowhush was built from this branch and started with `SNOWHUSH_HUB` set; `%LOCALAPPDATA%\Snowhush\snowhush.log` then has a `hub:` line.
- "Snow on Windows" is on and "Behind Windows" is off in the tray menu: with either the other way round, no surfaces are used.
- The rectangle has room above it (not touching the top of the display) and is at least about 80 × 16 DIPs.

Tell Snowhush where the hub is (off otherwise), by either of:

```
set SNOWHUSH_HUB=ws://127.0.0.1:8765
Snowhush.exe
```

or the first line of `%LOCALAPPDATA%\Snowhush\hub.txt` (`ws://127.0.0.1:8765`), which also works when it is started
from the Start menu or at login. Snowhush's log in the same folder says `hub: ws://...` when it took the address,
or `hub: off` when it found none.

`http://127.0.0.1:8765/test` is a page for the Firefox extension with every kind of element and a panel that shows who is
connected; `http://127.0.0.1:8765/status` is the same as JSON.

Only `ws://` addresses on this machine (`127.0.0.1`, `localhost`, `[::1]`) are accepted.

## Messages

JSON text. Whatever one client sends, the hub passes to all the others.

```json
{"type":"surfaces","source":"firefox","rects":[{"id":"nav","x":100,"y":200,"w":600,"h":48,"radius":8}],"hidden":["footer"]}
{"type":"clear","source":"firefox"}
```

- Coordinates are **physical pixels on the virtual desktop, y pointing down**, like Windows reports its windows.
  In Firefox that is `(window.mozInnerScreenX + element.getBoundingClientRect().left) * devicePixelRatio`.
- A `surfaces` message replaces everything the same `source` sent before; `clear` removes it.
- `id` keeps the snow with its rectangle from one message to the next.
- **`hidden`** lists ids that are away for now: the program lost focus, or the page is on another tab. Their snow is
  put aside as it is, and settles again, in the same place and the same amount, when the id is back in `rects`.
  An id in neither list lets its snow fall. Snowhush keeps the snow of about 200 away surfaces; snowless ones
  are not counted.
- Up to 512 rectangles per source; they need room above them and at least about 80 × 16 DIPs to catch snow.
- When the hub goes away, its snow drops; Snowhush reconnects by itself. When a client goes away, the hub clears its
  sources after 3 seconds (`--grace`), unless it is sending them again by then.

Snowhush sends `{"type":"hello","role":"snowhush"}` when it connects.

## Not yet

- Windows in front of the browser don't hide the snow on page elements: report rectangles only while the page is visible and focused.
- No setting in the tray menu; the hub is switched on by the environment variable.
