#!/usr/bin/env python3
import os, sys, select, time
dev = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw5"
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0
logpath = sys.argv[3] if len(sys.argv) > 3 else os.environ["CLAUDE_JOB_DIR"]+"/tmp/hidraw5_capture.log"
fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
log = open(logpath, "w")
def emit(s):
    print(s); log.write(s+"\n"); log.flush()
emit(f"# capturing {dev} for {dur}s  start={time.strftime('%H:%M:%S')}")
last = None; t0 = time.time(); n = 0
while time.time() - t0 < dur:
    r,_,_ = select.select([fd], [], [], 0.5)
    if not r: continue
    try: data = os.read(fd, 64)
    except BlockingIOError: continue
    if not data: continue
    hexs = " ".join(f"{b:02x}" for b in data)
    n += 1
    if hexs != last:                     # only log when bytes move
        emit(f"{time.time()-t0:7.3f}  len={len(data):2d}  {hexs}")
        last = hexs
emit(f"# done: {n} reports total, log={logpath}")
os.close(fd)
