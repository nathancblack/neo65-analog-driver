# Neo65 Sonic HE+ — Analog Depth HID Protocol

**Status:** Phase 0 **GO** · Phase 1 (decode) **DONE** · Phase 2 (Linux reader)
**DONE + VERIFIED LIVE 2026-05-30.** Make-or-break **RESOLVED: per-key live depth
IS reachable.** `d0 ad` is an aggregate dead-end, BUT a NeoFlux full-matrix-view
sniff revealed **`d0 a6 <startIndex> <count>` — a paginated live per-key depth
array.** W/A/S/D each drive distinct fixed indices; `tools/reader.py` reads all
four independently and proportional bars were confirmed live on hardware.
**Next: Phase 3 — uinput virtual gamepad.** See
[Per-key depth map](#per-key-depth-map--d0-a6-the-real-channel) and `HANDOFF.md`.

This file is the living protocol record. `HANDOFF.md` is the start-here for a
fresh session; read it first, then this.

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

## Per-key depth map — `d0 a6` (THE real channel)  ✅ RESOLVED 2026-05-30

The steady-state loop hides the good stuff. Opening NeoFlux's **full per-key
matrix / Switch-Calibration view** (all keys at once) starts a high-rate poll of
a new opcode never seen before: **`d0 a6`, a paginated live per-key depth array.**

- **Request:** `d0 a6 <startIndex> <count> 00…` (32 B, zero-padded).
  - byte 2 = **starting key index**; byte 3 = **number of keys** in this page.
- **Reply:** `d0 a6 <startIndex> <count>` echoed in bytes [0..3], then **`count`
  consecutive 16-bit BIG-ENDIAN depth values** packed from **byte 4** onward
  (same units/scale as `d0 ad`: rest ≈ `0x012c`, bottom-out = `0x80e8`).
- **NeoFlux's matrix loop = 6 pages covering 80 key slots (index 0x00–0x4f):**

  | request | start idx | count | covers indices |
  |---|---|---|---|
  | `d0 a6 00 0e` | 0  | 14 | 0–13 |
  | `d0 a6 0e 0e` | 14 | 14 | 14–27 |
  | `d0 a6 1c 0e` | 28 | 14 | 28–41 |
  | `d0 a6 2a 0e` | 42 | 14 | 42–55 |
  | `d0 a6 38 0e` | 56 | 14 | 56–69 |
  | `d0 a6 46 0a` | 70 | 10 | 70–79 |

- **Proof it's per-key (not aggregate):** in the sniff, pressing W + D made two
  *different* reply slots ramp to `0x80e8` — page `0e` byte 12–13 (→ **key index
  18**) and page `1c` byte 18–19 (→ **key index 35**). Distinct fixed indices,
  independent values. This is the capability `d0 ad` lacked.
- **Safe to replay:** NeoFlux sends `d0 a6` itself, and it's a length-prefixed
  read returning data → not a setter. Cleared under the §SAFETY rule.
- **Replay it with:** `python tools/probe.py keymap [secs] [thr]` — pages all 6
  reads, reassembles the 80-slot array, and live-prints which indices exceed the
  threshold as you press keys. Use it to map W/A/S/D → their indices.

### WASD → index map  ✅ CONFIRMED 2026-05-30 (`probe.py keymap`)

| key | index | hex | page that carries it |
|---|---|---|---|
| **W** | 18 | 0x12 | `d0 a6 0e 0e` (covers 14–27) |
| **A** | 33 | 0x21 | `d0 a6 1c 0e` (covers 28–41) |
| **S** | 34 | 0x22 | `d0 a6 1c 0e` |
| **D** | 35 | 0x23 | `d0 a6 1c 0e` |

- Each index ramps **smoothly + monotonically** `~0x012c`(rest) → `0x80e8`(full)
  and back, one dedicated slot per key. Independent — exactly what diagonals need.
- **I/O shortcut:** all of WASD lives in just **2 pages** (`0e 0e` + `1c 0e`), so
  the reader polls 2 reports/frame, not 6.
- Byte offsets within each reply (`count`=14, data from byte 4):
  W → page `0e`, value index `18-14=4` → reply bytes **[12,13]**.
  A/S/D → page `1c`, value indices `5/6/7` → reply bytes **[14,15]/[16,17]/[18,19]**.
- (`keymap` also caught index **45** = Enter releasing at t=0 — a launch artifact, not a mapping.)

### Phase 2 reader → `tools/reader.py`  ✅ DONE + VERIFIED LIVE 2026-05-30
Polls the 2 WASD pages, normalizes each depth to 0..1 (`(v-0x012c)/(0x80e8-0x012c)`),
prints live bars. Auto-finds the channel by report-descriptor usage page `0xFF60`
(robust to hidraw renumbering). **Confirmed on hardware:** bars track press depth
proportionally and W/A/S/D move independently (diagonals work). Run: `python tools/reader.py`.

### NEXT (Phase 3): uinput virtual gamepad
Feed the four normalized depths into a uinput joystick: W/S → Y axis, A/D → X axis,
with a small rest deadzone, a response curve (linear first, then mild expo), and
SOCD handling for opposing keys. Verify with `evtest`/`jstest` or a gamepad tester.
The reader's decode + channel-discovery code is the reusable core; only the output
shim is new. See `HANDOFF.md` for the concrete starting steps.

## Open question — independent key reads  ✅ RESOLVED (was ⛔ MAKE-OR-BREAK)

**RESOLVED 2026-05-30 by the `d0 a6` discovery above — per-key reads work.** The
notes below are the dead-end history of `d0 ad`; kept so we don't re-walk it.

- The depth poll `d0 ad 00 00` carries **no key index** (bytes 2–31 = 0).
- **Selecting W/A/S/D in NeoFlux sends NOTHING to the board.** Verified with a filtered sniffer: while
  selecting *and* pressing each of W/A/S/D, the only OUT reports ever sent were `d0 b0` and `d0 ad 00 00`.
- So the board returns **one aggregate depth**, independent of UI selection. Working hypothesis: it reports
  the **single deepest-pressed key** on the board, and the per-key gauge in NeoFlux is just a cosmetic label.
- **Why it matters:** if `d0 ad 00 00` only ever returns the deepest key, we **cannot read W and D
  independently** (diagonals break) — fatal for analog WASD as designed.

### RESULT (2026-05-30): byte-2 addressing is dead — aggregate-only confirmed
`python tools/probe.py scanhold 12` while holding **W** fully down returned **all 64
channels byte-for-byte identical** (`max=0x80e8`, `min=0x0258`, `delta=32400` on every
index). Identical, not merely "all high" → the index byte in `d0 ad <i> 00` is **ignored**;
there is a **single shared depth register**. This confirms the deepest-key-aggregate
hypothesis. `d0 ad` **cannot** read W and D independently → fatal for analog WASD as
originally designed. **Do not start Phase 2 on this opcode.**

### Pivot — next tests (in progress)
Two cheap insurance checks, then the real hunt:
1. `python tools/probe.py scanhold4 12` — same hold-W test but index in **byte 4** (request
   byte meanings ≠ reply's). One/few high → selector just moved bytes, per-key lives.
2. `python tools/probe.py opcodescan` — sweep `d0 XX 00 00` at rest; flag any opcode whose
   reply has many nonzero payload bytes = candidate **bulk per-key map** (a 64-key 16-bit
   map = 128 B = ~4 chunked 32 B reports). Narrow with `opcodescan 0xa0 0xbf` if wary.
3. **Highest leverage (needs browser):** open NeoFlux's **Switch Calibration / full matrix
   view** (the screen showing *all* keys at once, not the WASD picker) with the §9 sniffer
   running. If it renders per-key live, it MUST send an opcode we haven't seen — capture it.
   If even that view sends only `d0 b0` + `d0 ad 00 00`, the board doesn't expose per-key on
   this channel → escape hatches (custom RP2040/QMK firmware, or Wooting plugin) per brief §5.

### opcodescan result (2026-05-30) + a transport gotcha
Swept `d0 XX 00 00`. **Gotcha: replies lag/buffer.** In a fast scan a missed read shifts
every later reply, so the reply opcode ran ~2 behind the request. **The device echoes the
opcode it is answering**, so attribute by **`reply[1]`**, not by what you sent. `probe.py`
now uses `xchg()` (flush stale replies → send → read until echo matches) so this is fixed.

Real opcodes the board answers (keyed by `reply[1]`, at rest). These look like **static
config/calibration reads**, not a live per-key array (and 64 keys can't fit one 32 B report):

| opcode | payload @ rest | guess |
|---|---|---|
| `d0 ad` | `01 2c` = 300 | live depth (aggregate) — confirmed |
| `d0 ac` | `80e8 3a98 07d0 07d0` = 33000,15000,2000,2000 | calibration ranges / thresholds |
| `d0 d0` | `1f40 5dc0 5dc0 1f40` = 8000,24000,24000,8000 | symmetric thresholds |
| `d0 d8` | `1f40 3e80 5dc0` = 8000,16000,24000 | evenly-spaced steps (DKS/actuation?) |
| `d0 c4` | `0000 1388 1388` = 5000,5000 | threshold pair |
| `d0 a5` | `01 01 0b 01 2c` | config struct |
| `d0 bf` | `01 0b 09 fd 00 03 05 45 01 ef` | config struct |
| `d0 01` | `0e …01 01 01 01` | version / feature flags |
| also answer (short): `d0 0f/10/11/12` (empty), `d0 23/90/a0/a1/a3/a9/b4/b6/b7/c1` | | |

### ⚠️ SAFETY (2026-05-30): some `d0 XX` opcodes are SETTERS — do NOT blind-write
`watch 0xac/0xc4/...` (polls an opcode ~1000×/run with a zero payload) **corrupted live
key config**: backspace + number keys stopped actuating (threshold pushed out of range).
**Recovered fully by unplug/replug** → damage was volatile RAM only, not written to EEPROM.
Lesson: `d0 ad`/`d0 b0` are confirmed safe reads; the rest are unknown and at least some are
writes. **Rule going forward: never issue an opcode we haven't first observed NeoFlux send.**
`opcodescan`/`watch`/`chunk` are now considered unsafe-by-default — leave them unused.

### Safe path = passive observation only
1. **NeoFlux + DevTools §9 sniffer** (host→device + device→host, fully visible). Open the
   **full per-key matrix / calibration view**, press W then D; capture every OUT opcode and
   IN report. This shows whether per-key live data exists AND the exact (safe) command to
   replay. This is now the primary next step — it writes nothing of our own.
2. `cap.py` passive read of hidraw5 while NeoFlux drives the board, as a cross-check.

Only after we SEE the per-key opcode in the sniff do we replay it from `probe.py`.

## Tools (`tools/`)

- **`reader.py`** — ⭐ **Phase 2 reader / current main tool.** `python tools/reader.py [secs]`.
  Auto-finds the `0xFF60` channel, polls the 2 WASD pages of `d0 a6`, prints live normalized
  bars for W/A/S/D. This is the reusable core for Phase 3 (decode + channel discovery).
- **`sniff2.js`** — DevTools sniffer that collapses HID traffic by **opcode signature**
  (not full payload, so live depth doesn't flood). Paste into NeoFlux's console; `neoSummary()`
  prints a short summary, `neoSave()` downloads `neo65-sniff.json`. This is what found `d0 a6`.
- **`probe.py`** — active driver; no browser needed. Modes: `selftest` | `poll <secs>` |
  **`keymap [secs] [thr]`** (replay the `d0 a6` per-key depth map; used to map W/A/S/D) |
  `scan` | `scanhold <secs>` | `guide` | `scanhold4 <secs>` (index in byte 4) |
  `opcodescan [start] [end]` (sweep `d0 XX` — ⚠️ unsafe-by-default, see §SAFETY).
- **`cap.py`** — passive reader of a hidraw node; logs only changed reports.
  `python tools/cap.py /dev/hidraw5 <secs> <logfile>`. Only sees device→host, so the board must be
  polled by something else (browser or `probe.py`) for data to appear.

## Evidence

- W press (selected), polled depth: `0x012c → … → 0x80e8 → … → 0x012c`, smooth/monotonic, bytes [2..3] only.
  This is the Phase 0 GO signal: plaintext, sustained, on-demand analog depth over a QMK raw-HID channel.
