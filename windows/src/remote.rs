//! Surfaces reported by other programs: a Firefox extension with the rectangles of page elements, a Unity script with
//! those of its windows. Snowhush connects as a client to a local hub (a WebSocket server on this machine) and the
//! hub passes on what the others send. The snow settles on those rectangles like on a window.
//!
//! Messages are JSON text. Snowhush sends `{"type":"hello","role":"snowhush"}` once connected, and listens for
//!
//! ```text
//! {"type":"surfaces","source":"firefox","rects":[{"id":"nav","x":100,"y":200,"w":600,"h":48,"radius":8}],"hidden":["footer"]}
//! {"type":"clear","source":"firefox"}
//! ```
//!
//! Coordinates are physical pixels on the virtual desktop, y pointing down, as Windows reports its own windows.
//! A `surfaces` message replaces everything its `source` sent before. `hidden` lists ids that are away for now, as
//! when the program lost focus or the page is on another tab: their snow is put aside as it is, and settles again, in
//! the same place and the same amount, when the id comes back in `rects`. `clear` and ids in neither list let the snow
//! fall. Anything else is ignored.

use std::collections::{HashMap, HashSet};
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use serde_json::Value;
use tungstenite::stream::MaybeTlsStream;
use tungstenite::{Message, WebSocket};

use crate::geometry::Rect;
use crate::simulation::{WindowId, WindowSurface};

/// More than this from one source is a mistake or abuse; the rest is dropped.
const MAX_RECTS: usize = 512;
/// Ids kept away for one source; a few thousand elements of old pages is as many as anyone wants snow back on.
const MAX_HIDDEN: usize = 2048;
/// A message larger than this closes the connection.
const MAX_MESSAGE: usize = 1 << 20;
/// Smallest rectangle the snow settles on, in DIPs.
const MIN_WIDTH: f32 = 80.0;
const MIN_HEIGHT: f32 = 16.0;

/// A rectangle from another program, in physical pixels of the virtual desktop.
#[derive(Clone, Debug, PartialEq)]
pub struct RemoteRect {
    pub id: WindowId,
    pub x: f32,
    pub y: f32,
    pub width: f32,
    pub height: f32,
    pub radius: f32,
}

/// What came in on one message.
#[derive(Debug, PartialEq)]
pub enum Update {
    Surfaces { source: String, rects: Vec<RemoteRect>, hidden: Vec<WindowId> },
    Clear { source: String },
}

/// Reads one message from the hub; `None` for anything that isn't a valid `surfaces` or `clear`.
pub fn parse(text: &str) -> Option<Update> {
    let message: Value = serde_json::from_str(text).ok()?;
    let source = message.get("source")?.as_str()?.to_string();
    if source.is_empty() || source.len() > 64 {
        return None;
    }
    match message.get("type")?.as_str()? {
        "clear" => Some(Update::Clear { source }),
        "surfaces" => {
            let rects = message
                .get("rects")?
                .as_array()?
                .iter()
                .filter_map(|rect| {
                    let number = |key: &str| rect.get(key).and_then(Value::as_f64).filter(|n| n.is_finite()).map(|n| n as f32);
                    let (x, y, width, height) = (number("x")?, number("y")?, number("w")?, number("h")?);
                    if width <= 0.0 || height <= 0.0 {
                        return None;
                    }
                    let name = match rect.get("id")? {
                        Value::String(name) => name.clone(),
                        Value::Number(number) => number.to_string(),
                        _ => return None,
                    };
                    let radius = number("radius").unwrap_or(0.0).max(0.0);
                    Some(RemoteRect { id: surface_id(&source, &name), x, y, width, height, radius })
                })
                .take(MAX_RECTS)
                .collect();
            let hidden = message
                .get("hidden")
                .and_then(Value::as_array)
                .map(|ids| {
                    ids.iter()
                        .filter_map(|id| match id {
                            Value::String(name) => Some(surface_id(&source, name)),
                            Value::Number(number) => Some(surface_id(&source, &number.to_string())),
                            _ => None,
                        })
                        .take(MAX_HIDDEN)
                        .collect()
                })
                .unwrap_or_default();
            Some(Update::Surfaces { source, rects, hidden })
        }
        _ => None,
    }
}

