"""Draws invisible windows for the snow to settle on, to try Snowhush without a browser extension.

    pip install pillow            (and websockets, for --mode hub)
    python fake_client.py

A dimmed, low quality picture of your screen covers the desktop. Press the mouse and drag to draw a rectangle, as when
selecting icons on the desktop; green is big enough for snow to settle on, red is too small. When you let go, the picture
goes away and the rectangle stays behind as an invisible window. A small panel keeps count and lets you draw another
one, undo or remove them all.

Two ways to make the window real to Snowhush:

  --mode windows   (default) A real top-level window, so even an unchanged Snowhush sees it: no border, no title bar,
                   no taskbar button, never takes focus, and you can click through it. It has to avoid what Snowhush
                   skips on purpose: windows that are click-through by style, or mostly transparent (alpha under 30%),
                   or cut out by a colour key, or drawn with per-pixel alpha. So it is not "layered" at all. It is
                   invisible because nothing is ever drawn into it, and it is click-through because its shape
                   is cut down to a thin strip along the top edge, the part the snow rests on.
  --mode hub       Sends the rectangles to the hub (hub.py) for a Snowhush started with SNOWHUSH_HUB.

  --show           Makes the windows visible (a blue box), to see where they are and tell "Snowhush ignores it"
                   from "Snowhush doesn't work at all".
  --demo           No window: one bar that moves up and down for 20 seconds, sent to the hub.
  --mirror         Draws a blue outline where the other programs (the Firefox extension, Unity) say their rectangles are,
                   to check that their coordinates land on the right pixels. The outlines are click-through windows, which
                   Snowhush ignores, so they add no snow of their own.

Coordinates are physical pixels of the virtual desktop, y pointing down (see README.md).
In the tray menu of Snowhush, "Snow on Windows" must be on and "Behind Windows" off.
"""

import argparse
import atexit
import ctypes
import json
import math
import sys
import time

# What Snowhush settles on, in DIPs: its window list takes 80 x 40 and up (src/tracker.rs), the hub's rectangles 80 x 16.
MIN_WIDTH = 80
MIN_HEIGHT_WINDOW = 40
MIN_HEIGHT_HUB = 16
# How much of a window is left to click on: just a strip along its top edge, in physical pixels.
STRIP = 2


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
        from websockets.sync.client import connect

        for _ in range(2):
            try:
                if self.socket is None:
                    # Entered by hand: newer versions of websockets want connect() used like this, older ones return the connection.
                    self.socket = connect(self.url, open_timeout=2).__enter__()
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


class FakeWindows:
    """Real windows, one per rectangle, that Snowhush takes for ordinary ones. Windows only; needs a message loop in
    this thread (Tk's is one), or Windows takes the program for hung and puts a ghost over its windows."""

    WS_POPUP = 0x80000000
    WS_VISIBLE = 0x10000000
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080  # no taskbar button, not in Alt+Tab
    WS_EX_NOACTIVATE = 0x08000000  # never takes focus
    WS_EX_NOREDIRECTIONBITMAP = 0x00200000  # no surface to draw on: shows nothing
    SWP_NOACTIVATE = 0x0010

    WS_EX_TRANSPARENT = 0x00000020  # click-through by style: Snowhush leaves such windows out

    def __init__(self, show, outline=False):
        from ctypes import wintypes

        self.show = show
        self.outline = outline
        self.windows = []  # (handle, x, y, w, h)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32, gdi32 = self.user32, self.gdi32

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HANDLE),
                ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        kernel32.GetModuleHandleW.restype = wintypes.HANDLE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_void_p,
        ]  # fmt: skip
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]  # fmt: skip
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        gdi32.CombineRgn.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_int]
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        gdi32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        gdi32.CreateSolidBrush.restype = wintypes.HANDLE
        gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]

        self.instance = kernel32.GetModuleHandleW(None)
        self.class_name = "SnowhushFakeWindow"
        window_class = WNDCLASSW()
        # The system's own procedure: nothing here ever needs to answer a message differently.
        window_class.lpfnWndProc = ctypes.cast(user32.DefWindowProcW, ctypes.c_void_p).value
        window_class.hInstance = self.instance
        window_class.lpszClassName = self.class_name
        window_class.hbrBackground = gdi32.CreateSolidBrush(0xE0A050) if show else None  # BGR: a light blue
        if not user32.RegisterClassW(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())
        atexit.register(self.sync, [])

    def sync(self, rects):
        """Makes the windows match these (x, y, w, h) rectangles: moves the ones that stay, adds, removes."""
        wanted = [tuple(int(round(v)) for v in rect) for rect in rects]
        # Keeps windows that are still wanted where they are; a window is cheaper to leave than to remake.
        kept = []
        for window in self.windows:
            if window[1:] in wanted:
                wanted.remove(window[1:])
                kept.append(window)
            else:
                self.user32.DestroyWindow(window[0])
        self.windows = kept + [self.create(*rect) for rect in wanted]

    def create(self, x, y, w, h):
        style = self.WS_EX_TOPMOST | self.WS_EX_TOOLWINDOW | self.WS_EX_NOACTIVATE
        if self.outline:
            style |= self.WS_EX_TRANSPARENT
        if not self.show:
            style |= self.WS_EX_NOREDIRECTIONBITMAP
        handle = self.user32.CreateWindowExW(
            style, self.class_name, "Snowhush fake window", self.WS_POPUP | self.WS_VISIBLE, x, y, w, h, None, None, self.instance, None
        )
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if self.outline:
            # Only a 3 px frame is part of the window.
            frame = self.gdi32.CreateRectRgn(0, 0, w, h)
            inside = self.gdi32.CreateRectRgn(3, 3, max(3, w - 3), max(3, h - 3))
            self.gdi32.CombineRgn(frame, frame, inside, 4)  # RGN_DIFF
            self.user32.SetWindowRgn(handle, frame, True)
        elif not self.show:
            # Only a strip along the top is part of the window: the rest of the rectangle is click-through, not part of it.
            self.user32.SetWindowRgn(handle, self.gdi32.CreateRectRgn(0, 0, w, min(STRIP, h)), True)
        return (handle, x, y, w, h)


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
    by_hub = arguments.mode == "hub"
    min_height = MIN_HEIGHT_HUB if by_hub else MIN_HEIGHT_WINDOW
    hub = Hub(arguments.url) if by_hub else None
    fakes = None if by_hub else FakeWindows(arguments.show)
    rects = []

    root = tk.Tk()
    root.title("Snowhush fake windows")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    status = tk.StringVar()
    overlay = None

    def publish():
        problem = ""
        try:
            if by_hub:
                sent = hub.send(message(arguments.source, rects) if rects else json.dumps({"type": "clear", "source": arguments.source}))
                problem = "" if sent else " - hub not reachable at " + arguments.url
            else:
                fakes.sync(rects)
        except Exception as error:
            problem = f" - {error}"
        status.set(f"{len(rects)} invisible window(s)" + problem)

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
            return w >= MIN_WIDTH * scale and h >= min_height * scale

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
                finish()  # the picture is gone before the window appears
                publish()
            else:
                finish()

        def finish(_event=None):
            nonlocal overlay
            if overlay is not None:
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
        if hub is not None:
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


