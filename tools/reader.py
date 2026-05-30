#!/usr/bin/env python3
"""Phase 2 reader — live per-key analog depth for W/A/S/D off the Neo65 HE.

Self-contained, no browser needed. Decodes the `d0 a6` paginated per-key depth
map (see PROTOCOL.md / neo_core.py). Finds the QMK raw-HID channel by its
report-descriptor usage page (0xFF60), so it survives hidraw renumbering across
replugs. Prints normalized depth bars for W/A/S/D in real time.

Usage:  python tools/reader.py [seconds]     (default: run until Ctrl-C)
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from neo_core import KEYS, open_channel, pages_for, read_depths, norm


def bar(x, width=24):
    n = int(round(x * width))
    return "#" * n + "-" * (width - n)


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else None
    fd, node = open_channel()
    if not fd:
        print("ERROR: no hidraw channel with usage page 0xFF60 found. Board plugged in (wired)?",
              file=sys.stderr)
        return 1
    need = pages_for(KEYS.values())
    print(f"# channel: {node}   polling pages {[hex(s) for s, _ in need]} for W/A/S/D")
    print("# press keys; Ctrl-C to stop.\n")
    names = list(KEYS)
    t0 = time.time()
    try:
        while dur is None or time.time() - t0 < dur:
            depth = read_depths(fd)
            line = "  ".join(
                f"{n}:{bar(norm(depth.get(n, 0)),12)} {norm(depth.get(n,0)):4.2f}"
                for n in names
            )
            sys.stdout.write("\r" + line)
            sys.stdout.flush()
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        os.close(fd)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
