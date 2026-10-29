# Snowhush for Firefox

Lets the snow of Snowhush settle on the elements of the page you are looking at: cards, the header, buttons, images,
anything with a visible top edge.

## Install (temporary, until Firefox restarts)

1. Start the hub (`python hub.py` in the folder above) and Snowhush with `SNOWHUSH_HUB=ws://127.0.0.1:8765`.
2. In Firefox open `about:debugging#/runtime/this-firefox`, press **Load Temporary Add-on...** and pick `manifest.json`
   in this folder.
3. **Reload the pages** you have open: a page only gets the extension's script when it loads.

For good, the folder has to be packed and signed by Mozilla (or loaded in Firefox Developer Edition / Nightly with
`xpinstall.signatures.required` set to `false`).

## What it does

- A page reports the rectangles of its solid elements (a background, a border, a shadow, or an image / video / input),
  80 at most, the ones whose whole top edge isn't covered by something else. Nothing but those rectangles leaves the
  page, and they go only to `ws://127.0.0.1` on this machine.
- The snow moves with the elements when the page scrolls, and with the window when you drag it.
- **Leave Firefox, or switch tabs, and the snow of the page goes away; come back and it is the same snow in the same
  place.** The extension reports the elements of the tab on top in the window that has the focus; the elements of
  every other tab, and all of them while another program has the focus, are reported as `hidden`, and Snowhush puts
  their snow aside. Close the tab or go to another page and its snow falls.

## If the snow is off

Run `python ../fake_client.py --mirror`: it outlines, on the screen, where the extension says the elements are. If the
outlines are off from the elements by a constant factor or a few pixels (browser zoom and a second display with another
scale are the usual causes), correct `CALIBRATION` at the top of `background.js` and reload the extension. If they
match and the snow still doesn't settle, look at Snowhush's side (see `../README.md`).

Known limits: elements inside iframes aren't reported; an element that is rotated or clipped by its parent is reported
as the rectangle it occupies.
