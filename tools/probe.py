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

elif mode == "scan":
    # test whether byte2 of the d0 ad command selects a key (per-key addressing)
    print("# scanning command 'd0 ad <i> 00' for i=0..63, reading resting reply")
    for i in range(64):
        send(fd, 0xd0, 0xad, i, 0x00)
        rep = recv(fd, 0.1)
        if rep:
            print(f"i={i:3d} (0x{i:02x})  ->  {' '.join('%02x'%x for x in rep[:6])}  depth=0x{depth(rep):04x}")
        time.sleep(0.01)

os.close(fd)