/// A stable id for a rectangle, so its snow stays with it from one message to the next. Always negative:
/// the handles of real windows never are, so the two kinds can't be mistaken for each other.
pub fn surface_id(source: &str, id: &str) -> WindowId {
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in source.bytes().chain(std::iter::once(b'/')).chain(id.bytes()) {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    (hash as usize | (1 << (usize::BITS - 1))) as isize
}

/// Only a hub on this machine: nothing else may place snow, and nothing here is encrypted.
pub fn is_loopback(url: &str) -> bool {
    let Some(rest) = url.strip_prefix("ws://") else { return false };
    let host = rest.split(['/', '?']).next().unwrap_or("");
    let host = if let Some(inner) = host.strip_prefix('[') {
        inner.split(']').next().unwrap_or("")
    } else {
        host.rsplit_once(':').map_or(host, |(name, _)| name)
    };
    matches!(host, "127.0.0.1" | "localhost" | "::1")
}

/// What one source reported last.
#[derive(Default)]
struct Source {
    rects: Vec<RemoteRect>,
    hidden: HashSet<WindowId>,
}

struct Shared {
    generation: AtomicU64,
    stop: AtomicBool,
    sources: Mutex<HashMap<String, Source>>,
}

/// The connection to the hub, kept up on its own thread.
pub struct Hub {
    shared: Arc<Shared>,
}

impl Hub {
    /// Connects to `url` and keeps reconnecting while the hub is away. `wake` is called whenever the rectangles change.
    /// `None` if the address isn't on this machine.
    pub fn start(url: &str, wake: impl Fn() + Send + 'static) -> Option<Hub> {
        if !is_loopback(url) {
            return None;
        }
        let shared = Arc::new(Shared { generation: AtomicU64::new(0), stop: AtomicBool::new(false), sources: Mutex::new(HashMap::new()) });
        let (url, worker) = (url.to_string(), shared.clone());
        thread::Builder::new().name("hub".into()).spawn(move || run(&url, &worker, &wake)).ok()?;
        Some(Hub { shared })
    }

    /// Goes up whenever the rectangles change, with every message that did and when the hub goes away.
    pub fn generation(&self) -> u64 {
        self.shared.generation.load(Ordering::Acquire)
    }

    /// Whether this id was reported away for now rather than gone: its snow waits instead of falling.
    pub fn is_hidden(&self, id: WindowId) -> bool {
        let sources = self.shared.sources.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        sources.values().any(|source| source.hidden.contains(&id) && !source.rects.iter().any(|rect| rect.id == id))
    }

    /// The rectangles on one display, in its overlay coordinates.
    /// `area` is the display's work area in physical pixels as (left, top, right, bottom), `size` the overlay's size in DIPs.
    pub fn surfaces(&self, area: (i32, i32, i32, i32), size: (u32, u32)) -> Vec<WindowSurface> {
        let sources = self.shared.sources.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut all: Vec<&RemoteRect> = sources.values().flat_map(|source| &source.rects).collect();
        all.sort_by_key(|rect| rect.id);
        all.into_iter().filter_map(|rect| surface(rect, area, size)).collect()
    }
}

impl Drop for Hub {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::Release);
    }
}

/// One rectangle as a surface of the display with this work area, or `None` if the snow couldn't settle on it there.
fn surface(rect: &RemoteRect, (left, top, right, bottom): (i32, i32, i32, i32), (width, height): (u32, u32)) -> Option<WindowSurface> {
    let (width, height) = (width as f32, height as f32);
    let sx = width / (right - left).max(1) as f32;
    let sy = height / (bottom - top).max(1) as f32;
    let frame =
        Rect { x: (rect.x - left as f32) * sx, y: (bottom as f32 - (rect.y + rect.height)) * sy, width: rect.width * sx, height: rect.height * sy };
    let room_above = (rect.y - top as f32) * sy >= 6.0 && frame.max_y() < height;
    let on_screen = frame.max_x() > 0.0 && frame.min_x() < width && frame.max_y() > 0.0;
    if !(room_above && on_screen && frame.width >= MIN_WIDTH && frame.height >= MIN_HEIGHT) {
        return None;
    }
    let radius = (rect.radius * sx).min(frame.width / 2.0).min(frame.height / 2.0);
    Some(WindowSurface { id: rect.id, frame, blockers: Vec::new(), corner_radius: radius, corner_exponent: 2.0 })
}

