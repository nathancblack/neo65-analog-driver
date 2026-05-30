# Neo65 Analog Driver — Session Handoff

**Start here.** This is the fast on-ramp for a fresh context window. Read this
top to bottom, then skim `PROTOCOL.md` for byte-level detail. The big static
brief is `neo65-analog-driver-PROJECT.md` (rationale + architecture; not status).

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
| 3 | **Linux virtual gamepad (uinput)** | ⏭️ **NEXT — start here** |
| 4 | Windows port (ViGEm) | not started |
| 5 | Per-game tuning | not started |

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
   unsafe-by-default — leave them unused. Reading `d0 a6` is safe and is all Phase 3 needs.

## What's built (`tools/`)
- **`reader.py`** ⭐ — Phase 2 reader. `python tools/reader.py [secs]`. Auto-finds the
  channel, polls the 2 WASD pages, prints live normalized bars. **Its decode +
  channel-discovery code is the reusable core for Phase 3** — don't rewrite it.
- **`sniff2.js`** — DevTools sniffer (collapses HID traffic by opcode signature so
  live depth doesn't flood). `neoSummary()` / `neoSave()`. This is what found `d0 a6`.
- **`probe.py`** — active driver. Useful mode: `keymap [secs] [thr]` (map keys→indices).
- **`cap.py`** — passive hidraw logger (needs something else polling the board).

## NEXT: Phase 3 — uinput virtual gamepad

Goal: present a virtual Xbox-style pad on Linux whose stick axes follow key depth.

Concrete starting steps:
1. **Pick the binding.** Python `python-uinput` or `evdev`/`uinput` is fine for a
   Linux PoC (the brief's long-term lang is Rust w/ `hidapi`+`uinput`+`vigem-client`,
   but match the existing Python tools for Phase 3 speed; port to Rust later if desired).
2. **Reuse `reader.py`'s core**: `find_channel()`, the 2-page `d0 a6` read, and `norm()`.
   Factor those into something importable rather than copy-paste if it's clean.
3. **Create a uinput joystick** with ABS_X and ABS_Y axes (range e.g. -32768..32767).
4. **Map:** `Y = norm(S) - norm(W)` (or invert to taste), `X = norm(D) - norm(A)`.
   Add a small **rest deadzone**, then a response **curve** (linear first, then mild
   expo). Handle opposing keys (SOCD: last-input-wins or neutral).
5. **Verify** with `evtest` / `jstest` / `jstest-gtk`, or an online gamepad tester,
   or a Linux game. Watch for smooth proportional axis travel, independent X/Y.
6. Once smooth on Linux → **Phase 4**: swap the uinput shim for a ViGEm Xbox-360 pad
   on Windows (pin ViGEmBus 1.22.0; `vigem-client` Rust crate). Core stays unchanged.

### Open considerations for Phase 3+
- **Poll rate / latency:** `reader.py` sleeps 5 ms/loop; tune for responsiveness vs CPU.
  Each frame = 2 USB request/response round-trips.
- **Suppressing raw keys:** while the virtual pad is active, the physical W/A/S/D still
  send normal keystrokes to the OS. Some games fight having both keyboard + pad present
  (Wooting documented this). Decide per-game whether to grab/suppress the keys; this is
  Phase 5 territory but keep it in mind when testing.
- **Heartbeat:** NeoFlux sends `d0 b0` ~1/s. `reader.py` works without it; if the channel
  ever stalls during long runs, interleave a `d0 b0` heartbeat.

## Verify the current state in 10 seconds
`python tools/reader.py` → press W/A/S/D → bars fill proportionally to depth and
move independently. (Confirmed working 2026-05-30.) Ctrl-C to stop.
