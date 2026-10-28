"""Stands in for the Firefox extension, to try the snow on invisible windows.

    pip install websockets pillow
    python fake_client.py

A dimmed, low quality picture of your screen covers the desktop. Press the mouse and drag to draw a rectangle, as when
selecting icons on the desktop; green is big enough for snow to settle on, red is too small. When you let go, the picture
goes away and the rectangle stays behind as an invisible window: the hub passes it on and Snowhush lets snow settle on
its top edge. A small panel keeps count and lets you draw another one, undo or remove them all.

Coordinates sent are physical pixels of the virtual desktop, y pointing down (see ../README.md).
Start Snowhush with SNOWHUSH_HUB set, with "Snow on Windows" on and "Behind Windows" off.
    python fake_client.py --demo        no window: one bar that moves up and down, for 20 seconds
"""

import argparse
import ctypes
import json
import math
import sys
import time

from websockets.sync.client import connect

# What Snowhush settles on: wide and tall enough (DIPs), see src/remote.rs.
MIN_WIDTH = 80
MIN_HEIGHT = 16


def message(source, rects):
    """The `surfaces` message for a list of (x, y, w, h) rectangles."""
    items = [{"id": f"fake-{n}", "x": x, "y": y, "w": w, "h": h, "radius": 0} for n, (x, y, w, h) in enumerate(rects, 1)]
    return json.dumps({"type": "surfaces", "source": source, "rects": items})


def normalized(x0, y0, x1, y1):
    """A rectangle from two opposite corners, as (x, y, w, h)."""
    return (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))


class Hub:
    """The connection to the hub; tries again when it was lost."""

    def __init__(self, url):
        self.url = url
        self.socket = None

    def send(self, text):
        for _ in range(2):
            try:
                if self.socket is None:
                    self.socket = connect(self.url, open_timeout=2)
                self.socket.send(text)
                return True
            except Exception:
                self.socket = None
        return False

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass


def virtual_screen():
    """(left, top, width, height) of the whole desktop in physical pixels, and the scale of the main display."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    left, top, width, height = (user32.GetSystemMetrics(n) for n in (76, 77, 78, 79))
    try:
        scale = user32.GetDpiForSystem() / 96
    except Exception:
        scale = 1.0
    return left, top, width, height, scale


def run_window(arguments):
    import tkinter as tk

    from PIL import Image, ImageEnhance, ImageGrab, ImageTk

    if sys.platform == "win32":
        # Physical pixels, as Snowhush reports its windows; without this Tk works in scaled ones.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    screen = virtual_screen()
    if screen is None:
        print("The drawing window needs Windows: it covers the desktop Snowhush runs on.")
        return 1
    left, top, width, height, scale = screen
    hub = Hub(arguments.url)
    rects = []

    root = tk.Tk()
    root.title("Snowhush fake windows")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    status = tk.StringVar()
    overlay = None

    def publish():
        ok = hub.send(message(arguments.source, rects)) if rects else hub.send(json.dumps({"type": "clear", "source": arguments.source}))
        status.set(f"{len(rects)} invisible window(s)" + ("" if ok else " - hub not reachable at " + arguments.url))

    def low_quality():
        picture = ImageGrab.grab(bbox=(left, top, left + width, top + height), all_screens=True)
        small = picture.resize((max(1, width // arguments.blur), max(1, height // arguments.blur)), Image.BILINEAR)
        blurred = small.resize((width, height), Image.NEAREST)
        return ImageEnhance.Brightness(blurred).enhance(0.55)

    def draw():
        nonlocal overlay
        if overlay is not None:
            return
        root.withdraw()
        root.update()
        time.sleep(0.15)  # lets the panel disappear before the picture is taken
        photo = ImageTk.PhotoImage(low_quality())
        overlay = tk.Toplevel(root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.geometry(f"{width}x{height}{left:+d}{top:+d}")
        canvas = tk.Canvas(overlay, width=width, height=height, highlightthickness=0, cursor="crosshair")
        canvas.pack()
        canvas.photo = photo
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.create_text(24, 24, anchor="nw", fill="white", font=("Segoe UI", 14), text="Drag to draw a window for the snow. Esc cancels.")
        for x, y, w, h in rects:
            canvas.create_rectangle(x - left, y - top, x - left + w, y - top + h, outline="#6cf", dash=(4, 4))
        shape = {"start": None, "id": None}

        def ok(x0, y0, x1, y1):
            _, _, w, h = normalized(x0, y0, x1, y1)
            return w >= MIN_WIDTH * scale and h >= MIN_HEIGHT * scale

        def press(event):
            shape["start"] = (event.x, event.y)

        def move(event):
            if shape["start"] is None:
                return
            if shape["id"] is not None:
                canvas.delete(shape["id"])
            x0, y0 = shape["start"]
            colour = "#4f4" if ok(x0, y0, event.x, event.y) else "#f44"
            shape["id"] = canvas.create_rectangle(x0, y0, event.x, event.y, outline=colour, width=2, fill=colour, stipple="gray25")

        def release(event):
            if shape["start"] is None:
                return
            x0, y0 = shape["start"]
            if ok(x0, y0, event.x, event.y):
                x, y, w, h = normalized(x0, y0, event.x, event.y)
                rects.append((x + left, y + top, w, h))
                publish()
            finish()

        def finish(_event=None):
            nonlocal overlay
            overlay.destroy()
            overlay = None
            root.deiconify()

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", release)
        overlay.bind("<Escape>", finish)
        overlay.focus_force()

    def undo():
        if rects:
            rects.pop()
        publish()

    def clear():
        rects.clear()
        publish()

    def quit_():
        rects.clear()
        publish()
        hub.close()
        root.destroy()

    tk.Label(root, textvariable=status, padx=12, pady=8).pack()
    buttons = tk.Frame(root)
    buttons.pack(padx=8, pady=(0, 8))
    for text, command in (("Draw", draw), ("Undo", undo), ("Clear all", clear), ("Quit", quit_)):
        tk.Button(buttons, text=text, command=command, width=9).pack(side="left", padx=2)
    root.protocol("WM_DELETE_WINDOW", quit_)
    publish()
    root.after(100, draw)
    root.mainloop()
    return 0


def run_demo(arguments):
    """One bar moving up and down for a while, without any window."""
    hub = Hub(arguments.url)
    started = time.monotonic()
    print(f"sending a moving bar for {arguments.hold:.0f} s")
    while time.monotonic() - started < arguments.hold:
        y = 400 + 80 * (1 + math.sin((time.monotonic() - started) / 2))
        hub.send(message(arguments.source, [(560, y, 800, 60)]))
        time.sleep(0.05)
    hub.send(json.dumps({"type": "clear", "source": arguments.source}))
    hub.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--source", default="fake")
    parser.add_argument("--blur", type=int, default=8, help="how much quality the picture loses: 1 none, 8 default")
    parser.add_argument("--demo", action="store_true", help="no window, a moving bar")
    parser.add_argument("--hold", type=float, default=20, help="seconds for --demo")
    arguments = parser.parse_args()
    sys.exit(run_demo(arguments) if arguments.demo else run_window(arguments))
