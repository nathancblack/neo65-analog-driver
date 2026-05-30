# Neo65 Sonic HE+ — Analog Depth HID Protocol

**Status:** Phase 0 (recon) **COMPLETE → GO**. Phase 1 (decode) ~80% done.
One make-or-break question remains open — see [Open question](#open-question--independent-key-reads).

This file is the living protocol record + session handoff. Read it before resuming.

---

## Device identity

- **USB VID:PID = `0xE560:0xEE65`**, product `"NEO Neo65 HE"`, manufacturer `"NEO"` (wired mode).
- Presents **5 USB interfaces**:

| if | class/proto | role | Linux node | use |
|----|-------------|------|-----------|-----|
| 00 | HID, proto 1 | boot keyboard | hidraw3 | ❌ ignore |
| 01 | HID, proto 0 | **vendor "raw HID", usage page `0xFF60` usage `0x61`** | **hidraw5** | ✅ **config/analog channel** |
| 02 | HID, proto 0 | composite mouse/system/consumer/NKRO | hidraw4 | ❌ ignore |
| 03 | CDC comms | virtual serial (control) | — | ❌ ignore |
| 04 | CDC-data | virtual serial (data) | — | ❌ ignore |

- The `0xFF60 / 0x61 / 0x62 / 0x63` descriptor is the **QMK "Raw HID"** signature → firmware is almost
  certainly QMK-based. Firmware ships as `neo65he_v1.2.0_*.uf2` (UF2 → RP2040/RP2350 likely).
- **Permissions:** `/etc/udev/rules.d/99-hid.rules` already sets `KERNEL=="hidraw*", MODE="0666"`, so the
  device is world-RW — **no new udev rule needed**. User `nate` is in group `input`.
- ⚠️ hidraw numbering can shift across replug. Match the channel by **usage page `0xFF60`** (or VID:PID +
  interface 01), not by the literal `hidraw5`.

## Transport

- Reports are **32 bytes, UNNUMBERED** (report ID 0), both Input (device→host) and Output (host→device).
- **Strict request/response, host-driven.** The board sends nothing unsolicited (verified: 3s idle read = 0
  reports). Something must poll it for data to appear.
- **Linux hidraw I/O:** to send a report, `write()` **33 bytes** = `[0x00 report-id] + 32 payload`. Reads
  return the **32** payload bytes.

## Commands (all host→device, 32 B, zero-padded)

- **Heartbeat:** `d0 b0 00…` → reply `d0 b0 00…`. NeoFlux sends ~1/sec to keep the channel alive.
- **Depth poll:** `d0 ad 00 00 00…` → reply `d0 ad <hi> <lo> 00…`
  - **Depth = `(hi<<8) | lo`, 16-bit BIG-ENDIAN, bytes [2..3].** Only bytes 2–3 ever vary.
  - Rest (key up) ≈ `0x012c`–`0x0190` (300–400). Bottom-out = `0x80e8` (33000). Smooth, monotonic up with
    travel. Values look like firmware-scaled decimal units; calibrate empirically per key.
- NeoFlux's steady-state loop is just these two alternating.

## Open question — independent key reads  ⛔ MAKE-OR-BREAK

- The depth poll `d0 ad 00 00` carries **no key index** (bytes 2–31 = 0).
- **Selecting W/A/S/D in NeoFlux sends NOTHING to the board.** Verified with a filtered sniffer: while
  selecting *and* pressing each of W/A/S/D, the only OUT reports ever sent were `d0 b0` and `d0 ad 00 00`.
- So the board returns **one aggregate depth**, independent of UI selection. Working hypothesis: it reports
  the **single deepest-pressed key** on the board, and the per-key gauge in NeoFlux is just a cosmetic label.
- **Why it matters:** if `d0 ad 00 00` only ever returns the deepest key, we **cannot read W and D
  independently** (diagonals break) — fatal for analog WASD as designed.

### Next test (pending — was interrupted to write this handoff)
Run with the browser/NeoFlux tab **closed** so we have exclusive access to hidraw5:
1. `python tools/probe.py selftest` — confirm Linux write+read talks to the board.
2. `python tools/probe.py poll 30` — poll while **holding W ~half-depth, then also press+hold D full**, then
   release D, then W.
   - Value tracks **max of both** → command is deepest-key-only → must find another path:
     - `python tools/probe.py scan` — test whether `d0 ad <i> 00` with nonzero byte 2 addresses a specific key.
     - Capture NeoFlux's **Switch Calibration** / matrix views for a bulk "all keys" opcode.
   - Value somehow exposes both keys → proceed to **Phase 2** (Linux reader).

## Tools (`tools/`)

- **`cap.py`** — passive reader of a hidraw node; logs only changed reports.
  `python tools/cap.py /dev/hidraw5 <secs> <logfile>`. Only sees device→host, so the board must be polled by
  something else (browser or `probe.py`) for data to appear.
- **`probe.py`** — active driver; no browser needed. Modes: `selftest` | `poll <secs>` | `scan`.

## Evidence

- W press (selected), polled depth: `0x012c → … → 0x80e8 → … → 0x012c`, smooth/monotonic, bytes [2..3] only.
  This is the Phase 0 GO signal: plaintext, sustained, on-demand analog depth over a QMK raw-HID channel.
