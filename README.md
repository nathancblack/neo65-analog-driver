# neo-pad

**Turn a Hall-effect keyboard into an analog gamepad.** `neo-pad` reads how *far*
you press W/A/S/D on a QwertyKeys Neo65 Sonic HE+ keyboard and feeds that depth
into a virtual gamepad's left stick — so a light press walks and a hard press runs,
with everything in between.

## The hook

Most keyboards are digital: a key is either down or up. The Neo65 is Hall-effect,
so its firmware actually knows the *analog travel* of every key. This tool pulls
that per-key depth off the board in real time over its QMK raw-HID channel and maps
the four movement keys onto a stick:

```
X = depth(D) - depth(A)      (right positive)
Y = depth(S) - depth(W)      (down positive, screen convention)
```

Opposing keys cancel (press A and D together and you stay centered — subtractive
SOCD). The result is a virtual Xbox-style gamepad that any game or gamepad tester
can pick up, driven entirely by how hard you lean on WASD.

## Status — what actually works today

- **Reading analog depth off the board:** working and verified live. The driver
  finds the board's raw-HID channel, polls the per-key depth map, and tracks W/A/S/D
  independently and proportionally.
- **Virtual gamepad on Linux (uinput) and Windows (ViGEm):** both working and
  verified on hardware. The driver creates an Xbox-style pad and drives its left
  stick from key depth; on Linux it's a 6-axis pad named *"Neo65 HE Analog Pad"*,
  on Windows (11) it's a wired Xbox 360 pad read back through XInput. End-to-end
  confirmed on both: the values the OS reports back match what the driver emits.
- **Live tuning GUI (`--gui`, Windows):** an egui window with deadzone / expo /
  poll-rate / invert sliders, live W/A/S/D depth bars, and a stick visualizer;
  settings persist across runs. The HID poll loop runs on a background thread and
  GUI edits apply on the next frame.
- **Forward walk-to-run, turning, and diagonals:** smooth and proportional at the
  driver level — partial presses produce partial stick travel, and the axes move
  independently.

**Honest caveat — per-game feel varies.** The keyboard still sends its normal digital
W/A/S/D keystrokes *alongside* the analog stick. Many games either ignore the stick
once they see a keypress, or treat a key as fully "down" the instant it actuates,
which collapses the analog range. Getting satisfying proportional movement in a real
game usually means **unbinding keyboard movement and binding the controller stick**
(biggest lever, no code), and/or **raising the actuation point near bottom-out** on
the board so the digital keystroke only fires at the very end of travel. The pad and
the depth signal are solid; making a specific game *use* them analog is per-game
tuning, not a guaranteed flip-the-switch result.

**Platform support:** both backends ship and are verified — **Linux (uinput)** and
**Windows (ViGEm)**. The HID read core and mapping logic are shared cross-platform;
only the output backend differs per OS (selected at compile time). The `--gui` live
tuning window is Windows-only; Linux runs headless with CLI tuning flags.

## Requirements

- A **QwertyKeys Neo65 Sonic HE+** keyboard, **wired** (USB VID:PID `E560:EE65`,
  raw-HID usage page `0xFF60`).
