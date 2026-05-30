#!/usr/bin/env python3
"""Phase 3 — Neo65 HE analog key depth -> virtual gamepad left stick (Linux).

Presents an Xbox-style virtual pad via the kernel uinput device (pure ctypes/
ioctl, no third-party deps) and drives its left-stick ABS_X / ABS_Y from the
analog press depth of W/A/S/D:

    X = curve(D) - curve(A)        (right positive)
    Y = curve(S) - curve(W)        (down positive, screen convention)

Opposing keys cancel (subtractive SOCD) — push both A+D and you get neutral.

SAFETY: depth comes from neo_core, which only issues the confirmed-safe READ
opcode `d0 a6`. Nothing here writes to the keyboard.

Usage:
    python tools/gamepad.py            # run until Ctrl-C
    python tools/gamepad.py --monitor  # also print live axis values
    python tools/gamepad.py --expo 0.4 # add mild expo (0 = linear, default)
    python tools/gamepad.py --deadzone 0.06
Needs write access to /dev/uinput (root, or membership in a group with an ACL
on the node — the `input` group here already has it).
"""
import os, sys, time, struct, fcntl, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from neo_core import KEYS, open_channel, read_depths, norm

# ---- uinput / input-subsystem constants (linux/uinput.h, linux/input-event-codes.h)
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0x00
ABS_X, ABS_Y, ABS_Z = 0x00, 0x01, 0x02
ABS_RX, ABS_RY, ABS_RZ = 0x03, 0x04, 0x05
BTN_A = 0x130                       # BTN_GAMEPAD; presence makes joydev classify us a pad
BUS_USB = 0x03
UINPUT_MAX_NAME_SIZE = 80

# _IOC bit layout (asm-generic): dir<<30 | size<<16 | type<<8 | nr
def _IOC(d, t, nr, size):
    return (d << 30) | (size << 16) | (ord(t) << 8) | nr

UI_DEV_CREATE  = _IOC(0, 'U', 1, 0)
UI_DEV_DESTROY = _IOC(0, 'U', 2, 0)
UI_DEV_SETUP   = _IOC(1, 'U', 3, 92)    # sizeof(struct uinput_setup)
UI_ABS_SETUP   = _IOC(1, 'U', 4, 28)    # sizeof(struct uinput_abs_setup)
UI_SET_EVBIT   = _IOC(1, 'U', 100, 4)
UI_SET_KEYBIT  = _IOC(1, 'U', 101, 4)
UI_SET_ABSBIT  = _IOC(1, 'U', 103, 4)

AXIS_MIN, AXIS_MAX = -32768, 32767


class VirtualPad:
    """Minimal uinput Xbox-style pad. Drives left stick (ABS_X/Y); declares the
    full 360 axis+button set so it enumerates as a gamepad, leaving the rest at 0."""

    def __init__(self, name="Neo65 HE Analog Pad"):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        # Enable event types.
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
        # A gamepad button set so the kernel/joydev treats us as a controller.
        for btn in range(BTN_A, BTN_A + 11):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, btn)
        # Declare the standard 360 axes; configure each absinfo.
        for axis in (ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ):
            fcntl.ioctl(self.fd, UI_SET_ABSBIT, axis)
            self._abs_setup(axis, AXIS_MIN, AXIS_MAX)
        # uinput_setup: struct input_id{u16 bus,vendor,product,version}; char name[80]; u32 ff_max
        setup = struct.pack("HHHH", BUS_USB, 0xE560, 0xEE65, 1)
        setup += name.encode().ljust(UINPUT_MAX_NAME_SIZE, b"\x00")[:UINPUT_MAX_NAME_SIZE]
        setup += struct.pack("I", 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.2)             # let udev settle / device node appear

    def _abs_setup(self, code, mn, mx):
        # struct uinput_abs_setup { u16 code; struct input_absinfo absinfo; }
        # input_absinfo = s32 value,minimum,maximum,fuzz,flat,resolution
        absinfo = struct.pack("iiiiii", 0, mn, mx, 0, 0, 0)
        buf = struct.pack("H", code) + b"\x00\x00" + absinfo   # 2-byte pad to align s32
        fcntl.ioctl(self.fd, UI_ABS_SETUP, buf)

    def _emit(self, etype, code, value):
        # struct input_event { struct timeval(2x s64) time; u16 type; u16 code; s32 value; }
        os.write(self.fd, struct.pack("qqHHi", 0, 0, etype, code, value))

    def set_left_stick(self, x, y):
        """x, y in [-1.0, 1.0]."""
        self._emit(EV_ABS, ABS_X, int(round(x * AXIS_MAX if x >= 0 else -x * AXIS_MIN)))
        self._emit(EV_ABS, ABS_Y, int(round(y * AXIS_MAX if y >= 0 else -y * AXIS_MIN)))
        self._emit(EV_SYN, SYN_REPORT, 0)

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        finally:
            os.close(self.fd)


def shape(v, deadzone, expo):
    """Normalized depth (0..1) -> shaped magnitude (0..1) with rest deadzone + expo."""
    if v <= deadzone:
        return 0.0
    v = (v - deadzone) / (1.0 - deadzone)        # rescale so just past deadzone starts at 0
    if expo > 0.0:
        v = (1.0 - expo) * v + expo * v ** 3     # mild cubic blend
    return v


def main():
    ap = argparse.ArgumentParser(description="Neo65 HE depth -> virtual gamepad stick")
    ap.add_argument("--deadzone", type=float, default=0.05, help="rest deadzone (0..1)")
    ap.add_argument("--expo", type=float, default=0.0, help="expo blend 0=linear..1=full cubic")
    ap.add_argument("--monitor", action="store_true", help="print live axis values")
    ap.add_argument("--rate", type=float, default=200.0, help="target poll rate (Hz)")
    args = ap.parse_args()

    fd, node = open_channel()
    if not fd:
        print("ERROR: no hidraw channel (usage page 0xFF60). Board plugged in (wired)?",
              file=sys.stderr)
        return 1
    try:
        pad = VirtualPad()
    except PermissionError:
        print("ERROR: cannot open /dev/uinput (need root or an ACL/group on the node).",
              file=sys.stderr)
        os.close(fd)
        return 1

    print(f"# keyboard channel: {node}")
    print(f"# virtual pad created: 'Neo65 HE Analog Pad' (left stick = WASD depth)")
    print(f"# deadzone={args.deadzone} expo={args.expo} rate={args.rate:.0f}Hz")
    print("# press W/A/S/D; Ctrl-C to stop.\n")

    held = {k: 0 for k in KEYS}             # last raw depth per key (hold across dropped frames)
    period = 1.0 / max(1.0, args.rate)
    try:
        while True:
            t0 = time.time()
            held.update(read_depths(fd))    # only updates keys whose page replied
            w, a, s, d = (shape(norm(held[k]), args.deadzone, args.expo)
                          for k in ("W", "A", "S", "D"))
            x = max(-1.0, min(1.0, d - a))
            y = max(-1.0, min(1.0, s - w))
            pad.set_left_stick(x, y)
            if args.monitor:
                sys.stdout.write(f"\rX:{x:+5.2f}  Y:{y:+5.2f}   "
                                 f"W:{w:.2f} A:{a:.2f} S:{s:.2f} D:{d:.2f}   ")
                sys.stdout.flush()
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)
    except KeyboardInterrupt:
        pass
    finally:
        pad.set_left_stick(0.0, 0.0)        # recenter before tearing down
        pad.close()
        os.close(fd)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
