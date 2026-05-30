//! Neo65 HE analog key depth -> virtual gamepad left stick (Rust port of the
//! Phase 3 Python PoC; the read core uses hidapi so it carries over to Windows
//! in Phase 4, where only the Pad backend changes).
//!
//!   X = shape(D) - shape(A)   (right positive)
//!   Y = shape(S) - shape(W)   (down positive, screen convention)
//!
//! Opposing keys cancel (subtractive SOCD). Needs write access to /dev/uinput
//! (root, or a group/ACL on the node — the `input` group has it here).
//!
//! Usage:
//!   neo-pad                 run until Ctrl-C
//!   neo-pad --monitor       also print live axis values
//!   neo-pad --expo 0.4      mild expo (0 = linear, default)
//!   neo-pad --deadzone 0.06
//!   neo-pad --rate 200      target poll rate (Hz)
//!   neo-pad --selftest      sweep the stick with NO keyboard (verify the pad via jsmon.py)

mod pad;
mod protocol;

use hidapi::HidApi;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

static RUNNING: AtomicBool = AtomicBool::new(true);

extern "C" fn on_sigint(_: i32) {
    RUNNING.store(false, Ordering::SeqCst);
}

struct Args {
    deadzone: f32,
    expo: f32,
    rate: f32,
    monitor: bool,
    selftest: bool,
}

fn parse_args() -> Args {
    let mut a = Args {
        deadzone: 0.05,
        expo: 0.0,
        rate: 200.0,
        monitor: false,
        selftest: false,
    };
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--monitor" => a.monitor = true,
            "--selftest" => a.selftest = true,
            "--deadzone" => {
                a.deadzone = it.next().and_then(|v| v.parse().ok()).unwrap_or(a.deadzone)
            }
            "--expo" => a.expo = it.next().and_then(|v| v.parse().ok()).unwrap_or(a.expo),
            "--rate" => a.rate = it.next().and_then(|v| v.parse().ok()).unwrap_or(a.rate),
            "-h" | "--help" => {
                eprintln!("neo-pad [--monitor] [--selftest] [--deadzone D] [--expo E] [--rate HZ]");
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
    // SAFETY: registering a trivial async-signal-safe handler that only sets a flag.
    unsafe {
        libc::signal(libc::SIGINT, on_sigint as *const () as libc::sighandler_t);
    }
}

fn run_selftest(args: &Args) -> std::io::Result<()> {
    let mut pad = pad::new_pad()?;
    println!("# selftest: sweeping left stick for ~6s (no keyboard).");
    println!("# verify with: python tools/jsmon.py");
    let t0 = Instant::now();
    while RUNNING.load(Ordering::SeqCst) && t0.elapsed() < Duration::from_secs(6) {
        let a = t0.elapsed().as_secs_f32();
        pad.set_left_stick((a * 2.0).sin(), (a * 2.0).cos());
        std::thread::sleep(Duration::from_millis(10));
    }
    let _ = args;
    Ok(())
}

fn main() -> std::io::Result<()> {
    let args = parse_args();
    install_sigint();

    if args.selftest {
        return run_selftest(&args);
    }

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
    println!(
        "# deadzone={} expo={} rate={:.0}Hz",
        args.deadzone, args.expo, args.rate
    );
    println!("# press W/A/S/D; Ctrl-C to stop.");

    let mut depth: HashMap<&'static str, u16> =
        protocol::KEYS.iter().map(|&(n, _)| (n, 0u16)).collect();
    let period = Duration::from_secs_f32(1.0 / args.rate.max(1.0));

    while RUNNING.load(Ordering::SeqCst) {
        let frame = Instant::now();
        protocol::read_depths(&dev, &mut depth);
        let g = |k: &str| shape(protocol::norm(depth[k]), args.deadzone, args.expo);
        let (w, a, s, d) = (g("W"), g("A"), g("S"), g("D"));
        let x = (d - a).clamp(-1.0, 1.0);
        let y = (s - w).clamp(-1.0, 1.0);
        pad.set_left_stick(x, y);
        if args.monitor {
            print!("\rX:{x:+5.2}  Y:{y:+5.2}   W:{w:.2} A:{a:.2} S:{s:.2} D:{d:.2}   ");
            use std::io::Write;
            let _ = std::io::stdout().flush();
        }
        if let Some(rem) = period.checked_sub(frame.elapsed()) {
            std::thread::sleep(rem);
        }
    }
    println!();
    Ok(()) // pad drops here -> recenters + destroys the uinput device
}
