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
| 3 | Linux virtual gamepad (uinput) | ✅ **DONE — uinput path verified; pending human live WASD test** |
| 4 | **Windows port (ViGEm)** | ⏭️ **NEXT — start here** |
| 5 | Per-game tuning | not started |

**Phase 3 result:** `tools/gamepad.py` presents a pure-Python uinput Xbox-style
pad (no third-party deps — this box has no pip and Python 3.14) whose **left stick
follows W/A/S/D depth**. Verified that the virtual device enumerates as a 6-axis
gamepad and that emitted axis values read back exactly through the kernel event
node (cross-process, via `tools/jsmon.py`). **Not yet done:** a human pressing the
physical keys and watching the stick — see "Verify" below. Mapping:
`X = shape(D) − shape(A)`, `Y = shape(S) − shape(W)`, with rest deadzone + optional
expo; opposing keys cancel (subtractive SOCD).

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

## NEXT: Phase 4 — Windows port (ViGEm)

Phase 3 is built and the uinput path is verified; the Linux PoC is in `gamepad.py`.
Before moving on, do the **human live test** (below) to confirm physical W/A/S/D
drives the stick smoothly and tune `--deadzone`/`--expo` to taste.

For Windows: swap only the output shim — keep `neo_core.py`'s channel discovery,
`d0 a6` read, and `norm()` unchanged.
1. **Output shim:** ViGEm Xbox-360 pad (pin **ViGEmBus 1.22.0**). If staying in
   Python, `vgamepad`; if porting to the brief's Rust target, `vigem-client` +
   `hidapi`. Map the same `X = shape(D)-shape(A)`, `Y = shape(S)-shape(W)`.
2. **Channel discovery on Windows:** the 0xFF60-usage-page lookup is Linux-sysfs
   specific — replace `find_channel()` with `hidapi` enumeration filtering on
   VID:PID `0xE560:0xEE65` + usage page `0xFF60`. The transport (32-byte reports,
   leading report-id byte, request/response) is the same.
3. **Verify** with the Windows "Game Controllers" (joy.cpl) applet or Steam Input.

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
