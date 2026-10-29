// Snowhush for Firefox, the part that talks to the hub. The pages report the rectangles of their elements; this turns
// them into physical pixels of the screen and passes on only those of the tab you are looking at in the window you are
// in. The elements of every other tab, and all of them while you are in another program, are reported as "hidden":
// Snowhush puts their snow aside as it is, and settles it again in the same place when they come back.
"use strict";

const HUB_URL = "ws://127.0.0.1:8765";
const SOURCE = "firefox";
// Snowhush keeps the snow of about 200 away surfaces; a few less leaves room for what is on screen.
const MAX_HIDDEN = 160;
// If the snow lands off from the elements, a pixel or two or by a constant factor, this is where to correct it.
// python fake_client.py --mirror outlines where the rectangles are said to be.
const CALIBRATION = { scale: 1, dx: 0, dy: 0 };

const tabs = new Map(); // tabId -> { rects, geom } as the page reported them
const activeTab = new Map(); // windowId -> the tab on top in it
let focusedWindow = browser.windows.WINDOW_ID_NONE;
let socket = null;
let retryTimer = 0;
let retry = 1000;
let flushTimer = 0;
let lastSent = "";

function number(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function toScreen(tabId, entry) {
  const k = entry.geom.dpr * CALIBRATION.scale;
  return entry.rects.map((r) => ({
    id: tabId + ":" + r.id,
    x: (entry.geom.sx + r.x) * k + CALIBRATION.dx,
    y: (entry.geom.sy + r.y) * k + CALIBRATION.dy,
    w: r.w * k,
    h: r.h * k,
    radius: r.radius * k,
  }));
}

function build() {
  const visible = activeTab.get(focusedWindow); // nothing while no Firefox window has the focus
  const rects = [];
  const hidden = [];
  for (const [tabId, entry] of tabs) {
    const list = toScreen(tabId, entry);
    if (tabId === visible) rects.push(...list);
    else for (const r of list) hidden.push(r.id);
  }
  return { type: "surfaces", source: SOURCE, rects, hidden: hidden.slice(0, MAX_HIDDEN) };
}

function flush() {
  flushTimer = 0;
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  const text = JSON.stringify(build());
  if (text === lastSent) return;
  lastSent = text;
  socket.send(text);
}

/** Sends the state soon; many changes in a moment go out as one. */
function update() {
  if (!flushTimer) flushTimer = setTimeout(flush, 30);
}

function lost() {
  if (socket) {
    socket.onopen = socket.onclose = socket.onerror = null;
    try {
      socket.close();
    } catch (error) {}
    socket = null;
  }
  clearTimeout(retryTimer);
  retryTimer = setTimeout(connect, retry);
  retry = Math.min(retry * 2, 10000);
}

function connect() {
  try {
    socket = new WebSocket(HUB_URL);
  } catch (error) {
    socket = null;
    lost();
    return;
  }
  socket.onopen = () => {
    retry = 1000;
    lastSent = ""; // the hub may have been restarted: it knows nothing yet
    update();
  };
  socket.onclose = lost;
  socket.onerror = lost;
}

/** Asks the page for rectangles that are right now: it may have been scrolled or moved while away. */
function refresh(tabId) {
  browser.tabs.sendMessage(tabId, { type: "refresh" }).catch(() => {});
}

browser.runtime.onMessage.addListener((message, sender) => {
  const tabId = sender.tab && sender.tab.id;
  if (tabId === undefined || !message) return;
  if (message.type === "state" && Array.isArray(message.rects) && message.geom) {
    const geom = { sx: number(message.geom.sx), sy: number(message.geom.sy), dpr: number(message.geom.dpr) || 1 };
    const rects = message.rects.slice(0, 200).map((r) => ({
      id: String(r.id).slice(0, 200),
      x: number(r.x),
      y: number(r.y),
      w: number(r.w),
      h: number(r.h),
      radius: number(r.radius),
    }));
    tabs.set(tabId, { rects, geom });
    update();
  } else if (message.type === "gone") {
    tabs.delete(tabId); // navigated away or closed: its snow falls
    update();
  }
});

browser.tabs.onActivated.addListener(({ tabId, windowId }) => {
  activeTab.set(windowId, tabId);
  refresh(tabId);
  update();
});

browser.tabs.onRemoved.addListener((tabId) => {
  tabs.delete(tabId);
  update();
});

browser.windows.onFocusChanged.addListener((windowId) => {
  focusedWindow = windowId; // WINDOW_ID_NONE when another program has the focus
  const tabId = activeTab.get(windowId);
  if (tabId !== undefined) refresh(tabId);
  update();
});

browser.windows.onRemoved.addListener((windowId) => {
  activeTab.delete(windowId);
  update();
});

browser.tabs.query({ active: true }).then((list) => {
  for (const tab of list) activeTab.set(tab.windowId, tab.id);
  return browser.windows.getLastFocused();
}).then((window) => {
  if (window.focused) focusedWindow = window.id;
  update();
}).catch(() => {});

connect();
