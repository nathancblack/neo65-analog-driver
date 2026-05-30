# Neo65 Sonic HE+ Analog Input Driver

> Handoff brief for a fresh Claude Code session. This file is self-contained.
> Read it top to bottom before writing any code. The owner (Nathan) has already
> done the scoping below with a previous Claude session; your job is to execute
> the plan, starting at **Phase 0 recon**, and to respect the go/no-go gate.

---

## 1. Goal

Turn a **QwertyKeys Neo65 Sonic HE+** Hall-effect keyboard into a true analog
input device, so that key press *depth* drives a virtual gamepad **stick axis**.
The target use case is fine movement control (walk-to-run) in single-player
games, the way a Wooting board does it natively.

- **Deploy target:** Windows (where games are played).
- **Dev/recon environment:** Arch Linux (the owner's daily driver: Hyprland,
  Neovim). Everything except the final output layer is developed and tested
  here first.

## 2. The core problem (read this before anything else)

A Hall-effect switch senses key travel as an analog value *inside the board*.
That is how rapid trigger and adjustable actuation work. **But by default the
keyboard still reports plain on/off keypresses to the OS, exactly like any
keyboard.** "Analog switch" and "analog signal reaching the game" are two
different layers. Closing that gap is the whole project.

To get analog movement you must:
1. Read the per-key analog *depth* values off the board (over USB HID), and
2. Feed them into a **virtual gamepad** as proportional axis values, because
   nearly every game reads analog movement via XInput/gamepad, not keyboard.

The Neo65 almost certainly exposes depth over HID already, because its web
configurator draws live per-key calibration graphs. The data exists; nothing
public surfaces it to games. (confidence 8/10 the data is retrievable on demand)

## 3. Why existing tools do NOT solve this

- **Wooting Analog SDK** is the standard open driver for analog keyboards, but
  its default plugin talks to **Wooting hardware only**. Its recent "generic
  device handling" covers new *Wooting* devices, not arbitrary vendors. It will
  not auto-detect the Neo65. (confidence 8/10)
- **reWASD / vJoy / Steam Input / JoyToKey** can map keys onto a virtual stick,
  but they only see the digital keypress, so you get full-tilt movement, never
  proportional depth.
- **Dynamic Keystroke (DKS)** on the board gives up to 4 actions at 4 depths.
  That is discrete, max ~4 levels, and most games lack separate walk/run binds.
  Not a real analog substitute.
- No public Neo65 / QwertyKeys analog-to-gamepad driver or SDK plugin was found
  in searches across the analog-keyboard SDK ecosystem, GitHub HID/reverse-eng
  topics, and QwertyKeys-specific terms. (confidence 7/10 that none is widely
  published; absence of search hits is not proof. **First action item: still
  check the QwertyKeys official Discord and search GitHub for "neo65" /
  "qwertykeys analog" before writing code, in case private work exists.**)

## 4. Hardware / software facts

| Item | Value | Confidence |
|---|---|---|
| Keyboard | QwertyKeys Neo65 Sonic HE+ (OwLab Nova magnetic switches) | 9/10 |
| Config tool | NeoFlux web configurator at `https://he.qwertykeys.com/` | 8/10 |
| Config transport | WebHID (runs in browser, no install) | 8/10 |
| Polling rate | 8000 Hz, ~0.125 ms response (marketing figure) | 7/10 |
| Native analog/gamepad mode | **None advertised** anywhere | 7/10 |
| Connectivity for analog work | Use **wired**; treat tri-mode wireless as out of scope | 8/10 |
| MCU model | **UNKNOWN** (one low-quality source claimed RP2040 for the non-HE Neo65; do not trust it). Marketing only says "high-frequency MCU". | 3/10 |
| Analog value resolution | **UNKNOWN until captured.** Could be 8-bit (0-255) or 10/12-bit little-endian. Determine empirically; do not assume. | n/a |

WebHID is **Chromium-only** (no Firefox). On Arch, install `chromium` or
`google-chrome`. WebHID works on Linux Chromium but needs hidraw access, so a
udev rule is likely required (see Phase 0).

## 5. Architecture

```
                 PORTABLE CORE (write once, runs everywhere)
  +----------------------------------------------------------+
  |  HID reader (hidapi)  ->  decode depth  ->  axis mapping  |
  +----------------------------------------------------------+
                 |                                  |
        Linux output shim                  Windows output shim
        (uinput virtual joystick)          (ViGEmBus, XInput pad)
        -> test with evtest/jstest         -> what games actually read
```

- **Core**, identical on both OSes: open the device with `hidapi`, replay any
  required init/poll, parse the analog report, map chosen keys (W/A/S/D first)
  to X/Y axis values with deadzone and curve.
- **Output is the only OS-specific part.** Linux: `uinput`. Windows: `ViGEmBus`
  + `ViGEmClient` (emulate an Xbox 360 / XInput pad). Keep this behind a thin
  trait/interface so the core never changes.
- **Recommended language: Rust.** Clean cross-platform story: `hidapi` crate for
  reading, `uinput` crate for Linux output, `vigem-client` crate for Windows
  output. C with hidapi + raw ViGEmClient also works if preferred.

## 6. Plan (phased, with the gate)

### Phase 0 — Recon (DO THIS FIRST)
1. Sanity check: search GitHub + QwertyKeys Discord for prior work (section 3).
2. On Arch, open the configurator in Chromium, connect the board wired.
3. Add a udev rule if the browser cannot see the device, e.g. create
   `/etc/udev/rules.d/99-neo65.rules` with a `hidraw`/`usb` match on the board's
   VID:PID (get VID:PID from `lsusb` or the sniffer), set `MODE="0660"` and your
   group, then `sudo udevadm control --reload && sudo udevadm trigger`.