fn run(url: &str, shared: &Shared, wake: &dyn Fn()) {
    let mut wait = Duration::from_secs(1);
    while !shared.stop.load(Ordering::Acquire) {
        match tungstenite::connect(url) {
            Ok((mut socket, _)) => {
                wait = Duration::from_secs(1);
                if let MaybeTlsStream::Plain(stream) = socket.get_mut() {
                    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
                    let _ = stream.set_nodelay(true);
                }
                let _ = socket.send(Message::text(r#"{"type":"hello","role":"snowhush"}"#));
                listen(&mut socket, shared, wake);
                // The hub is gone, and with it whoever was placing snow.
                let had = {
                    let mut sources = shared.sources.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
                    let had = !sources.is_empty();
                    sources.clear();
                    had
                };
                if had {
                    changed(shared, wake);
                }
            }
            Err(_) => {
                sleep(shared, wait);
                wait = (wait * 2).min(Duration::from_secs(10));
            }
        }
    }
}

fn listen(socket: &mut WebSocket<MaybeTlsStream<TcpStream>>, shared: &Shared, wake: &dyn Fn()) {
    while !shared.stop.load(Ordering::Acquire) {
        match socket.read() {
            Ok(Message::Text(text)) => {
                if text.len() > MAX_MESSAGE {
                    return;
                }
                if let Some(update) = parse(text.as_str()) {
                    {
                        let mut sources = shared.sources.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
                        match update {
                            Update::Surfaces { source, rects, hidden } => {
                                if rects.is_empty() && hidden.is_empty() {
                                    sources.remove(&source);
                                } else {
                                    sources.insert(source, Source { rects, hidden: hidden.into_iter().collect() });
                                }
                            }
                            Update::Clear { source } => {
                                sources.remove(&source);
                            }
                        }
                    }
                    changed(shared, wake);
                }
            }
            Ok(Message::Close(_)) => return,
            Ok(_) => {}
            Err(tungstenite::Error::Io(error)) if matches!(error.kind(), std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut) => {}
            Err(_) => return,
        }
    }
}

fn changed(shared: &Shared, wake: &dyn Fn()) {
    shared.generation.fetch_add(1, Ordering::AcqRel);
    wake();
}

/// Sleeps in short steps, so that stopping doesn't wait for the whole pause.
fn sleep(shared: &Shared, total: Duration) {
    let mut left = total;
    while left > Duration::ZERO && !shared.stop.load(Ordering::Acquire) {
        let step = left.min(Duration::from_millis(200));
        thread::sleep(step);
        left -= step;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::sync::atomic::AtomicUsize;

    const AREA: (i32, i32, i32, i32) = (0, 0, 1920, 1080);
    const SIZE: (u32, u32) = (1920, 1080);

    fn rect(x: f32, y: f32, width: f32, height: f32) -> RemoteRect {
        RemoteRect { id: surface_id("test", "a"), x, y, width, height, radius: 8.0 }
    }

    #[test]
    fn parses_surfaces() {
        let text = r#"{"type":"surfaces","source":"firefox","rects":[{"id":"nav","x":100,"y":200,"w":600,"h":48,"radius":8},{"id":7,"x":0,"y":0,"w":10,"h":10}]}"#;
        let Some(Update::Surfaces { source, rects, hidden }) = parse(text) else { panic!("not parsed") };
        assert!(hidden.is_empty());
        assert_eq!(source, "firefox");
        assert_eq!(rects.len(), 2);
        assert_eq!((rects[0].x, rects[0].y, rects[0].width, rects[0].height, rects[0].radius), (100.0, 200.0, 600.0, 48.0, 8.0));
        assert_eq!(rects[0].id, surface_id("firefox", "nav"));
        assert_eq!(rects[1].id, surface_id("firefox", "7"));
    }

    #[test]
    fn ignores_what_is_not_valid() {
        assert_eq!(parse("nonsense"), None);
        assert_eq!(parse(r#"{"type":"surfaces","rects":[]}"#), None);
        assert_eq!(parse(r#"{"type":"explode","source":"x"}"#), None);
        assert_eq!(parse(r#"{"type":"clear","source":""}"#), None);
        let Some(Update::Surfaces { rects, .. }) = parse(
            r#"{"type":"surfaces","source":"s","rects":[{"id":"a","x":1,"y":1,"w":0,"h":5},{"id":"b","x":"1","y":1,"w":5,"h":5},{"x":1,"y":1,"w":5,"h":5}]}"#,
        ) else {
            panic!("not parsed")
        };
        assert!(rects.is_empty());
        assert_eq!(parse(r#"{"type":"clear","source":"s"}"#), Some(Update::Clear { source: "s".into() }));
    }

    #[test]
    fn caps_the_rectangles_of_one_source() {
        let rects: Vec<String> = (0..MAX_RECTS + 50).map(|n| format!(r#"{{"id":{n},"x":0,"y":0,"w":100,"h":50}}"#)).collect();
        let text = format!(r#"{{"type":"surfaces","source":"s","rects":[{}]}}"#, rects.join(","));
        let Some(Update::Surfaces { rects, .. }) = parse(&text) else { panic!("not parsed") };
        assert_eq!(rects.len(), MAX_RECTS);
    }

    #[test]
    fn ids_are_stable_negative_and_separate_sources() {
        assert_eq!(surface_id("firefox", "a"), surface_id("firefox", "a"));
        assert_ne!(surface_id("firefox", "a"), surface_id("unity", "a"));
        assert_ne!(surface_id("firefox", "a"), surface_id("firefox", "b"));
        assert!(surface_id("firefox", "a") < 0);
    }

    #[test]
    fn only_this_machine_is_a_hub() {
        assert!(is_loopback("ws://127.0.0.1:8765"));
        assert!(is_loopback("ws://localhost:8765/path"));
        assert!(is_loopback("ws://[::1]:8765"));
        assert!(!is_loopback("ws://192.168.1.5:8765"));
        assert!(!is_loopback("ws://127.0.0.1.evil.com:8765"));
        assert!(!is_loopback("wss://127.0.0.1:8765"));
        assert!(!is_loopback("http://127.0.0.1"));
    }

    #[test]
    fn y_points_up_in_the_overlay() {
        // Top edge 200 px below the top of a 1080 px display: 880 above the bottom, in overlay coordinates.
        let surface = surface(&rect(100.0, 200.0, 600.0, 48.0), AREA, SIZE).expect("settles");
        assert_eq!(surface.frame, Rect { x: 100.0, y: 832.0, width: 600.0, height: 48.0 });
        assert_eq!(surface.frame.max_y(), 880.0);
        assert_eq!(surface.corner_radius, 8.0);
    }

    #[test]
    fn follows_the_display_it_is_on() {
        // A second display to the right, at half the DIP size of its physical pixels.
        let area = (1920, 0, 3840, 1080);
        let size = (960, 540);
        assert!(surface(&rect(100.0, 200.0, 600.0, 48.0), area, size).is_none(), "on the other display");
        let surface = surface(&rect(2020.0, 200.0, 600.0, 48.0), area, size).expect("settles");
        assert_eq!(surface.frame, Rect { x: 50.0, y: 416.0, width: 300.0, height: 24.0 });
    }

    #[test]
    fn needs_room_above_and_a_useful_size() {
        assert!(surface(&rect(100.0, 2.0, 600.0, 48.0), AREA, SIZE).is_none(), "touching the top of the display");
        assert!(surface(&rect(100.0, 200.0, 40.0, 48.0), AREA, SIZE).is_none(), "too narrow");
        assert!(surface(&rect(100.0, 200.0, 600.0, 4.0), AREA, SIZE).is_none(), "too thin");
        assert!(surface(&rect(5000.0, 200.0, 600.0, 48.0), AREA, SIZE).is_none(), "off the display");
    }

    #[test]
    fn parses_the_ids_that_are_away() {
        let text = r#"{"type":"surfaces","source":"firefox","rects":[],"hidden":["a",7,{"bad":1},"b"]}"#;
        let Some(Update::Surfaces { rects, hidden, .. }) = parse(text) else { panic!("not parsed") };
        assert!(rects.is_empty());
        assert_eq!(hidden, vec![surface_id("firefox", "a"), surface_id("firefox", "7"), surface_id("firefox", "b")]);
        // Ids away are the same ones that come back in rects.
        let back = r#"{"type":"surfaces","source":"firefox","rects":[{"id":"a","x":0,"y":0,"w":100,"h":50}]}"#;
        let Some(Update::Surfaces { rects, .. }) = parse(back) else { panic!("not parsed") };
        assert_eq!(rects[0].id, hidden[0]);
    }

    #[test]
    fn caps_the_ids_that_are_away() {
        let ids: Vec<String> = (0..MAX_HIDDEN + 50).map(|n| format!(r#""{n}""#)).collect();
        let text = format!(r#"{{"type":"surfaces","source":"s","rects":[],"hidden":[{}]}}"#, ids.join(","));
        let Some(Update::Surfaces { hidden, .. }) = parse(&text) else { panic!("not parsed") };
        assert_eq!(hidden.len(), MAX_HIDDEN);
    }

    #[test]
    fn talks_to_a_hub() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
        let url = format!("ws://{}", listener.local_addr().expect("address"));
        let woken = Arc::new(AtomicUsize::new(0));
        let counter = woken.clone();
        let hub = Hub::start(&url, move || {
            counter.fetch_add(1, Ordering::SeqCst);
        })
        .expect("loopback");

        let (stream, _) = listener.accept().expect("accept");
        let mut server = tungstenite::accept(stream).expect("handshake");
        let hello = server.read().expect("hello");
        assert_eq!(hello.into_text().expect("text").as_str(), r#"{"type":"hello","role":"snowhush"}"#);

        let message = r#"{"type":"surfaces","source":"firefox","rects":[{"id":"nav","x":100,"y":200,"w":600,"h":48}]}"#;
        server.send(Message::text(message)).expect("send");
        wait_for(|| hub.generation() == 1);
        assert_eq!(hub.surfaces(AREA, SIZE).len(), 1);
        assert_eq!(woken.load(Ordering::SeqCst), 1);

        server.send(Message::text(r#"{"type":"clear","source":"firefox"}"#)).expect("send");
        wait_for(|| hub.generation() == 2);
        assert!(hub.surfaces(AREA, SIZE).is_empty());

        // Away for now: nothing to settle on, but the id is known to be coming back.
        let id = surface_id("firefox", "nav");
        server.send(Message::text(message)).expect("send");
        wait_for(|| hub.generation() == 3);
        assert!(!hub.is_hidden(id));
        server.send(Message::text(r#"{"type":"surfaces","source":"firefox","rects":[],"hidden":["nav"]}"#)).expect("send");
        wait_for(|| hub.generation() == 4);
        assert!(hub.surfaces(AREA, SIZE).is_empty());
        assert!(hub.is_hidden(id));
        server.send(Message::text(message)).expect("send");
        wait_for(|| hub.generation() == 5);
        assert_eq!(hub.surfaces(AREA, SIZE).len(), 1);
        assert!(!hub.is_hidden(id), "back on its window");

        // Cleared means gone, even if it was away.
        server.send(Message::text(r#"{"type":"surfaces","source":"firefox","rects":[],"hidden":["nav"]}"#)).expect("send");
        wait_for(|| hub.generation() == 6);
        server.send(Message::text(r#"{"type":"clear","source":"firefox"}"#)).expect("send");
        wait_for(|| hub.generation() == 7);
        assert!(!hub.is_hidden(id));

        // A hub that goes away takes its rectangles with it, and what was away too.
        server.send(Message::text(message)).expect("send");
        wait_for(|| hub.generation() == 8);
        drop(server);
        wait_for(|| hub.generation() == 9);
        assert!(hub.surfaces(AREA, SIZE).is_empty());
    }

    fn wait_for(condition: impl Fn() -> bool) {
        for _ in 0..100 {
            if condition() {
                return;
            }
            thread::sleep(Duration::from_millis(50));
        }
        panic!("timed out");
    }
}
