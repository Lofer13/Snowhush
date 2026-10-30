# Snowhush for Firefox

Lets the snow of Snowhush settle on the elements of the page you are looking at: cards, the header, buttons, images,
anything with a visible top edge.

## Install (temporary, until Firefox restarts)

1. Start the hub (`python hub.py` in the folder above), and tell Snowhush where it is: either start it with
   `SNOWHUSH_HUB=ws://127.0.0.1:8765` in its environment, or put that address on the first line of
   `%LOCALAPPDATA%\Snowhush\hub.txt` (the second works when it is started from the Start menu or at login) and restart it.
2. In Firefox open `about:debugging#/runtime/this-firefox`, press **Load Temporary Add-on...** and pick `manifest.json`
   in this folder.
3. **Reload the pages** you have open: a page only gets the extension's script when it loads.
4. Open **http://127.0.0.1:8765/test** (served by the hub) to see if it all works, see below.

For good, the folder has to be packed and signed by Mozilla (or loaded in Firefox Developer Edition / Nightly with
`xpinstall.signatures.required` set to `false`).

## What it does

- A page reports the rectangles of its solid elements (a background, a border, a shadow, or an image / video / input),
  80 at most, the ones whose whole top edge isn't covered by something else. Nothing but those rectangles leaves the
  page, and they go only to `ws://127.0.0.1` on this machine.
- The snow moves with the elements when the page scrolls, and with the window when you drag it.
- **Leave Firefox, or switch tabs, and the snow of the page goes away; come back and it is the same snow in the same
  place.** The extension reports the elements of the tab on top in the window that has the focus; every other element
  it has seen is reported as `hidden`, and Snowhush puts its snow aside as it is.
- **Close a tab, go to another page, scroll an element out of view: the snow is kept.** Elements are named by their page
  (host and path) and their place in the document, not by the tab, so when the same page is opened again, in any tab,
  its snow is back where it was. It is kept while Snowhush runs, for up to about a thousand elements.

## The test page

`http://127.0.0.1:8765/test` (also `/test2` and `/test3`, as other pages) has every kind of element on it, each marked
with whether snow should settle on it, and a panel that tells where the chain breaks:

- **hub**: the page came from it, so it is running;
- **Snowhush**: connected to the hub or not (if not: it wasn't started with `SNOWHUSH_HUB` or `hub.txt`, or was started before);
- **the extension**: whether its script is in this page (if not: reload the page after installing it);
- **elements sent** from this page, and what the hub has from Firefox.

The overlay draws what the extension decided: **green** outlines on the elements it reports, **red** dashed ones on
the boxes it skips, with the reason (top edge covered, no background or border, invisible, ...). Any page can ask for
the overlay with `data-snowhush-debug` on its `<html>`.

## If the snow is off

Run `python ../fake_client.py --mirror`: it outlines, on the screen, where the extension says the elements are. If the
outlines are off from the elements by a constant factor or a few pixels (browser zoom and a second display with another
scale are the usual causes), correct `CALIBRATION` at the top of `background.js` and reload the extension. If they
match and the snow still doesn't settle, look at Snowhush's side (see `../README.md`).

Known limits: elements inside iframes aren't reported; an element that is rotated or clipped by its parent is reported
as the rectangle it occupies.