4. Open DevTools (F12) -> Console, paste the **sniffer script in section 9**.
5. Go to the live per-key calibration / analog graph view. Press **W** slowly
   from rest to full bottom-out, release. Repeat with **A**.
6. Save the full console dump.

**GO/NO-GO GATE:** If pressing W makes one byte (or byte pair) ramp smoothly
from low to high in the log, the project is feasible: continue. If analog data
only appears during a one-shot calibration sequence that cannot be sustained, or
the stream is encrypted/obfuscated, **stop and reassess** rather than grinding.
(Plaintext-ish protocol expected, confidence 8/10. WebHID makes any init
handshake fully visible, which is the big advantage over sniffing a binary.)

### Phase 1 — Decode the protocol
From the dump, establish: the device **VID:PID**, the **report ID** carrying the
analog stream, whether data arrives as async **input reports** or via
**feature-report polling** (request/response), any **init/handshake** command
NeoFlux sends before data flows, the **byte offset(s)** that move for W vs A
(reveals per-key indexing), and the **value range + endianness**. Document all
of this in a `PROTOCOL.md`.

### Phase 2 — Linux reader
Open the device via hidapi, replay the init/poll exactly as captured, and print
decoded depth for W/A/S/D in real time. Confirm it matches what you saw in the
browser.

### Phase 3 — Linux virtual gamepad
Create a uinput virtual joystick. Map W/S to the Y axis and A/D to the X axis,
with a small deadzone near rest and a configurable response curve (linear first,
then try a mild expo). Handle opposing keys (SOCD-style: last-input or neutral).
Verify with `evtest` / `jstest` and a Linux game or the gamepad tester.

### Phase 4 — Windows port
Swap the uinput shim for a ViGEm shim presenting an Xbox 360 pad. Compile on
Windows. The core and decoder stay untouched.

### Phase 5 — Per-game tuning
Expect friction here, not in our code. Some games swap between keyboard and
gamepad device modes and fight having both present (Wooting documented this
exact issue). Tune deadzone/curve per game, and decide per title whether to
suppress the raw keyboard keys while the virtual pad is active.

## 7. Risks and honest confidence

- Working proof of concept (analog W/S on one axis in a test): **~7/10**.
- Smooth behavior in the specific single-player games wanted: **~5-6/10**, and
  the limiting factor is per-game keyboard-vs-gamepad handling, not the driver.
- Biggest single risk lives entirely in **Phase 0**: whether the board streams
  depth on demand or only during an unsustainable calibration handshake.

## 8. Open questions to resolve during recon
- VID:PID of the Sonic HE+ in wired mode?
- Async input reports or polled feature reports?
- Is there an init/"start streaming" command? Capture it verbatim if so.
- Value resolution and endianness (8-bit vs 10/12-bit LE)?
- How are the 60-something keys indexed in the report (one big array? per-key
  request?), and where do W and A land?
- Does the board keep streaming analog while a game has focus, or only while the
  configurator tab is active?

## 9. DevTools sniffer script

Paste into the Chromium DevTools Console on `he.qwertykeys.com` with the board
connected. It wraps the WebHID calls and logs only reports whose bytes change,
so the console will not flood. If nothing logs, the page opened the device
before the wrap took effect: unplug/replug the board (or hit reconnect) so the
handlers catch it.

```js
(() => {
  const toHex = (d) => {
    const b = new Uint8Array(d.buffer ?? d);
    return [...b].map(x => x.toString(16).padStart(2, '0')).join(' ');
  };
  const last = {};
  const log = (tag, id, data) => {
    const hex = toHex(data);
    const k = tag + ':' + id;
    if (last[k] === hex) return;            // only show bytes that move
    last[k] = hex;
    console.log(`%c${tag}%c id=${id} len=${data.byteLength ?? data.length} | ${hex}`,
                'color:#0bf;font-weight:bold', 'color:inherit');
  };

  const P = HIDDevice.prototype;
  const wrap = (name, kind) => {
    const orig = P[name];
    if (!orig || orig.__snf) return;
    P[name] = function (id, data) { try { log(kind, id, data ?? new Uint8Array()); } catch (e) {} return orig.apply(this, arguments); };
    P[name].__snf = true;
  };
  wrap('sendReport', 'OUT');
  wrap('sendFeatureReport', 'FEAT-SET');

  const recv = P.receiveFeatureReport;
  if (recv && !recv.__snf) {
    P.receiveFeatureReport = function (id) { return recv.apply(this, arguments).then(dv => { try { log('FEAT-GET', id, dv); } catch (e) {} return dv; }); };
    P.receiveFeatureReport.__snf = true;
  }

  const addEL = P.addEventListener;
  if (!addEL.__snf) {
    P.addEventListener = function (type, listener, opts) {
      if (type === 'inputreport') addEL.call(this, 'inputreport', (e) => log('IN', e.reportId, e.data), {});
      return addEL.call(this, type, listener, opts);
    };
    P.addEventListener.__snf = true;
  }

  navigator.hid.getDevices().then(ds => ds.forEach(d => { try { d.addEventListener('inputreport', e => log('IN', e.reportId, e.data)); } catch (e) {} }));
  console.log('%cNeo65 sniffer active. Press a key slowly now.', 'color:#0f0;font-weight:bold');
})();
```

## 10. First action for the new session

Do **not** scaffold the whole driver yet. Start by helping Nathan run Phase 0
and paste back the console dump, then decode it together. The capture decides
the architecture details (polled vs streamed, value range), so writing the
reader before the capture is guessing at byte offsets. Confirm the go/no-go gate
result before moving to Phase 1.
