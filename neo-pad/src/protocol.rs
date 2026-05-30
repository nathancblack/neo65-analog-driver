//! Shared Neo65 HE analog read core (QMK raw HID, usage page 0xFF60).
//!
//! This is the cross-platform half — it uses `hidapi`, so the same code finds
//! the channel and reads depth on Linux now and on Windows in Phase 4. The
//! Python `neo_core.py` is the reference; this mirrors it 1:1.
//!
//! SAFETY (HANDOFF.md): the only opcode issued here is the confirmed-safe READ
//! `d0 a6`. Never add a blind write of an unobserved `d0 XX` opcode.

use hidapi::{HidApi, HidDevice};
use std::collections::HashMap;
use std::time::{Duration, Instant};

pub const VID: u16 = 0xE560; // NEO Neo65 HE, wired
pub const PID: u16 = 0xEE65;
pub const USAGE_PAGE: u16 = 0xFF60; // QMK raw HID interface

pub const REST: f32 = 0x012c as f32; // 300, rest depth
pub const FULL: f32 = 0x80e8 as f32; // 33000, bottom-out

/// (name, key index) — confirmed 2026-05-30 via probe.py keymap.
pub const KEYS: [(&str, u8); 4] = [("W", 18), ("A", 33), ("S", 34), ("D", 35)];

/// Full 6-page layout (start, count); we poll only pages carrying a wanted key.
pub const PAGES: [(u8, u8); 6] = [
    (0x00, 0x0e),
    (0x0e, 0x0e),
    (0x1c, 0x0e),
    (0x2a, 0x0e),
    (0x38, 0x0e),
    (0x46, 0x0a),
];

/// Raw firmware depth -> 0.0 (rest) .. 1.0 (bottom-out).
pub fn norm(v: u16) -> f32 {
    (((v as f32) - REST) / (FULL - REST)).clamp(0.0, 1.0)
}

/// Open the analog channel: VID:PID match whose interface reports usage page 0xFF60.
pub fn find_device(api: &HidApi) -> Option<HidDevice> {
    let info = api
        .device_list()
        .find(|d| d.vendor_id() == VID && d.product_id() == PID && d.usage_page() == USAGE_PAGE)?;
    info.open_device(api).ok()
}

fn pages_for(indices: &[u8]) -> Vec<(u8, u8)> {
    PAGES
        .iter()
        .copied()
        .filter(|&(s, c)| indices.iter().any(|&i| s <= i && i < s + c))
        .collect()
}

fn drain(dev: &HidDevice) {
    let mut tmp = [0u8; 64];
    while let Ok(n) = dev.read_timeout(&mut tmp, 0) {
        if n == 0 {
            break;
        }
    }
}

/// Send `d0 a6 <start> <cnt>`; return the reply matching THIS page (all echo a6).
fn read_page(dev: &HidDevice, start: u8, cnt: u8) -> Option<[u8; 64]> {
    drain(dev);
    // hidapi write: leading byte is the report id (0x00 = unnumbered), then 32 payload.
    let mut out = [0u8; 33];
    out[1] = 0xd0;
    out[2] = 0xa6;
    out[3] = start;
    out[4] = cnt;
    dev.write(&out).ok()?;
    let deadline = Instant::now() + Duration::from_millis(200);
    while Instant::now() < deadline {
        let mut buf = [0u8; 64];
        match dev.read_timeout(&mut buf, 200) {
            Ok(n)
                if n >= 4
                    && buf[0] == 0xd0
                    && buf[1] == 0xa6
                    && buf[2] == start
                    && buf[3] == cnt =>
            {
                return Some(buf)
            }
            Ok(_) => continue, // some other page's reply; keep waiting
            Err(_) => return None,
        }
    }
    None
}

/// Poll the minimal page set and update `depth` with {name: raw}. Keys whose page
/// didn't reply this frame keep their previous value (caller's map is reused).
pub fn read_depths(dev: &HidDevice, depth: &mut HashMap<&'static str, u16>) {
    let idx: Vec<u8> = KEYS.iter().map(|&(_, i)| i).collect();
    for (start, cnt) in pages_for(&idx) {
        if let Some(rep) = read_page(dev, start, cnt) {
            for &(name, i) in KEYS.iter() {
                if start <= i && i < start + cnt {
                    let j = (i - start) as usize;
                    let v = ((rep[4 + 2 * j] as u16) << 8) | rep[4 + 2 * j + 1] as u16;
                    depth.insert(name, v);
                }
            }
        }
    }
}
