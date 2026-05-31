//! State shared between the device poll loop and the (Windows) tuning GUI.
//!
//! The poll loop reads `Tunables` each frame and writes the latest `Live`
//! readout; the GUI does the opposite. A single `Mutex` guards both — the
//! critical sections are tiny (a struct copy), so contention is negligible
//! even at a few hundred Hz.

/// Knobs the user can turn live. Plain `Copy` so we can snapshot under a short
/// lock and release before doing any real work / drawing.
#[derive(Clone, Copy, PartialEq)]
#[cfg_attr(windows, derive(serde::Serialize, serde::Deserialize))]
pub struct Tunables {
    pub deadzone: f32,
    pub expo: f32,
    pub rate: f32,
    pub invert_x: bool,
    pub invert_y: bool,
    pub enabled: bool,
}

impl Default for Tunables {
    fn default() -> Self {
        // Mirrors the old CLI defaults.
        Self {
            deadzone: 0.05,
            expo: 0.0,
            rate: 200.0,
            invert_x: false,
            invert_y: false,
            enabled: true,
        }
    }
}

/// Latest computed values, for the GUI's live readout / stick visualizer.
#[derive(Clone, Copy, Default)]
pub struct Live {
    pub w: f32,
    pub a: f32,
    pub s: f32,
    pub d: f32,
    pub x: f32,
    pub y: f32,
}

#[derive(Default)]
pub struct Shared {
    pub tun: Tunables,
    pub live: Live,
}