def run_mirror(arguments):
    """Outlines of the rectangles the other programs send to the hub, as they would land on the screen."""
    import queue
    import threading
    import tkinter as tk

    from websockets.sync.client import connect

    if sys.platform != "win32":
        print("The mirror needs Windows: it draws on the desktop Snowhush runs on.")
        return 1
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
    fakes = FakeWindows(show=True, outline=True)
    incoming = queue.Queue()
    stop = threading.Event()

    def listen():
        while not stop.is_set():
            try:
                with connect(arguments.url, open_timeout=2) as socket:
                    incoming.put(("status", f"listening at {arguments.url}"))
                    for text in socket:
                        incoming.put(("message", text))
            except Exception:
                incoming.put(("status", f"hub not reachable at {arguments.url}, trying again"))
                stop.wait(1.0)

    threading.Thread(target=listen, daemon=True).start()
    sources = {}
    root = tk.Tk()
    root.title("Snowhush mirror")
    root.attributes("-topmost", True)
    status = tk.StringVar(value="starting")
    tk.Label(root, textvariable=status, padx=12, pady=8).pack()
    tk.Button(root, text="Quit", command=root.destroy, width=9).pack(pady=(0, 8))

    def poll():
        changed = False
        while True:
            try:
                kind, value = incoming.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                status.set(value)
                continue
            try:
                data = json.loads(value)
                source = data["source"]
                if data["type"] == "surfaces":
                    sources[source] = [(r["x"], r["y"], r["w"], r["h"]) for r in data.get("rects", [])]
                    changed = True
                elif data["type"] == "clear":
                    sources.pop(source, None)
                    changed = True
            except (ValueError, KeyError, TypeError):
                pass  # "hello" and the like
        if changed:
            fakes.sync([rect for rects in sources.values() for rect in rects if rect[2] >= 1 and rect[3] >= 1])
            status.set(f"{sum(len(r) for r in sources.values())} rectangle(s) from {len(sources)} source(s)")
        root.after(30, poll)

    root.after(30, poll)
    root.mainloop()
    stop.set()
    fakes.sync([])
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
    parser.add_argument("--mode", choices=("windows", "hub"), default="windows")
    parser.add_argument("--show", action="store_true", help="make the windows visible, to see where they are")
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--source", default="fake")
    parser.add_argument("--blur", type=int, default=8, help="how much quality the picture loses: 1 none, 8 default")
    parser.add_argument("--demo", action="store_true", help="no window, a moving bar sent to the hub")
    parser.add_argument("--mirror", action="store_true", help="outline where other programs say their rectangles are")
    parser.add_argument("--hold", type=float, default=20, help="seconds for --demo")
    arguments = parser.parse_args()
    if arguments.mirror:
        sys.exit(run_mirror(arguments))
    sys.exit(run_demo(arguments) if arguments.demo else run_window(arguments))
