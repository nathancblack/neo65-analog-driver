# neo-pad

Turns a QwertyKeys Neo65 Sonic HE+ Hall-effect keyboard into an analog input
device. Reads per-key press *depth* over USB HID and drives a virtual gamepad
left stick, so W/A/S/D give proportional walk-to-run movement in games.

Reads depth from the board's QMK raw-HID interface (VID:PID `E560:EE65`, usage
page `0xFF60`), maps it to a stick, and outputs through a virtual Xbox 360 pad
(ViGEm on Windows, uinput on Linux). The read/mapping core is shared; only the
output backend is platform-specific.

```
X = D - A    Y = S - W    (opposing keys cancel)
```

## Requirements

- Neo65 Sonic HE+, connected wired
- Rust (stable, MSVC toolchain on Windows)
- Windows: ViGEmBus driver 1.22.0 installed
- Linux: write access to `/dev/uinput`

## Build

```
cargo build --release --manifest-path neo-pad/Cargo.toml
```

## Run

```
neo-pad --gui        live tuning window (Windows): deadzone, expo, poll rate,
                     invert, depth bars, stick visualizer; settings persist
neo-pad              headless, runs until Ctrl-C
neo-pad --monitor    headless, print live axis values
neo-pad --selftest   sweep the stick with no keyboard (verify the pad)
```

Flags: `--deadzone <0..0.4>`, `--expo <0..1>`, `--rate <hz>`.

## Status

Works: forward walk-to-run is smooth and proportional; turning and diagonals
track depth. Per-game feel varies because the board still sends normal W/A/S/D
keystrokes alongside the stick, and most games merge the two. If movement
saturates, unbind keyboard W/A/S/D in the game and bind movement to the stick,
or raise the actuation point in NeoFlux.

See `HANDOFF.md` for protocol details and `PROTOCOL.md` for the byte-level HID
decode.
