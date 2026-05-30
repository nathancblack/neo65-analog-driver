# Neo65 Analog Driver — Session Handoff

**Start here.** This is the fast on-ramp for a fresh context window. Read this
top to bottom, then skim `PROTOCOL.md` for byte-level detail. The big static
brief is `neo65-analog-driver-PROJECT.md` (rationale + architecture; not status).

> **🪟 NEW CONTEXT, READ THIS FIRST:** Phases 0–3 are done and the Rust core is
> ported + Linux-verified. **The only work left is the Windows ViGEm output
> backend (Phase 4).** This new session is expected to run **on the Windows
> gaming PC** (that's why we're here — to test in a real game). Jump to
> [**NEXT: Phase 4**](#next-phase-4--windows-vigem-backend); it has the exact
> code to add, the deps, and how to test. The Linux verify commands elsewhere in
> this doc are reference/regression only — you won't run uinput on Windows.

Owner: Nathan (Arch Linux / Hyprland / Neovim daily driver; games on Windows).

---

## Goal (one line)
Turn the QwertyKeys **Neo65 Sonic HE+** Hall-effect keyboard into an analog input
device: key-press *depth* drives a virtual **gamepad stick axis** (walk→run), the
way a Wooting board does natively.

## Status — 2026-05-30
| Phase | What | State |
|---|---|---|
| 0 | Recon / go-no-go gate | ✅ **PASSED** — board streams plaintext on-demand per-key depth |
| 1 | Decode the HID protocol | ✅ **DONE** — `d0 a6` per-key map fully decoded |
| 2 | Linux reader | ✅ **DONE + VERIFIED LIVE** — `tools/reader.py` reads independent W/A/S/D |
| 3 | Linux virtual gamepad (uinput) | ✅ **DONE + VERIFIED LIVE** — `tools/gamepad.py` |
| 4 | Windows port (ViGEm) | 🚧 **IN PROGRESS** — Rust core ported + Linux-verified (`neo-pad/`); ViGEm shim is the remaining bit |
| 5 | Per-game tuning | not started |

**Phase 3 result:** `tools/gamepad.py` presents a pure-Python uinput Xbox-style
pad (no third-party deps — this box has no pip and Python 3.14) whose **left stick
follows W/A/S/D depth**. Verified that the virtual device enumerates as a 6-axis
gamepad and that emitted axis values read back exactly through the kernel event
node (cross-process, via `tools/jsmon.py`). **Not yet done:** a human pressing the
physical keys and watching the stick — see "Verify" below. Mapping:
`X = shape(D) − shape(A)`, `Y = shape(S) − shape(W)`, with rest deadzone + optional
expo; opposing keys cancel (subtractive SOCD). **Confirmed working live by the owner.**

**Phase 4 progress (Rust):** the verified Python logic is ported to a Rust crate
in `neo-pad/`, structured so Windows is a drop-in: the read core (`protocol.rs`)
uses the cross-platform **`hidapi`** crate (filters VID:PID + usage page 0xFF60),
and output sits behind a `Pad` trait (`pad.rs`). The Linux backend is a hand-rolled
uinput device (same ioctl struct layout as `gamepad.py`). **Verified on Linux:**
builds clean; `--selftest` sweep reads back through the kernel via `jsmon.py`; the
hidapi read path was confirmed live against the board (sentinel test). **Remaining
for Phase 4:** add a `#[cfg(windows)]` `vigem-client` backend returning from
`new_pad()` — nothing else changes — then build/test on Windows (needs the hardware).

The earlier "fatal aggregate-only" scare (the `d0 ad` opcode returns only the
single deepest key) was **resolved**: a different opcode, `d0 a6`, is a true
per-key array. Escape hatches (custom firmware / Wooting plugin) were NOT needed.

## The 6 facts you need to resume

1. **Channel.** USB VID:PID `0xE560:0xEE65`. Config/analog lives on the **QMK raw-HID
   interface, usage page `0xFF60`** (currently `/dev/hidraw5`, but **hidraw numbers
   shift on replug** — discover by usage page, not the literal node). `reader.py`
   already does this discovery; reuse `find_channel()`.
2. **Transport.** 32-byte UNNUMBERED reports, strict request/response (board sends
   nothing unsolicited). Linux hidraw: `write()` 33 bytes = `[0x00] + 32 payload`;
   reads return the 32 payload bytes.
3. **Per-key depth opcode `d0 a6 <startIndex> <count>`.** Reply echoes that header
   in bytes [0..3], then `count` **16-bit BIG-ENDIAN** depth values from byte 4.
   Full map = 6 pages over 80 slots; **WASD needs only 2 pages** (`d0 a6 0e 0e`
   and `d0 a6 1c 0e`).
4. **WASD → index:** **W=18, A=33, S=34, D=35** (confirmed via `probe.py keymap`).
5. **Calibration:** depth rest ≈ `0x012c` (300), bottom-out = `0x80e8` (33000).
   Normalize: `clamp((v-0x012c)/(0x80e8-0x012c), 0, 1)`. Refine per-key if needed.
6. **⚠️ SAFETY RULE (hard-won):** **never issue an opcode we haven't first observed
   NeoFlux send.** Blind-writing unknown `d0 XX` opcodes once corrupted live key
   config (recovered by replug — it was volatile RAM, not EEPROM). `d0 ad`, `d0 b0`,
   `d0 a6` are confirmed-safe reads. `probe.py`'s `opcodescan`/`watch`/`chunk` are
   unsafe-by-default — leave them unused. Reading `d0 a6` is safe and is all the
   reader/driver (Python or Rust) needs.

## What's built (`tools/`)
- **`neo_core.py`** ⭐ — the reusable core (extracted from reader.py in Phase 3):
  `find_channel()`/`open_channel()`, the paginated `d0 a6` read (`read_page`,
  `read_depths`), `norm()`, and the WASD index/calibration constants. Both
  `reader.py` and `gamepad.py` import it. Only issues the safe `d0 a6` read.
- **`gamepad.py`** ⭐ — Phase 3 driver. `python tools/gamepad.py [--monitor] [--expo E]
  [--deadzone D] [--rate HZ]`. Pure-Python uinput pad; left stick = WASD depth.
- **`jsmon.py`** — OS-level axis monitor (no evtest/jstest on this box). Finds the
  virtual pad by name and prints live kernel ABS_X/Y. **Match "Analog Pad", NOT
  "Neo65"** — the physical keyboard exposes several "NEO Neo65 HE …" nodes that
  carry no axes.
- **`reader.py`** — Phase 2 reader. `python tools/reader.py [secs]`. Live normalized
  WASD bars. Now a thin CLI over `neo_core.py`.
- **`sniff2.js`** — DevTools sniffer (collapses HID traffic by opcode signature so
  live depth doesn't flood). `neoSummary()` / `neoSave()`. This is what found `d0 a6`.
- **`probe.py`** — active driver. Useful mode: `keymap [secs] [thr]` (map keys→indices).
- **`cap.py`** — passive hidraw logger (needs something else polling the board).

## What's built (`neo-pad/` — Rust, Phase 4)
Cargo crate; the Phase 3 logic ported to Rust as the cross-platform base.
- **`src/protocol.rs`** ⭐ — read core via the **`hidapi`** crate (same on Linux &
  Windows): `find_device()` (VID:PID + usage page 0xFF60), the safe `d0 a6` paged
  read, `norm()`, WASD constants. The mirror of `neo_core.py`.
- **`src/pad.rs`** — `Pad` trait + `new_pad()`; Linux backend is a hand-rolled
  uinput device (same ioctl structs as `gamepad.py`). **Windows backend goes here**
  under `#[cfg(windows)]`.
- **`src/main.rs`** — arg parsing, mapping/`shape()`/SOCD, poll loop. Flags mirror
  `gamepad.py` plus `--selftest` (sweep the stick with no keyboard, for `jsmon.py`).
- Build/run: `cargo run --release --manifest-path neo-pad/Cargo.toml -- --monitor`.
  (`target/` is gitignored.)

## NEXT: Phase 4 — Windows ViGEm backend

The Rust core is done and Linux-verified; **all that's left is the Windows output
shim.** `protocol.rs` (hidapi read) and `main.rs` (mapping/curve/SOCD/loop) are
already cross-platform and need **no changes** — you only add a `Pad` backend.

### Prerequisites on the Windows box
- **Rust toolchain** (`rustup` → stable MSVC, i.e. `x86_64-pc-windows-msvc`). MSVC
  build tools must be installed (rustup prompts for them).
- **ViGEmBus driver, pinned to 1.22.0** — install the signed MSI from the ViGEm
  releases. The repo is archived but 1.22.0 is the stable build DS4Windows ships;
  expect no updates. Without it, `vigem-client` fails to connect at runtime.
- The keyboard plugged in **wired**. (On Windows the same VID:PID `0xE560:0xEE65`
  + usage page `0xFF60` interface is what hidapi must open — see step 2.)
- The repo cloned; `cargo build --manifest-path neo-pad\Cargo.toml` should already
  compile the cross-platform parts (it'll just hit the `new_pad()` "no backend"
  error at runtime until you do step 1).

### Step 1 — add the backend in `neo-pad/src/pad.rs`
Add the `vigem-client` crate under `[target.'cfg(windows)'.dependencies]` in
`neo-pad/Cargo.toml`, then add a `#[cfg(windows)] mod win_vigem` and route the
`#[cfg(not(target_os = "linux"))] new_pad()` (or a dedicated `#[cfg(windows)]`
one) to it. Skeleton (verify exact API against the installed `vigem-client`
version — names like `Client`, `Xbox360Wired`, `XGamepad`, `XButtons` may differ):

```rust
#[cfg(windows)]
mod win_vigem {
    use super::Pad;
    use vigem_client::{Client, TargetId, XGamepad, Xbox360Wired};

    pub struct VigemPad { target: Xbox360Wired<Client>, gp: XGamepad }
    impl VigemPad {
        pub fn new() -> std::io::Result<Self> {
            let client = Client::connect()            // needs ViGEmBus 1.22.0 installed
                .map_err(|e| std::io::Error::other(format!("ViGEmBus connect: {e}")))?;
            let mut target = Xbox360Wired::new(client, TargetId::XBOX360_WIRED);
            target.plugin().and_then(|_| target.wait_ready())
                .map_err(|e| std::io::Error::other(format!("ViGEm plugin: {e}")))?;
            Ok(Self { target, gp: XGamepad::default() })
        }
    }
    impl Pad for VigemPad {
        fn set_left_stick(&mut self, x: f32, y: f32) {
            // main.rs gives x,y in [-1,1]. ViGEm thumb axes are i16, +Y = up,
            // so NEGATE y (our Y is screen-down-positive). Clamp to i16 range.
            let s = |v: f32| (v.clamp(-1.0, 1.0) * 32767.0).round() as i16;
            self.gp.thumb_lx = s(x);
            self.gp.thumb_ly = s(-y);
            let _ = self.target.update(&self.gp);
        }
    }
}
```
The Linux `UinputPad` negated nothing because evdev ABS_Y is down-positive; **XInput
is up-positive, so flip Y here** (or flip the mapping in main.rs — pick one place).

### Step 2 — confirm hidapi opens the right interface on Windows
`protocol::find_device()` filters on `vendor_id == 0xE560 && product_id == 0xEE65
&& usage_page == 0xFF60`. hidapi's Windows backend populates `usage_page` per
top-level collection, so this should just work. If `find_device` returns `None`,
enumerate and print `(vendor_id, product_id, usage_page, usage, path)` for all
matches to see what Windows exposes, and relax/adjust the filter (it may surface
the interface differently than Linux hidraw).

### Step 3 — verify
- `cargo run --release --manifest-path neo-pad\Cargo.toml -- --monitor`, press
  W/A/S/D; the `--monitor` line should move (proves read+mapping) and...
- Open **`joy.cpl`** (Set up USB game controllers → Properties) or Steam → Settings
  → Controller; the virtual Xbox pad's left stick should track your key depth.
- Then the real goal: launch a game with controller support and confirm proportional
  walk→run on the left stick.

### Open considerations for Phase 4+
- **Poll rate / latency:** `gamepad.py` defaults to a 200 Hz `--rate`; each frame is
  still 2 USB request/response round-trips (one per WASD page). Tune for feel vs CPU.
- **Suppressing raw keys:** while the virtual pad is active, the physical W/A/S/D still
  send normal keystrokes to the OS. Some games fight having both keyboard + pad present
  (Wooting documented this). Decide per-game whether to grab/suppress the keys; this is
  Phase 5 territory but keep it in mind when testing.
- **Heartbeat:** NeoFlux sends `d0 b0` ~1/s. `reader.py` works without it; if the channel
  ever stalls during long runs, interleave a `d0 b0` heartbeat.

## Verify the current state

**Phase 2 (reader), ~10 s:** `python tools/reader.py` → press W/A/S/D → bars fill
proportionally and move independently. (Confirmed working 2026-05-30.) Ctrl-C to stop.

**Phase 3 (gamepad), human live test — the one step not yet done headless:**
two terminals.
- Terminal A: `python tools/gamepad.py --monitor`  (creates the pad, prints its own X/Y)
- Terminal B: `python tools/jsmon.py`  (shows what the *kernel* sees — independent check)
- Press/partially-press W/A/S/D: both should track, stick travel proportional to
  depth, X and Y independent, opposing keys (A+D / W+S) cancel toward center.
- Or point any game / online gamepad tester at "Neo65 HE Analog Pad".
Needs write access to `/dev/uinput` (root, or a group/ACL on the node — the `input`
group already has it here). Already auto-verified: device enumerates as a 6-axis pad
and emitted axis values read back exactly via the kernel (`jsmon`, cross-process).

**Phase 4 (Rust crate `neo-pad/`):**
- Pad path: `cargo run --release --manifest-path neo-pad/Cargo.toml -- --selftest`
  in one terminal + `python tools/jsmon.py` in another → kernel sees a swept stick
  (auto-verified). Read path auto-verified live against the board (sentinel test).
- Live feel (same as Phase 3 human test): `cargo run --release --manifest-path
  neo-pad/Cargo.toml -- --monitor` + `jsmon.py`, then press W/A/S/D.
