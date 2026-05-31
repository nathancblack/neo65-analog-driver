//! Live tuning GUI (Windows). egui/eframe window that reads + writes the shared
//! `Tunables` while the device poll loop runs on a background thread, so every
//! slider change takes effect on the very next poll frame.
//!
//! Settings persist via eframe storage (the `persistence` feature), so your
//! per-game tuning survives a restart.

use crate::shared::{Shared, Tunables};
use eframe::egui;
use std::sync::{Arc, Mutex};

const STORE_KEY: &str = "neo_pad_tunables";

pub fn run(shared: Arc<Mutex<Shared>>) -> std::io::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([340.0, 470.0])
            .with_min_inner_size([300.0, 420.0])
            .with_title("Neo65 Analog Pad — Tuning"),
        ..Default::default()
    };
    eframe::run_native(
        "neo-pad",
        options,
        Box::new(|cc| Ok(Box::new(TuneApp::new(cc, shared)))),
    )
    .map_err(|e| std::io::Error::other(e.to_string()))
}

struct TuneApp {
    shared: Arc<Mutex<Shared>>,
}

impl TuneApp {
    fn new(cc: &eframe::CreationContext<'_>, shared: Arc<Mutex<Shared>>) -> Self {
        // Restore saved tunables (if any) and push them into the shared state so
        // the poll loop picks them up immediately.
        if let Some(storage) = cc.storage {
            if let Some(t) = eframe::get_value::<Tunables>(storage, STORE_KEY) {
                shared.lock().unwrap().tun = t;
            }
        }
        Self { shared }
    }
}

impl eframe::App for TuneApp {
    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        let tun = self.shared.lock().unwrap().tun;
        eframe::set_value(storage, STORE_KEY, &tun);
    }

    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        // Snapshot under a short lock; edit/draw on the copies; write back once.
        let (mut tun, live) = {
            let s = self.shared.lock().unwrap();
            (s.tun, s.live)
        };

        ui.heading("Neo65 Analog Pad");
        ui.add_space(4.0);

        ui.checkbox(&mut tun.enabled, "Enabled (sending to game)");
        ui.add_space(6.0);

        ui.add(egui::Slider::new(&mut tun.deadzone, 0.0..=0.40).text("Deadzone"));
        ui.add(egui::Slider::new(&mut tun.expo, 0.0..=1.0).text("Expo (finer slow end)"));
        ui.add(egui::Slider::new(&mut tun.rate, 30.0..=500.0).text("Poll rate (Hz)"));
        ui.horizontal(|ui| {
            ui.checkbox(&mut tun.invert_x, "Invert X");
            ui.checkbox(&mut tun.invert_y, "Invert Y");
        });

        ui.add_space(8.0);
        ui.separator();
        ui.label("Key depth");
        ui.add(egui::ProgressBar::new(live.w).text(format!("W {:.2}", live.w)));
        ui.add(egui::ProgressBar::new(live.s).text(format!("S {:.2}", live.s)));
        ui.add(egui::ProgressBar::new(live.a).text(format!("A {:.2}", live.a)));
        ui.add(egui::ProgressBar::new(live.d).text(format!("D {:.2}", live.d)));

        ui.add_space(8.0);
        ui.label(format!("Left stick    X {:+.2}    Y {:+.2}", live.x, live.y));
        stick_view(ui, live.x, live.y);

        ui.add_space(8.0);
        if ui.button("Reset to defaults").clicked() {
            tun = Tunables::default();
        }

        // Apply any edits back to the shared state for the poll loop.
        {
            let mut s = self.shared.lock().unwrap();
            s.tun = tun;
        }

        // Readouts/visualizer need continuous refresh even without input events.
        ui.ctx().request_repaint();
    }
}

/// Small top-down stick visualizer: a box with a crosshair and a dot. Forward
/// (W) shows up; right (D) shows right — matching how the value reaches the game.
fn stick_view(ui: &mut egui::Ui, x: f32, y: f32) {
    let (resp, painter) = ui.allocate_painter(egui::vec2(150.0, 150.0), egui::Sense::hover());
    let rect = resp.rect;
    painter.rect_filled(rect, egui::CornerRadius::same(4), egui::Color32::from_gray(28));
    let c = rect.center();
    let stroke = egui::Stroke::new(1.0, egui::Color32::from_gray(70));
    painter.line_segment([egui::pos2(rect.left(), c.y), egui::pos2(rect.right(), c.y)], stroke);
    painter.line_segment([egui::pos2(c.x, rect.top()), egui::pos2(c.x, rect.bottom())], stroke);
    let half = rect.width() * 0.5 - 6.0;
    // y is screen-down-positive (s - w), so forward (W, y<0) sits above center.
    let px = c.x + x.clamp(-1.0, 1.0) * half;
    let py = c.y + y.clamp(-1.0, 1.0) * half;
    painter.circle_filled(egui::pos2(px, py), 6.0, egui::Color32::from_rgb(90, 170, 255));
}
