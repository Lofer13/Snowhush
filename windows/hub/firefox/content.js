// Snowhush for Firefox, the part that runs in every page: finds the elements snow could settle on and reports their
// rectangles to background.js, in CSS pixels of the viewport, together with where the viewport is on the screen.
//
// Ids name an element by its page (host and path) and its place in the document, so they are the same when the page
// is opened again, in this tab or another: that is what lets the snow come back to it.
//
// A page that has the attribute data-snowhush-debug on <html> (hub/test.html does) gets an overlay: green outlines on the
// elements that are reported, red ones, with the reason, on the ones that are not.
(() => {
  "use strict";
  if (window.top !== window) return;
  const api = typeof browser !== "undefined" ? browser : chrome;
  const root = document.documentElement;

  const MIN_WIDTH = 80; // CSS pixels; Snowhush itself wants about 80 x 16 DIPs
  const MIN_HEIGHT = 20;
  const MAX_RECTS = 80; // Snowhush keeps the snow of away surfaces in a store of limited size
  const MAX_SCAN = 5000;
  const SKIP = new Set(["HTML", "BODY", "HEAD", "SCRIPT", "STYLE", "LINK", "META", "TITLE", "NOSCRIPT", "TEMPLATE", "BR", "WBR"]);
  const REPLACED = new Set(["IMG", "VIDEO", "CANVAS", "INPUT", "TEXTAREA", "SELECT", "BUTTON", "IFRAME", "EMBED", "OBJECT"]);

  const BOXLIKE = new Set(["DIV", "SECTION", "ARTICLE", "ASIDE", "NAV", "HEADER", "FOOTER", "MAIN", "FIGURE", "UL", "OL", "TABLE", "FORM", "DETAILS"]);

  /** A layout container: it holds boxes of its own, so the boxes are the ones to look at. */
  function hasBigChild(element) {
    return Array.prototype.some.call(element.children, (child) => {
      if (!BOXLIKE.has(child.tagName) && !REPLACED.has(child.tagName)) return false; // a line of text isn't a box
      const r = child.getBoundingClientRect();
      return r.width >= MIN_WIDTH && r.height >= MIN_HEIGHT;
    });
  }

  const paths = new WeakMap();
  let rects = [];
  let rejected = [];
  let sent = "";
  let timer = 0;
  let lastRun = 0;
  let cost = 0;
  let overlay = null;

  root.setAttribute("data-snowhush", "1");

  function hash(text) {
    let h1 = 0xdeadbeef;
    let h2 = 0x41c6ce57;
    for (let i = 0; i < text.length; i++) {
      const c = text.charCodeAt(i);
      h1 = Math.imul(h1 ^ c, 2654435761);
      h2 = Math.imul(h2 ^ c, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (h2 >>> 0).toString(36) + (h1 >>> 0).toString(36);
  }

  /** Where the element is in the document, as a path that doesn't change while the page is open. */
  function pathOf(element) {
    let path = paths.get(element);
    if (path) return path;
    const parts = [];
    for (let node = element; node && node !== root; node = node.parentElement) {
      if (node.id && /^[A-Za-z][\w-]{0,40}$/.test(node.id) && document.getElementById(node.id) === node) {
        parts.push("#" + node.id);
        break;
      }
      let index = 1;
      for (let sibling = node.previousElementSibling; sibling; sibling = sibling.previousElementSibling) {
        if (sibling.tagName === node.tagName) index++;
      }
      parts.push(node.tagName.toLowerCase() + index);
    }
    path = parts.reverse().join(">");
    paths.set(element, path);
    return path;
  }

  /** Short and the same for the same element of the same page, whichever tab shows it, and after a restart. */
  function idOf(element) {
    return hash(location.hostname + location.pathname + "|" + pathOf(element));
  }

  function alpha(color) {
    const match = /rgba?\(([^)]+)\)/.exec(color);
    if (!match) return 0;
    const parts = match[1].split(/[\s,\/]+/).filter(Boolean);
    return parts.length >= 4 ? parseFloat(parts[3]) : 1;
  }

  /** Something you can see the edge of, rather than an invisible box around text. */
  function isSolid(element, style) {
    if (REPLACED.has(element.tagName)) return true;
    if (alpha(style.backgroundColor) > 0.3) return true;
    if (style.backgroundImage !== "none") return true;
    if (style.boxShadow !== "none") return true;
    return parseFloat(style.borderTopWidth) > 0 && style.borderTopStyle !== "none" && alpha(style.borderTopColor) > 0.3;
  }

  /** What covers the top edge, or null if it is all in the clear (not partly under a menu, a banner, another card):
   * snow would settle on the covered part too, and be drawn over what covers it. */
  function coveredBy(element, rect) {
    const y = Math.min(window.innerHeight - 1, Math.max(0, rect.top + 2));
    for (const fraction of [0.1, 0.3, 0.5, 0.7, 0.9]) {
      const x = rect.left + rect.width * fraction;
      if (x < 0 || x >= window.innerWidth) continue;
      const hit = document.elementFromPoint(x, y);
      if (!hit) return "nothing at its top edge";
      if (hit !== element && !element.contains(hit)) return hit.tagName.toLowerCase() + (hit.id ? "#" + hit.id : "");
    }
    return null;
  }

  function collect(notes) {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const all = document.body ? document.body.getElementsByTagName("*") : [];
    const found = [];
    const names = new Set();
    const no = (rect, reason) => {
      if (notes && notes.length < 200) notes.push({ x: rect.left, y: rect.top, w: rect.width, h: rect.height, reason });
    };
    for (let i = 0; i < all.length && i < MAX_SCAN; i++) {
      const element = all[i];
      if (SKIP.has(element.tagName) || element instanceof SVGElement) continue;
      if (overlay && overlay.contains(element)) continue;
      const rect = element.getBoundingClientRect();
      if (rect.width < MIN_WIDTH || rect.height < MIN_HEIGHT) continue; // too small to say anything about
      if (rect.right <= 0 || rect.left >= width || rect.bottom <= 0 || rect.top >= height) continue;
      // The top edge has to be on screen: it is what the snow settles on.
      if (rect.top < 1 || rect.top > height - MIN_HEIGHT) {
        no(rect, "top edge is off screen");
        continue;
      }
      if (rect.width >= width * 0.98 && rect.height >= height * 0.8) {
        no(rect, "wrapper of the whole page");
        continue;
      }
      const style = getComputedStyle(element);
      if (style.visibility !== "visible" || style.display === "none" || parseFloat(style.opacity) < 0.3) {
        no(rect, "invisible");
        continue;
      }
      if (!isSolid(element, style)) {
        // Only said of the boxes someone might have expected snow on, not of every heading, paragraph and layout row.
        if (notes && BOXLIKE.has(element.tagName) && rect.width < width * 0.9 && !hasBigChild(element)) {
          no(rect, "no visible edge (no background, border or shadow)");
        }
        continue;
      }
      // The outermost element wins where a parent and its child start at the same height.
      if (found.some((other) => Math.abs(other.y - rect.top) < 3 && Math.min(other.x + other.w, rect.right) - Math.max(other.x, rect.left) > rect.width * 0.5)) {
        no(rect, "starts where its parent does");
        continue;
      }
      const cover = coveredBy(element, rect);
      if (cover) {
        no(rect, "top edge covered by " + cover);
        continue;
      }
      const id = idOf(element);
      if (names.has(id)) continue;
      if (found.length >= MAX_RECTS) {
        no(rect, "more than " + MAX_RECTS + " elements on the page");
        continue;
      }
      names.add(id);
      found.push({
        id,
        x: Math.round(rect.left * 10) / 10,
        y: Math.round(rect.top * 10) / 10,
        w: Math.round(rect.width * 10) / 10,
        h: Math.round(rect.height * 10) / 10,
        radius: Math.min(parseFloat(style.borderTopLeftRadius) || 0, rect.width / 2, rect.height / 2),
      });
    }
    return found;
  }

  /** Where the viewport is on the screen. mozInnerScreenX is in CSS pixels; times devicePixelRatio it is physical pixels. */
  function geometry() {
    const left = window.mozInnerScreenX !== undefined ? window.mozInnerScreenX : window.screenX;
    const top = window.mozInnerScreenY !== undefined ? window.mozInnerScreenY : window.screenY;
    return { sx: left, sy: top, dpr: window.devicePixelRatio || 1 };
  }

  function send(force) {
    const message = { type: "state", rects, geom: geometry() };
    const text = JSON.stringify(message);
    root.setAttribute("data-snowhush-count", String(rects.length));
    if (!force && text === sent) return;
    sent = text;
    try {
      const result = api.runtime.sendMessage(message);
      if (result && result.catch) result.catch(() => {});
    } catch (error) {
      // The extension was reloaded or removed; this script is a leftover.
    }
  }

  // The overlay of a page that asks for it.

  function box(layer, rect, color, dashed, label) {
    const element = document.createElement("div");
    element.style.cssText =
      "position:fixed;box-sizing:border-box;pointer-events:none;border:2px " + (dashed ? "dashed " : "solid ") + color +
      ";left:" + rect.x + "px;top:" + rect.y + "px;width:" + rect.w + "px;height:" + rect.h + "px;";
    if (label) {
      const text = document.createElement("span");
      text.textContent = label;
      text.style.cssText = "position:absolute;left:0;top:0;font:10px/1.2 monospace;padding:1px 3px;color:#fff;background:" + color + ";max-width:100%;overflow:hidden;white-space:nowrap";
      element.appendChild(text);
    }
    layer.appendChild(element);
  }

  function draw() {
    const wanted = root.hasAttribute("data-snowhush-debug");
    if (!wanted) {
      if (overlay) {
        overlay.remove();
        overlay = null;
      }
      return;
    }
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "snowhush-debug-layer";
      overlay.style.cssText = "position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none";
      root.appendChild(overlay);
    }
    overlay.textContent = "";
    for (const note of rejected) box(overlay, note, "#d33", true, note.reason);
    for (const rect of rects) box(overlay, rect, "#1a9a3a", false, null);
  }

  // Rectangles you draw (the button of the extension): kept for the page, where you drew them in the document.
  const STORE = "drawn:" + location.hostname + location.pathname;
  let drawn = [];
  api.storage.local.get(STORE).then((got) => {
    drawn = Array.isArray(got[STORE]) ? got[STORE] : [];
    schedule();
  }, () => {});
  const saveDrawn = () => api.storage.local.set({ [STORE]: drawn.slice(-40) }).catch(() => {});

  function drawnRects() {
    const out = [];
    for (const d of drawn) {
      const x = d.x - window.scrollX;
      const y = d.y - window.scrollY;
      if (y < 1 || y > window.innerHeight - 4 || x + d.w <= 0 || x >= window.innerWidth) continue;
      out.push({ id: d.id, x, y, w: d.w, h: d.h, radius: 0 });
    }
    return out;
  }

  function startDrawing() {
    if (document.getElementById("snowhush-draw-layer")) return;
    const layer = document.createElement("div");
    layer.id = "snowhush-draw-layer";
    layer.style.cssText = "position:fixed;inset:0;z-index:2147483647;cursor:crosshair;background:rgba(30,60,120,.15);";
    const hint = document.createElement("div");
    hint.textContent = "Drag a rectangle where snow should settle (its top edge). Esc cancels.";
    hint.style.cssText = "position:absolute;left:50%;top:12px;transform:translateX(-50%);font:14px system-ui;color:#fff;background:#123c;padding:6px 12px;border-radius:8px;";
    const rubber = document.createElement("div");
    layer.append(hint, rubber);
    root.appendChild(layer);
    let from = null;
    const finish = () => {
      layer.remove();
      removeEventListener("keydown", onKey, true);
    };
    const onKey = (event) => {
      if (event.key === "Escape") finish();
    };
    addEventListener("keydown", onKey, true);
    const area = (event) => ({
      x: Math.min(from.x, event.clientX),
      y: Math.min(from.y, event.clientY),
      w: Math.abs(event.clientX - from.x),
      h: Math.abs(event.clientY - from.y),
    });
    layer.addEventListener("pointerdown", (event) => {
      from = { x: event.clientX, y: event.clientY };
      layer.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    layer.addEventListener("pointermove", (event) => {
      if (!from) return;
      const r = area(event);
      rubber.style.cssText = "position:absolute;border:2px solid #1a9a3a;background:#1a9a3a33;left:" + r.x + "px;top:" + r.y + "px;width:" + r.w + "px;height:" + r.h + "px;";
    });
    layer.addEventListener("pointerup", (event) => {
      if (!from) return;
      const r = area(event);
      finish();
      if (r.w >= 40 && r.h >= 12) {
        drawn.push({ id: "d" + hash(location.hostname + location.pathname + "|" + Date.now() + Math.random()), x: r.x + window.scrollX, y: r.y + window.scrollY, w: r.w, h: r.h });
        saveDrawn();
        run(true);
      }
    });
  }

  function run(force) {
    timer = 0;
    if (document.hidden) return;
    const started = performance.now();
    const debug = root.hasAttribute("data-snowhush-debug");
    rejected = [];
    rects = collect(debug ? rejected : null).concat(drawnRects());
    cost = performance.now() - started;
    lastRun = performance.now();
    send(force === true);
    draw();
  }

  /** Looks again soon, but not more often than the page can spare: a heavy page is scanned less often. */
  function schedule() {
    if (timer) return;
    const wait = Math.max(0, lastRun + Math.max(60, cost * 6) - performance.now());
    timer = setTimeout(run, wait);
  }

  document.addEventListener("scroll", schedule, { capture: true, passive: true });
  window.addEventListener("resize", schedule);
  window.addEventListener("load", schedule);
  window.addEventListener("pageshow", schedule);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) schedule();
  });
  window.addEventListener("pagehide", () => {
    try {
      const result = api.runtime.sendMessage({ type: "gone" });
      if (result && result.catch) result.catch(() => {});
    } catch (error) {}
  });
  new MutationObserver((records) => {
    // What the overlay itself changes isn't the page changing.
    if (overlay && records.every((record) => overlay.contains(record.target) || record.target === overlay)) return;
    schedule();
  }).observe(root, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "style", "hidden", "open", "data-snowhush-debug"],
  });
  setInterval(schedule, 800); // animations and layout that moves without telling anyone
  // Dragging the browser window changes nothing in the page, only where it is on the screen.
  setInterval(() => {
    if (!document.hidden && rects.length) send(false);
  }, 100);
  api.runtime.onMessage.addListener((message) => {
    if (message && message.type === "refresh") run(true);
    if (message && message.type === "draw") startDrawing();
    if (message && message.type === "undraw") {
      drawn = [];
      saveDrawn();
      run(true);
    }
  });

  schedule();
})();
