import os, sys, select, time
DEV = "/dev/hidraw5"

def opf():
    return os.open(DEV, os.O_RDWR | os.O_NONBLOCK)

def send(fd, *first_bytes):
    payload = bytes(first_bytes) + bytes(32 - len(first_bytes))
    os.write(fd, bytes([0x00]) + payload)   # leading 0x00 = report id for unnumbered report

def recv(fd, timeout=0.25):
    r,_,_ = select.select([fd], [], [], timeout)
    if not r: return None
    try: return os.read(fd, 64)
    except BlockingIOError: return None

def depth(b):
    return (b[2] << 8) | b[3]

def drain(fd):
    # discard any buffered/stale replies so the next read lines up with our request
    while True:
        r, _, _ = select.select([fd], [], [], 0)
        if not r:
            return
        try:
            os.read(fd, 64)
        except BlockingIOError:
            return

def xchg(fd, *first_bytes, timeout=0.2):
    # robust request/response: flush stale replies, send, then read until the
    # echoed opcode (reply byte 1) matches what we asked. Fixes the lag/desync
    # seen in a fast scan, where a missed read shifts every later reply.
    op = first_bytes[1]
    drain(fd)
    send(fd, *first_bytes)
    t0 = time.time()
    while time.time() - t0 < timeout:
        rep = recv(fd, timeout)
        if rep and rep[0] == 0xd0 and rep[1] == op:
            return rep
    return None

mode = sys.argv[1] if len(sys.argv) > 1 else "poll"
fd = opf()

if mode == "selftest":
    send(fd, 0xd0, 0xad, 0x00, 0x00)
    rep = recv(fd, 0.5)
    if rep and rep[0]==0xd0 and rep[1]==0xad:
        print("OK write+read works. reply:", " ".join(f"{x:02x}" for x in rep[:6]), "depth=0x%04x"%depth(rep))
    else:
        print("no/unexpected reply:", rep and " ".join(f"{x:02x}" for x in rep[:6]))

elif mode == "poll":
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    print(f"# polling d0 ad 00 00 every 25ms for {dur}s. Press keys now.")
    t0=time.time(); last=None
    while time.time()-t0 < dur:
        send(fd, 0xd0, 0xad, 0x00, 0x00)
        rep = recv(fd, 0.05)
        if rep and rep[0]==0xd0 and rep[1]==0xad:
            d=depth(rep)
            if d != last:
                print(f"{time.time()-t0:6.2f}  0x{d:04x}  {d}")
                last=d
        time.sleep(0.025)

elif mode == "keymap":
    # d0 a6 = paginated LIVE per-key depth map (found via NeoFlux matrix-view sniff).
    # Request: d0 a6 <startIndex> <count>. Reply echoes that header in [0..3], then
    # packs <count> 16-bit BIG-ENDIAN depth values from byte 4 (rest~0x012c, full=0x80e8).
    # These 6 pages cover 80 key slots (0x00..0x4f). Safe: NeoFlux sends this exact read.
    PAGES = [(0x00, 0x0e), (0x0e, 0x0e), (0x1c, 0x0e),
             (0x2a, 0x0e), (0x38, 0x0e), (0x46, 0x0a)]
    NKEYS = 0x50  # 80 slots
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    thr = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x1000

    def a6read(start, cnt, timeout=0.2):
        # match the reply to THIS page: all pages echo d0 a6, so also match
        # the start/count bytes or a stale page reply will be misread.
        drain(fd)
        send(fd, 0xd0, 0xa6, start, cnt)
        t0 = time.time()
        while time.time() - t0 < timeout:
            rep = recv(fd, timeout)
            if rep and rep[0] == 0xd0 and rep[1] == 0xa6 and rep[2] == start and rep[3] == cnt:
                return rep
        return None

    print(f"# keymap: paging d0 a6 live per-key depth ({NKEYS} slots) for {dur}s.")
    print(f"# press keys ONE AT A TIME; indices with depth > 0x{thr:04x} are listed.")
    print("# goal: record which index is W, A, S, D.\n")
    arr = [0] * NKEYS
    seenmax = [0] * NKEYS
    last = None
    t0 = time.time()
    while time.time() - t0 < dur:
        for (start, cnt) in PAGES:
            rep = a6read(start, cnt)
            if not rep:
                continue
            for j in range(cnt):
                idx = start + j
                if idx >= NKEYS:
                    break
                v = (rep[4 + 2 * j] << 8) | rep[4 + 2 * j + 1]
                arr[idx] = v
                if v > seenmax[idx]:
                    seenmax[idx] = v
        hot = tuple((i, arr[i]) for i in range(NKEYS) if arr[i] > thr)
        if hot != last:
            txt = "  ".join(f"#{i}(0x{i:02x})=0x{v:04x}" for i, v in hot) or "(all at rest)"
            print(f"{time.time()-t0:6.2f}  {txt}")
            last = hot
    print("\n# per-key MAX depth seen this run (i.e. the keys you pressed):")
    any_hi = False
    for i in range(NKEYS):
        if seenmax[i] > thr:
            print(f"#  index {i:3d} (0x{i:02x})  max=0x{seenmax[i]:04x}  ({seenmax[i]})")
            any_hi = True
    if not any_hi:
        print("#  (nothing exceeded threshold — lower thr or check the channel)")

