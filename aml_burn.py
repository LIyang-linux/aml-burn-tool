#!/usr/bin/env python3
"""
Amlogic USB Burn — Full GXL Protocol
Based on pyamlboot analysis:
  1. ROM stage: WRITE_MEM → DDR_LOAD, WRITE_MEM → BL2_PARAMS, RUN(DDR_LOAD)
  2. BL2 stage: identify stage=8
  3. WR_LARGE_MEM + BULK → UBOOT_LOAD, RUN(BL2_PARAMS)

Force libusb0: restart with env var if libusb1 is active.
"""
import sys, os, time, struct, subprocess

# ---- Force libusb0 ----
if "PYUSB_FORCED" not in os.environ:
    os.environ["PYUSB_FORCED"] = "1"
    os.environ["PYUSB_BACKEND"] = "libusb0"
    # Re-exec with forced env
    python = sys.executable
    args = [python] + sys.argv
    os.execv(python, args)
    sys.exit(0)

import usb.core, usb.util

# ---- Constants ----
VID = 0x1B8E
PID = 0xC003
BLK = 64
REQ_WRITE   = 0x01
REQ_READ    = 0x02
REQ_RUN     = 0x05
REQ_W_LARGE = 0x11
REQ_ID      = 0x20
KEEP_POWER  = 0x10
TIMEOUT     = 5000
SLOW_TO     = 15000  # longer timeout for big transfers

DDR_LOAD   = 0xd9000000
DDR_PRMS   = 0xd900c000
UBT_LOAD   = 0x0200c000


# ---- Helpers ----
def L(msg): print(f"  {msg}", flush=True)

def H(msg): print(f"\n{'='*55}\n  {msg}\n{'='*55}", flush=True)

def find_device():
    for d in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
        try:
            d.set_configuration()
            usb.util.claim_interface(d, 0)
            return d
        except Exception:
            continue
    return None

def identify(dev):
    try:
        raw = bytes(dev.ctrl_transfer(0xC0, REQ_ID, 0, 0, 8, timeout=3000))
        stage = raw[3] if len(raw) > 3 else -1
        name = {0: "ROM", 8: "BL2/SPL", 16: "TPL/U-Boot"}.get(stage, f"unknown({stage})")
        L(f"Chip stage: {name}")
        return stage
    except Exception:
        return -1

def write_chunk(dev, addr, chunk):
    """One 64-byte REQ_WRITE_MEM."""
    hi, lo = (addr >> 16) & 0xFFFF, addr & 0xFFFF
    dev.ctrl_transfer(0x40, REQ_WRITE, hi, lo, chunk, timeout=TIMEOUT)

def write_mem(dev, addr, data, label=""):
    """Write memory 64B at a time. Assumes device stays connected."""
    total = len(data)
    pos = 0
    errs = 0
    t0 = time.time()
    while pos < total:
        a = addr + pos
        piece = data[pos:pos + BLK]
        try:
            write_chunk(dev, a, piece)
            errs = 0
            pos += BLK
        except Exception as e:
            errs += 1
            if errs > 30:
                L(f"FAILED at {pos//1024}KB after {errs} retries: {e}")
                return False
            time.sleep(0.05)
        # Progress every 400 chunks (~25KB)
        if pos % (BLK * 400) == 0:
            pct = pos * 100 // total
            elap = max(0.01, time.time() - t0)
            kbps = pos / 1024 / elap
            eta_s = (total - pos) / 64 / max(1, kbps)
            print(f"\r  {label}{pct}%  {kbps:.0f}KB/s  ~{eta_s:.0f}s", end="", flush=True)
    elap = time.time() - t0
    L(f"{label}OK  {total//1024}KB  {elap:.0f}s  {total/1024/elap:.0f}KB/s")
    return True

def write_large(dev, addr, data, blen=64):
    """REQ_WR_LARGE_MEM (0x11) + BULK OUT. Falls back to write_mem."""
    total = len(data)
    # Pad
    bcount = (total + blen - 1) // blen
    padded = data + b'\x00' * (bcount * blen - total)
    # Setup
    ctrl = struct.pack('<IIII', addr, total, 0, 0)
    dev.ctrl_transfer(0x40, REQ_W_LARGE, blen, bcount, ctrl, timeout=TIMEOUT)
    L(f"  BULK {bcount}×{blen}B ({total//1024}KB)")
    off = 0
    t0 = time.time()
    for i in range(bcount):
        try:
            dev.write(0x02, padded[off:off + blen], timeout=SLOW_TO)
            off += blen
        except Exception as e:
            L(f"  Bulk failed @ block {i}: {e}")
            L("  Fallback to REQ_WRITE_MEM...")
            return write_mem(dev, addr, data)
        if i % 200 == 0:
            print(f"\r  {i*100//bcount}%", end="", flush=True)
    L(f"  OK {time.time()-t0:.0f}s")
    return True

def run_addr(dev, addr):
    val = addr | KEEP_POWER
    ctrl = struct.pack('<I', val)
    dev.ctrl_transfer(0x40, REQ_RUN, (addr>>16)&0xFFFF, addr&0xFFFF, ctrl, timeout=3000)
    L(f"Jump 0x{addr:08x}")


# ---- Main ----
def main():
    H("Amlogic GXL Boot — Full Protocol")
    
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    ddr = open(os.path.join(base, "DDR.USB"), "rb").read()
    ubt = open(os.path.join(base, "UBOOT.USB"), "rb").read()
    L(f"DDR={len(ddr)//1024}KB  UBOOT={len(ubt)//1024}KB")

    # ---- Connect ----
    L("Connecting...")
    dev = find_device()
    if not dev:
        L("ERROR: device not found")
        sys.exit(1)
    bk = dev.backend.__class__.__name__
    L(f"OK  (backend: {bk})")

    # ---- ROM stage ----
    s0 = identify(dev)
    if s0 != 0:
        L(f"WARNING: expected ROM stage=0, got {s0}")

    # Step 1: Upload BL2 (DDR)
    L(f"\n[1/4] BL2 -> 0x{DDR_LOAD:08x}")
    write_mem(dev, DDR_LOAD, ddr, "BL2 ")

    # Step 2: DDR init params
    L(f"\n[2/4] DDR params -> 0x{DDR_PRMS:08x}")
    # Minimal params: just chain to U-Boot
    params = struct.pack('<16I',
        UBT_LOAD,           # u-boot load address
        0,                  # entry point (0 = use default)
        len(ubt),           # u-boot size
        0,0,0,0,0,          # reserved
        0,0,0,0,0,0,0,0     # reserved
    )
    write_mem(dev, DDR_PRMS, params, "PARAMS ")

    # Step 3: Run BL2 to init DDR
    L(f"\n[3/4] Run BL2 (DDR init)...")
    run_addr(dev, DDR_LOAD)      # Jump with KEEP_POWER
    time.sleep(3)

    # Step 4: BL2 stage — upload UBOOT
    s1 = identify(dev)
    L(f"Stage after DDR: {s1}")

    L(f"\n[4/4] UBOOT -> 0x{UBT_LOAD:08x}")
    L("Trying REQ_WR_LARGE_MEM + BULK...")
    ok = write_large(dev, UBT_LOAD, ubt, blen=64)
    if not ok:
        L("UBOOT upload FAILED", file=sys.stderr)
        sys.exit(1)

    # Step 5: Execute FIP chain
    L(f"\n[Boot] Running FIP chain at 0x{DDR_PRMS:08x}...")
    run_addr(dev, DDR_PRMS)

    L("\nDone. U-Boot should be running.")
    H("SUCCESS")


if __name__ == "__main__":
    main()
