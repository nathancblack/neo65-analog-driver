#!/usr/bin/env python3
"""Tiny OS-level gamepad axis monitor (no evtest/jstest needed).

Finds the virtual pad's kernel event node by name and prints live ABS_X/ABS_Y
as the *kernel* sees them — independent of gamepad.py's own math, so it's a true
end-to-end check. Run `python tools/gamepad.py` in one terminal and this in
another, then press W/A/S/D.

Usage:  python tools/jsmon.py ["Device Name substring"]   (default: "Analog Pad")

NB: the physical keyboard exposes several nodes named "NEO Neo65 HE ..." which
emit no ABS axes — so match the virtual pad's distinctive "Analog Pad", not
"Neo65", or you'll watch the wrong device and see nothing move.
"""
import os, sys, glob, struct, select

NAME = sys.argv[1] if len(sys.argv) > 1 else "Analog Pad"
EV_ABS = 0x03
ABS_X, ABS_Y = 0x00, 0x01
EVFMT = "qqHHi"
EVSIZE = struct.calcsize(EVFMT)


def find_event_node(substr):
    for d in glob.glob("/sys/class/input/event*"):
        try:
            with open(os.path.join(d, "device", "name")) as f:
                if substr.lower() in f.read().strip().lower():
                    return "/dev/input/" + os.path.basename(d)
        except OSError:
            pass
    return None


def bar(v):                                  # v in -32768..32767 -> centered 41-char bar
    half = 20
    n = int(round(v / 32768 * half))
    cells = ["-"] * (2 * half + 1)
    cells[half] = "|"
    cells[max(0, min(2 * half, half + n))] = "#"
    return "".join(cells)


def main():
    node = find_event_node(NAME)
    if not node:
        print(f"ERROR: no input device matching '{NAME}'. Is gamepad.py running?",
              file=sys.stderr)
        return 1
    print(f"# monitoring {node}  (match '{NAME}')   Ctrl-C to stop")
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    x = y = 0
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 1.0)
            if not r:
                continue
            data = os.read(fd, EVSIZE * 64)
            for i in range(0, len(data), EVSIZE):
                _, _, etype, code, value = struct.unpack(EVFMT, data[i:i + EVSIZE])
                if etype == EV_ABS and code == ABS_X:
                    x = value
                elif etype == EV_ABS and code == ABS_Y:
                    y = value
            sys.stdout.write(f"\rX[{bar(x)}]{x:+6d}   Y[{bar(y)}]{y:+6d} ")
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        os.close(fd)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