elif mode == "scan":
    # test whether byte2 of the d0 ad command selects a key (per-key addressing)
    print("# scanning command 'd0 ad <i> 00' for i=0..63, reading resting reply")
    for i in range(64):
        send(fd, 0xd0, 0xad, i, 0x00)
        rep = recv(fd, 0.1)
        if rep:
            print(f"i={i:3d} (0x{i:02x})  ->  {' '.join('%02x'%x for x in rep[:6])}  depth=0x{depth(rep):04x}")
        time.sleep(0.01)

elif mode == "scanhold":
    # MAKE-OR-BREAK: does byte2 of 'd0 ad' address a specific key?
    # Repeatedly scan i=0..N while the user HOLDS ONE KEY fully pressed.
    #   per-key addressing  -> exactly one index reads high, rest read rest.
    #   no addressing        -> EVERY index returns the same aggregate (all high).
    N = 64
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0
    print(f"# scanhold: scanning 'd0 ad <i> 00' i=0..{N-1} for {dur}s.")
    print("#")
    print("#   >>> PRESS AND HOLD 'W' FULLY DOWN NOW, keep it held until told to stop. <<<")
    print("#")
    for s in (3,2,1):
        print(f"#   starting in {s}..."); time.sleep(1)
    print("# GO — hold W steady.")
    mx = [0]*N; mn = [0xffff]*N; passes = 0
    t0 = time.time()
    while time.time()-t0 < dur:
        for i in range(N):
            send(fd, 0xd0, 0xad, i, 0x00)
            rep = recv(fd, 0.03)
            if rep and rep[0]==0xd0 and rep[1]==0xad:
                d = depth(rep)
                if d > mx[i]: mx[i] = d
                if d < mn[i]: mn[i] = d
        passes += 1
    print(f"# RELEASE W. done: {passes} passes.\n")
    print("idx  max     min     delta(max-min)")
    for i in range(N):
        bar = "#" * min(40, (mx[i]-mn[i])//800)
        print(f"{i:3d}  0x{mx[i]:04x}  0x{mn[i]:04x}  {mx[i]-mn[i]:6d}  {bar}")
    hi = [i for i in range(N) if mx[i] > 0x1000]
    print(f"\n# indices that ever read high (>0x1000): {hi}")
    print("# INTERPRET: one/few high -> per-key addressing WORKS (proceed Phase 2).")
    print("#            all/most high -> no addressing, aggregate only (pivot to bulk opcode).")

elif mode == "guide":
    # Aggregate-behavior test: poll d0 ad 00 00 through a scripted key sequence.
    # Confirms whether the single value tracks max-of-all-pressed (deepest key).
    log = []
    phases = [
        (5.0,  ">>> REST: don't touch any key."),
        (7.0,  ">>> Press & HOLD 'W' to about HALF depth."),
        (6.0,  ">>> Keeping W held, ALSO press & HOLD 'D' FULLY down."),
        (5.0,  ">>> Release D only. Keep W held at half."),
        (5.0,  ">>> Release W. Back to rest."),
    ]
    t0 = time.time(); last = None; pend = list(phases); ptab = []
    base = t0
    for dur_p, msg in phases:
        ptab.append((base - t0, base - t0 + dur_p, msg)); base += dur_p
    print("# guided poll test. Follow the prompts:")
    pi = -1
    while True:
        now = time.time() - t0
        # advance phase
        npi = -1
        for k,(s,e,_m) in enumerate(ptab):
            if s <= now < e: npi = k
        if npi != pi and npi >= 0:
            pi = npi
            print(f"\n[{now:5.1f}s] {ptab[pi][2]}")
        if now >= ptab[-1][1]:
            break
        send(fd, 0xd0, 0xad, 0x00, 0x00)
        rep = recv(fd, 0.05)
        if rep and rep[0]==0xd0 and rep[1]==0xad:
            d = depth(rep)
            if d != last:
                print(f"  {now:6.2f}  0x{d:04x}  {d}")
                last = d
        time.sleep(0.025)
    print("\n# done. Watch: when both W(half)+D(full) held, does value = D-full?")
    print("# and when D released, does it drop back to W-half? -> deepest-key aggregate.")

elif mode == "opcodescan":
    # PIVOT probe. scanhold proved 'd0 ad <i>' ignores the index byte entirely
    # (all 64 channels byte-identical -> single shared aggregate register).
    # Sweep the d0-prefixed command space at rest, hunting for an opcode whose
    # reply carries array-like / multi-byte data = candidate bulk per-key map.
    # NOTE: brute-forcing unknown firmware opcodes is mildly risky (a stray one
    # could be a write/reset/bootloader). Stays in the d0 query namespace; pass
    # start/end (e.g. `opcodescan 0xa0 0xbf`) to narrow if wary.
    lo = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x00
    hi = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0xff
    print(f"# opcodescan: sweeping 'd0 XX 00 00' for XX=0x{lo:02x}..0x{hi:02x} (at rest).")
    print("# uses xchg (flush+echo-match) so each reply is attributed to its true opcode.")
    print("# nz = nonzero payload bytes (beyond opcode echo). >2 flagged as bulk candidate.\n")
    known = {0xb0: "heartbeat", 0xad: "depth(aggregate)", 0xac: "calib-ranges?"}
    for op in range(lo, hi + 1):
        rep = xchg(fd, 0xd0, op, 0x00, 0x00)
        if not rep:
            continue
        nz = sum(1 for x in rep[2:] if x != 0)
        head = " ".join("%02x" % x for x in rep[:16])
        flag = "  <-- BULK?" if nz > 2 else ""
        print(f"op=0x{op:02x} nz={nz:2d} {known.get(op,''):16s}| {head}{flag}")
    print("\n# Reply opcode is now guaranteed == request. Watch promising ops live with")
    print("# 'watch <op>' (press keys) and page them with 'chunk <op>' (byte-2 index).")

elif mode == "watch":
    # Is opcode <op> LIVE (per-key depth) or STATIC (config)? Poll it while you
    # press keys; if the bytes move with key presses it's live, else it's config.
    op = int(sys.argv[2], 0)
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
    print(f"# watch: polling 'd0 {op:02x} 00 00' for {dur}s. PRESS/RELEASE KEYS now.")
    print("# bytes move with presses -> LIVE (maybe per-key). bytes static -> config read.\n")
    last = None
    t0 = time.time()
    while time.time() - t0 < dur:
        rep = xchg(fd, 0xd0, op, 0x00, 0x00)
        if rep:
            h = " ".join("%02x" % x for x in rep[:20])
            if h != last:
                print(f"{time.time()-t0:6.2f}  {h}")
                last = h
        time.sleep(0.02)

elif mode == "chunk":
    # Test hypothesis: byte 2 of opcode <op> is a PAGE/row index into a larger
    # array (a 64-key map can't fit one 32 B report). Read d0 op <i> 00 for
    # i=0..N at rest; if pages differ, the full array is paginated here.
    op = int(sys.argv[2], 0)
    N = int(sys.argv[3], 0) if len(sys.argv) > 3 else 16
    print(f"# chunk: reading 'd0 {op:02x} <i> 00' for i=0..{N-1} at rest.\n")
    seen = {}
    for i in range(N):
        rep = xchg(fd, 0xd0, op, i, 0x00)
        if rep:
            h = " ".join("%02x" % x for x in rep[:20])
            print(f"i={i:3d}  {h}")
            seen[i] = h
    uniq = len(set(seen.values()))
    print(f"\n# {len(seen)} replies, {uniq} distinct. >1 distinct -> byte 2 pages an array (good).")
    print("# all identical -> byte 2 ignored for this opcode too.")

elif mode == "scanhold4":
    # INSURANCE for the per-key question: same hold-W test, but put the index in
    # BYTE 4 instead of byte 2 (request byte meanings need not match the reply's,
    # where byte 2 is the depth hi-byte). If one/few channels read high here, the
    # selector just lives in a different byte and per-key addressing is alive.
    N = 64
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0
    print(f"# scanhold4: scanning 'd0 ad 00 00 <i>' (index in BYTE 4) i=0..{N-1} for {dur}s.")
    print("#\n#   >>> PRESS AND HOLD 'W' FULLY DOWN NOW, keep it held. <<<\n#")
    for s in (3, 2, 1):
        print(f"#   starting in {s}..."); time.sleep(1)
    print("# GO — hold W steady.")
    mx = [0] * N; mn = [0xffff] * N; passes = 0
    t0 = time.time()
    while time.time() - t0 < dur:
        for i in range(N):
            send(fd, 0xd0, 0xad, 0x00, 0x00, i)
            rep = recv(fd, 0.03)
            if rep and rep[0] == 0xd0 and rep[1] == 0xad:
                d = depth(rep)
                if d > mx[i]: mx[i] = d
                if d < mn[i]: mn[i] = d
        passes += 1
    print(f"# RELEASE W. done: {passes} passes.\n")
    print("idx  max     min     delta(max-min)")
    for i in range(N):
        bar = "#" * min(40, (mx[i] - mn[i]) // 800)
        print(f"{i:3d}  0x{mx[i]:04x}  0x{mn[i]:04x}  {mx[i]-mn[i]:6d}  {bar}")
    hi = [i for i in range(N) if mx[i] > 0x1000]
    print(f"\n# indices that ever read high (>0x1000): {hi}")
    print("# one/few high -> byte 4 IS the key selector (per-key WORKS). all high -> byte 4 ignored too.")

os.close(fd)
