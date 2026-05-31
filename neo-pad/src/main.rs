//! Neo65 HE analog key depth -> virtual gamepad left stick.
//!
//!   X = shape(D) - shape(A)   (right positive)
//!   Y = shape(S) - shape(W)   (down positive, screen convention)
//!
//! Opposing keys cancel (subtractive SOCD). The read core uses hidapi and is
//! cross-platform; only the Pad backend differs per OS (Linux uinput / Windows
//! ViGEm). On Windows, `--gui` opens a live tuning window.
//!
//! Usage:
//!   neo-pad                 run until Ctrl-C (headless)
//!   neo-pad --gui           live tuning GUI (Windows)
//!   neo-pad --monitor       headless, also print live axis values
//!   neo-pad --expo 0.4      mild expo (0 = linear, default)
//!   neo-pad --deadzone 0.06
//!   neo-pad --rate 200      target poll rate (Hz)
//!   neo-pad --selftest      sweep the stick with NO keyboard (verify the pad)

mod pad;
mod protocol;
mod shared;
#[cfg(windows)]
mod gui;

use hidapi::HidApi;
use shared::{Live, Shared};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

static RUNNING: AtomicBool = AtomicBool::new(true);

struct Args {
    deadzone: f32,
    expo: f32,
    rate: f32,
    monitor: bool,
    selftest: bool,
    gui: bool,
}

fn parse_args() -> Args {
    let mut a = Args {
        deadzone: 0.05,
        expo: 0.0,
        rate: 200.0,
        monitor: false,
        selftest: false,
        gui: false,
    };
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--monitor" => a.monitor = true,
            "--selftest" => a.selftest = true,
            "--gui" => a.gui = true,
            "--deadzone" => {
                a.deadzone = it.next().and_then(|v| v.parse().ok()).unwrap_or(a.deadzone)
            }
            "--expo" => a.expo = it.next().and_then(|v| v.parse().ok()).unwrap_or(a.expo),
            "--rate" => a.rate = it.next().and_then(|v| v.parse().ok()).unwrap_or(a.rate),
            "-h" | "--help" => {
                eprintln!("neo-pad [--gui] [--monitor] [--selftest] [--deadzone D] [--expo E] [--rate HZ]");
                std::process::exit(0);
            }
            other => eprintln!("# ignoring unknown arg: {other}"),
        }
    }
    a
}

/// Normalized depth (0..1) -> shaped magnitude (0..1) with rest deadzone + expo.
fn shape(v: f32, deadzone: f32, expo: f32) -> f32 {
    if v <= deadzone {
        return 0.0;
    }
    let v = (v - deadzone) / (1.0 - deadzone);
    if expo > 0.0 {
        (1.0 - expo) * v + expo * v.powi(3)
    } else {
        v
    }
}

fn install_sigint() {
    // Cross-platform: ctrlc handles SIGINT on Unix and the console CTRL_C event on
    // Windows. The closure only flips a flag, so the poll loop exits cleanly and the
    // pad recenters + tears down on drop.
    let _ = ctrlc::set_handler(|| RUNNING.store(false, Ordering::SeqCst));
}

fn run_selftest() -> std::io::Result<()> {
    let mut pad = pad::new_pad()?;
    println!("# selftest: sweeping left stick for ~6s (no keyboard).");
    let t0 = Instant::now();
    while RUNNING.load(Ordering::SeqCst) && t0.elapsed() < Duration::from_secs(6) {
        let a = t0.elapsed().as_secs_f32();
        pad.set_left_stick((a * 2.0).sin(), (a * 2.0).cos());
        std::thread::sleep(Duration::from_millis(10));
    }
    Ok(())
}

/// Open the board + pad and poll forever, reading tunables from `shared` each
/// frame and writing back the live readout. `monitor` prints axis values (only
/// used in the headless path; the GUI shows its own readout).
fn run_loop(shared: Arc<Mutex<Shared>>, monitor: bool) -> std::io::Result<()> {
    let api = HidApi::new().map_err(|e| std::io::Error::other(e.to_string()))?;
    let dev = match protocol::find_device(&api) {
        Some(d) => d,
        None => {
            eprintln!("ERROR: no Neo65 HE raw-HID channel (VID:PID {:04x}:{:04x}, usage page {:04x}). Board plugged in (wired)?",
                protocol::VID, protocol::PID, protocol::USAGE_PAGE);
            std::process::exit(1);
        }
    };
    dev.set_blocking_mode(false).ok();

    let mut pad = pad::new_pad()?;
    println!("# virtual pad created: 'Neo65 HE Analog Pad' (left stick = WASD depth)");
    println!("# press W/A/S/D; Ctrl-C to stop.");

    let mut depth: HashMap<&'static str, u16> =
        protocol::KEYS.iter().map(|&(n, _)| (n, 0u16)).collect();

    while RUNNING.load(Ordering::SeqCst) {
        let frame = Instant::now();
        let tun = { shared.lock().unwrap().tun };

        protocol::read_depths(&dev, &mut depth);
        let g = |k: &str| shape(protocol::norm(depth[k]), tun.deadzone, tun.expo);
        let (w, a, s, d) = (g("W"), g("A"), g("S"), g("D"));
        let mut x = (d - a).clamp(-1.0, 1.0);
        let mut y = (s - w).clamp(-1.0, 1.0);
        if tun.invert_x {
            x = -x;
        }
        if tun.invert_y {
            y = -y;
        }

        if tun.enabled {
            pad.set_left_stick(x, y);
        } else {
            pad.set_left_stick(0.0, 0.0);
        }

        {
            let mut sh = shared.lock().unwrap();
            sh.live = Live { w, a, s, d, x, y };
        }

        if monitor {
            print!("\rX:{x:+5.2}  Y:{y:+5.2}   W:{w:.2} A:{a:.2} S:{s:.2} D:{d:.2}   ");
            use std::io::Write;
            let _ = std::io::stdout().flush();
        }

        let period = Duration::from_secs_f32(1.0 / tun.rate.max(1.0));
        if let Some(rem) = period.checked_sub(frame.elapsed()) {
            std::thread::sleep(rem);
        }
    }
    println!();
    Ok(()) // pad drops here -> recenters + tears down
}

fn main() -> std::io::Result<()> {
    let args = parse_args();
    install_sigint();

    if args.selftest {
        return run_selftest();
    }

    // Seed shared state from CLI args; the GUI may overwrite from saved settings.
    let shared = Arc::new(Mutex::new(Shared::default()));
    {
        let mut sh = shared.lock().unwrap();
        sh.tun.deadzone = args.deadzone;
        sh.tun.expo = args.expo;
        sh.tun.rate = args.rate;
    }

    #[cfg(windows)]
    if args.gui {
        // Poll loop on a background thread; egui owns the main thread.
        let loop_shared = Arc::clone(&shared);
        let handle = std::thread::spawn(move || {
            if let Err(e) = run_loop(loop_shared, false) {
                eprintln!("driver loop error: {e}");
                RUNNING.store(false, Ordering::SeqCst);
            }
        });
        let res = gui::run(Arc::clone(&shared));
        RUNNING.store(false, Ordering::SeqCst); // window closed -> stop the loop
        let _ = handle.join();
        return res;
    }

    run_loop(shared, args.monitor)
}
