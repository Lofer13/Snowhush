// Snowhush for Firefox, the part that runs in every page: finds the elements snow could settle on and reports their
// rectangles to background.js, in CSS pixels of the viewport, together with where the viewport is on the screen.
(() => {
  "use strict";
  if (window.top !== window) return;
  const api = typeof browser !== "undefined" ? browser : chrome;

  const MIN_WIDTH = 80; // CSS pixels; Snowhush itself wants about 80 x 16 DIPs
  const MIN_HEIGHT = 20;
  const MAX_RECTS = 80; // Snowhush keeps the snow of away surfaces in a small store, so a page doesn't get more
  const MAX_SCAN = 5000;
  const SKIP = new Set(["HTML", "BODY", "HEAD", "SCRIPT", "STYLE", "LINK", "META", "TITLE", "NOSCRIPT", "TEMPLATE", "BR", "WBR"]);
  const REPLACED = new Set(["IMG", "VIDEO", "CANVAS", "INPUT", "TEXTAREA", "SELECT", "BUTTON", "IFRAME", "EMBED", "OBJECT"]);

  const ids = new WeakMap();
  let rects = [];
  let sent = "";
  let timer = 0;
  let lastRun = 0;
  let cost = 0;

  /** A name for an element that stays the same while it scrolls, and when you come back to the tab. */
  function idOf(element) {
    let id = ids.get(element);
    if (id) return id;
    const parts = [];
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
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
    id = parts.reverse().join(">").slice(-200);
    ids.set(element, id);
    return id;
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

  /** The whole top edge is in the clear, not partly under something else (a menu, a cookie banner, another card):
   * snow would settle on the covered part too, and be drawn over what covers it. */
  function topIsVisible(element, rect) {
    const y = Math.min(window.innerHeight - 1, Math.max(0, rect.top + 2));
    let seen = 0;
    for (const fraction of [0.1, 0.3, 0.5, 0.7, 0.9]) {
      const x = rect.left + rect.width * fraction;
      if (x < 0 || x >= window.innerWidth) continue;
      const hit = document.elementFromPoint(x, y);
      if (!hit || !(hit === element || element.contains(hit))) return false;
      seen++;
    }
    return seen > 0;
  }

  function collect() {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const all = document.body ? document.body.getElementsByTagName("*") : [];
    const found = [];
    const names = new Set();
    for (let i = 0; i < all.length && i < MAX_SCAN && found.length < MAX_RECTS; i++) {
      const element = all[i];
      if (SKIP.has(element.tagName) || element instanceof SVGElement) continue;
      const rect = element.getBoundingClientRect();
      if (rect.width < MIN_WIDTH || rect.height < MIN_HEIGHT) continue;
      // The top edge has to be on screen: it is what the snow settles on.
      if (rect.top < 1 || rect.top > height - MIN_HEIGHT || rect.right <= 0 || rect.left >= width) continue;
      if (rect.width >= width * 0.98 && rect.height >= height * 0.8) continue; // a wrapper of the whole page
      const style = getComputedStyle(element);
      if (style.visibility !== "visible" || style.display === "none" || parseFloat(style.opacity) < 0.3) continue;
      if (!isSolid(element, style)) continue;
      // The outermost element wins where a parent and its child start at the same height.
      if (found.some((other) => Math.abs(other.y - rect.top) < 3 && Math.min(other.x + other.w, rect.right) - Math.max(other.x, rect.left) > rect.width * 0.5)) continue;
      if (!topIsVisible(element, rect)) continue;
      const id = idOf(element);
      if (names.has(id)) continue;
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
    if (!force && text === sent) return;
    sent = text;
    try {
      const result = api.runtime.sendMessage(message);
      if (result && result.catch) result.catch(() => {});
    } catch (error) {
      // The extension was reloaded or removed; this script is a leftover.
    }
  }

  function run(force) {
    timer = 0;
    if (document.hidden) return;
    const started = performance.now();
    rects = collect();
    cost = performance.now() - started;
    lastRun = performance.now();
    send(force === true);
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
  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "style", "hidden", "open"],
  });
  setInterval(schedule, 800); // animations and layout that moves without telling anyone
  // Dragging the browser window changes nothing in the page, only where it is on the screen.
  setInterval(() => {
    if (!document.hidden && rects.length) send(false);
  }, 100);
  api.runtime.onMessage.addListener((message) => {
    if (message && message.type === "refresh") run(true);
  });

  schedule();
})();
