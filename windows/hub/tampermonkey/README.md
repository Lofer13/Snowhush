# Snowhush for Tampermonkey

The same job as the Firefox extension, as a userscript, and the same menu for drawing rectangles by hand.

1. Start the hub **with `--allow-web-origins`**: `python hub.py --allow-web-origins`. A userscript connects with the
   Origin of its page, which the hub refuses otherwise. (With the flag, any page you open could talk to the hub, and so
   could put snow on your screen; leave it off when you use the extension instead.)
2. In Tampermonkey create a new script, paste `snowhush.user.js`, save.
3. Open `http://127.0.0.1:8765/test` (or any page), and click the Tampermonkey icon: **Draw a snow rectangle** and
   **Remove drawn rectangles of this page** are in the list of the script.

Each page connects on its own and is its own source in the hub. Snow shows only on the page in front, in the window that
has the focus; leave it, or close the tab, and the snow is put aside and comes back when the page does. The hub keeps
that for up to 64 pages.

Limits: some sites (YouTube among them) have a Content-Security-Policy that forbids connections to `ws://127.0.0.1`; the
script can't reach the hub there, and the extension (which isn't bound by it) is the way. Two tabs of the same page
share one source and override each other.
