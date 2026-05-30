#!/usr/bin/env python3
"""Phase 2 reader — live per-key analog depth for W/A/S/D off the Neo65 HE.

Self-contained, no browser needed. Decodes the `d0 a6` paginated per-key depth
map discovered from the NeoFlux sniff (see PROTOCOL.md). Finds the QMK raw-HID
channel by its report-descriptor usage page (0xFF60), so it survives hidraw
renumbering across replugs. Prints normalized depth bars for W/A/S/D in real time.

Usage:  python tools/reader.py [seconds]     (default: run until Ctrl-C)
"""
import os, sys, glob, select, time

VID, PID = 0xE560, 0xEE65            # NEO Neo65 HE, wired
# d0 a6 <startIndex> <count>: paginated 16-bit BIG-ENDIAN per-key depth map.
# WASD indices confirmed 2026-05-30 via probe.py keymap.
KEYS = {"W": 18, "A": 33, "S": 34, "D": 35}
REST, FULL = 0x012c, 0x80e8         # firmware-scaled depth units (rest → bottom-out)

# Full 6-page layout; we only poll the pages that actually carry a wanted key.
PAGES = [(0x00, 0x0e), (0x0e, 0x0e), (0x1c, 0x0e),
         (0x2a, 0x0e), (0x38, 0x0e), (0x46, 0x0a)]


def find_channel():
    """hidraw path whose report descriptor declares Usage Page 0xFF60 (QMK raw HID)."""
    for sysdir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        node = "/dev/" + os.path.basename(sysdir)
        try:
            with open(sysdir + "/device/report_descriptor", "rb") as f:
                desc = f.read()
        except OSError:
            continue
        if b"\x06\x60\xff" in desc:          # Usage Page (Vendor-Defined 0xFF60)
            return node
    return None


def pages_for(indices):
    """Minimal subset of PAGES that covers every wanted key index."""
    return [(s, c) for (s, c) in PAGES if any(s <= i < s + c for i in indices)]


def send(fd, *first):
    payload = bytes(first) + bytes(32 - len(first))
    os.write(fd, bytes([0x00]) + payload)    # leading 0x00 = report id (unnumbered)


def recv(fd, timeout=0.2):
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return None
    try:
        return os.read(fd, 64)
    except BlockingIOError:
        return None


def drain(fd):
    while True:
        r, _, _ = select.select([fd], [], [], 0)
        if not r:
            return
        try:
            os.read(fd, 64)
        except BlockingIOError:
            return


def read_page(fd, start, cnt, timeout=0.2):
    """Send d0 a6 <start> <cnt>; return the reply matching THIS page (all echo a6)."""
    drain(fd)
    send(fd, 0xd0, 0xa6, start, cnt)
    t0 = time.time()
    while time.time() - t0 < timeout:
        rep = recv(fd, timeout)
        if rep and rep[0] == 0xd0 and rep[1] == 0xa6 and rep[2] == start and rep[3] == cnt:
            return rep
    return None


def norm(v):
    return max(0.0, min(1.0, (v - REST) / (FULL - REST)))


def bar(x, width=24):
    n = int(round(x * width))
    return "#" * n + "-" * (width - n)


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else None
    node = find_channel()
    if not node:
        print("ERROR: no hidraw channel with usage page 0xFF60 found. Board plugged in (wired)?",
              file=sys.stderr)
        return 1
    need = pages_for(KEYS.values())
    print(f"# channel: {node}   polling pages {[hex(s) for s, _ in need]} for W/A/S/D")
    print("# press keys; Ctrl-C to stop.\n")
    fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
    names = list(KEYS)
    t0 = time.time()
    try:
        while dur is None or time.time() - t0 < dur:
            depth = {}
            for (start, cnt) in need:
                rep = read_page(fd, start, cnt)
                if not rep:
                    continue
                for name, idx in KEYS.items():
                    if start <= idx < start + cnt:
                        j = idx - start
                        depth[name] = (rep[4 + 2 * j] << 8) | rep[4 + 2 * j + 1]
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
