#!/usr/bin/env python3
"""Shared core for the Neo65 HE analog channel (QMK raw HID, usage page 0xFF60).

Decodes the paginated `d0 a6` per-key depth map discovered from the NeoFlux
sniff (see PROTOCOL.md). Channel is found by report-descriptor usage page so it
survives hidraw renumbering across replugs.

SAFETY (HANDOFF.md rule): the only opcode issued here is the confirmed-safe READ
`d0 a6`. Never add a blind write of an unobserved `d0 XX` opcode — that once
corrupted live key config.
"""
import os, glob, select, time

VID, PID = 0xE560, 0xEE65            # NEO Neo65 HE, wired
# d0 a6 <startIndex> <count>: paginated 16-bit BIG-ENDIAN per-key depth map.
# WASD indices confirmed 2026-05-30 via probe.py keymap.
KEYS = {"W": 18, "A": 33, "S": 34, "D": 35}
REST, FULL = 0x012c, 0x80e8          # firmware-scaled depth units (rest -> bottom-out)

# Full 6-page layout; callers poll only the pages that carry a wanted key.
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


def open_channel():
    """Open the analog channel non-blocking. Returns (fd, node) or (None, None)."""
    node = find_channel()
    if not node:
        return None, None
    return os.open(node, os.O_RDWR | os.O_NONBLOCK), node


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


def read_depths(fd, keys=KEYS):
    """Poll the minimal page set and return {name: raw_depth} for `keys`.

    Missing keys (no page reply this frame) are simply absent from the dict;
    callers should treat absence as 'hold previous' or REST, per their needs.
    """
    depth = {}
    for (start, cnt) in pages_for(keys.values()):
        rep = read_page(fd, start, cnt)
        if not rep:
            continue
        for name, idx in keys.items():
            if start <= idx < start + cnt:
                j = idx - start
                depth[name] = (rep[4 + 2 * j] << 8) | rep[4 + 2 * j + 1]
    return depth


def norm(v):
    """Raw firmware depth -> 0.0 (rest) .. 1.0 (bottom-out)."""
    return max(0.0, min(1.0, (v - REST) / (FULL - REST)))