- A **Rust toolchain** (stable, edition 2021). Install via [rustup](https://rustup.rs/).
- **Linux:** write access to `/dev/uinput`. Run as root, or give your user access via
  a udev rule / ACL (here the `input` group already has it). `hidapi` also needs read
  access to the board's hidraw node.
- **Windows:** the [ViGEmBus](https://github.com/nefarius/ViGEmBus) driver installed
  (provides the virtual Xbox 360 pad). `--gui` opens the live tuning window.

## Build & run

```sh
# build the release binary
cargo build --release --manifest-path neo-pad/Cargo.toml

# run it: creates the virtual pad and drives the stick from WASD depth
cargo run --release --manifest-path neo-pad/Cargo.toml

# ...or run the built binary directly
./neo-pad/target/release/neo-pad
```

### Run modes & flags

| Flag | Effect |
|------|--------|
| *(none)* | Create the pad and run until Ctrl-C. |
| `--gui` | **(Windows)** Open the live tuning window — deadzone/expo/rate/invert sliders, depth bars, stick visualizer; settings persist. |
| `--monitor` | Also print live axis + per-key depth values to the terminal. |
| `--selftest` | Sweep the stick in a circle with **no keyboard** — verify the pad itself (watch it with `tools/jsmon.py`). |
| `--deadzone D` | Rest deadzone, fraction of travel ignored near rest (default `0.05`). |
| `--expo E` | Expo curve, `0` = linear (default), higher = softer center. |
| `--rate HZ` | Target poll rate in Hz (default `200`). |

Tuning is done with these flags — adjust `--deadzone` and `--expo` to taste and
re-run. To confirm the pad works without touching a game, run `--selftest` in one
terminal and `python tools/jsmon.py` in another to watch the kernel see the swept
stick.

## How it works

1. **Find the channel.** Match the board by VID:PID *and* raw-HID usage page, so it
   survives hidraw renumbering across replugs.
2. **Read depth.** Issue the firmware's read opcode (`d0 a6 <start> <count>`) to pull
   a paginated per-key depth array; only the 2 pages carrying W/A/S/D are polled.
   Each raw depth is normalized from rest (`0x012c`) to bottom-out (`0x80e8`) into
   `0.0..1.0`.
3. **Shape & map.** Apply deadzone + optional expo, then compute `X = D - A`,
   `Y = S - W`.
4. **Output.** Push the stick values to the virtual pad behind a shared `Pad` trait
   (Linux: a hand-rolled uinput device; Windows: a ViGEm Xbox 360 pad). With `--gui`,
   the poll loop runs on a background thread and shares tunables/readout with the GUI
   behind a `Mutex`, so slider edits apply on the next frame.

The byte-level HID decode — interface map, opcode reverse-engineering, the per-key
index map, calibration constants — lives in **[`PROTOCOL.md`](PROTOCOL.md)**.

## Repository structure

```
neo-pad/                 Rust driver — the shipped core
  src/main.rs            CLI, arg parsing, read→shape→map loop, selftest
  src/protocol.rs        Shared read core: find channel, d0 a6 paging, normalize (hidapi)
  src/pad.rs             Virtual-pad output behind a Pad trait (Linux uinput / Windows ViGEm)
  src/shared.rs          Tunables + live readout shared between the loop and the GUI
  src/gui.rs             egui/eframe live tuning window (Windows)
  Cargo.toml

tools/                   Python/JS prototyping & validation utilities
  neo_core.py            Reference read core the Rust port mirrors 1:1
  reader.py              Live WASD depth bars in the terminal (no GUI/browser)
  gamepad.py            Phase-3 pure-Python uinput pad (the Rust driver's predecessor)
  jsmon.py               Reads back what the *kernel* sees on the pad — independent check
  probe.py               HID opcode/keymap probing used to reverse-engineer the protocol
  cap.py                 Raw hidraw capture logger
  sniff2.js              NeoFlux traffic sniffer used to discover the depth opcode

PROTOCOL.md              Byte-level HID protocol record (read this for the deep detail)
HANDOFF.md               Working notes: phases, verification steps, per-game mitigations
```

The driver you run is the **Rust** crate in `neo-pad/`. The `tools/` directory is
**Python** (plus one JS sniffer) — these were used to reverse-engineer and validate
the HID protocol and to build the original proof-of-concept; the Rust core was ported
from them and is what's maintained now.

## Limitations & notes

- **Wired only.** The analog channel and IDs above are for the wired connection.
- **In-game results depend on the game**, not just this tool — see the per-game WASD
  overlap caveat under Status.
- **Safety:** the driver only ever issues the confirmed-safe *read* opcode. It never
  blindly writes unverified config opcodes to the board.
