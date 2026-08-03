#!/usr/bin/env python3
"""
Windows Amlogic Flash Tool — Complete Python-only solution.
No USB Burning Tool needed. No libusb conflicts.
Control transfer for DDR/BL2, then U-Boot bulkcmd for partition writes.
"""
import sys, os, time, struct

os.environ["PYUSB_BACKEND"] = "libusb0"
import usb.core, usb.util

VID_ROM = 0x1B8E; PID_ROM = 0xC003   # Boot ROM
VID_UBT = 0x1B8E; PID_UBT = 0xC004   # U-Boot (after BL2)
BLK = 64; RW = 0x01; RD = 0x02; RR = 0x05; TO = 5000
DDR_LOAD = 0xd9000000; DDR_RUN = 0xd9000030
PRM_LOAD = 0xd900c000

def log(m, end=True):
    if end: print(f"  {m}", flush=True)
    else:   print(f"\r  {m}", end="", flush=True)

def find(vid, pid):
    for d in usb.core.find(find_all=True, idVendor=vid, idProduct=pid):
        try: d.set_configuration(); usb.util.claim_interface(d, 0); return d
        except: pass
    return None

def write_mem(dev, addr, data, label=""):
    total = len(data); pos = 0; t0 = time.time()
    while pos < total:
        a = addr + pos; c = data[pos:pos+BLK]
        try: dev.ctrl_transfer(0x40, RW, (a>>16)&0xFFFF, a&0xFFFF, c, timeout=TO)
        except: time.sleep(0.01); continue
        pos += BLK
        if pos % (BLK*200) == 0:
            el = max(0.01, time.time()-t0)
            log(f"{label}{pos*100//total}% {pos/1024/el:.0f}KB/s", False)
    el = max(0.01, time.time()-t0)
    log(f"{label}OK {total//1024}KB {el:.0f}s")
    return True

def bulkcmd(dev, cmd):
    """Send command to U-Boot via TPL."""
    c = (cmd.encode() + b'\x00')[:128]
    try: dev.ctrl_transfer(0x40, 0x34, 0, 0, c, timeout=10000)
    except: pass
    try: return bytes(dev.read(0x81, 512, timeout=5000)).decode(errors='ignore')
    except: return ""

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    ddr = open(f"{base}/DDR.USB","rb").read()
    ubt = open(f"{base}/UBOOT.USB","rb").read()

    print("="*55+"\n  Amlogic Flash — Windows Python\n"+"="*55)
    log(f"DDR={len(ddr)//1024}KB UBOOT={len(ubt)//1024}KB")

    # === Phase 1: Boot ROM — upload DDR + UBOOT ===
    dev = find(VID_ROM, PID_ROM)
    if not dev: log("No device! Enter USB download mode."); sys.exit(1)
    log("ROM ready")

    # Upload DDR to 0xd9000000
    log("\n[ROM] Upload DDR...")
    write_mem(dev, DDR_LOAD, ddr, "DDR ")

    # Upload UBOOT to 0x10000000 (follows DDR in memory)
    log("\n[ROM] Upload UBOOT...")
    write_mem(dev, 0x10000000, ubt, "UBT ")

    # Build FIP params  
    fp = struct.pack("<16I", 0x10000000, 0, len(ubt), 0,0,0,0,0,0,0,0,0,0,0,0,0)
    write_mem(dev, PRM_LOAD, fp, "PRM ")

    # Run BL2
    log("\n[ROM] Run BL2...")
    dev.ctrl_transfer(0x40, RR, (DDR_LOAD>>16)&0xFFFF, DDR_LOAD&0xFFFF,
                      struct.pack("<I", DDR_LOAD|0x10), timeout=3000)
    try: usb.util.dispose_resources(dev)
    except: pass

    # === Phase 2: Wait for U-Boot ===
    log("\n[UBT] Waiting...")
    for i in range(30):
        time.sleep(2)
        d2 = find(VID_UBT, PID_UBT)
        if d2:
            log(f"U-Boot ready ({i*2}s)", False)
            dev = d2
            break

    if not dev:
        # Try ROM VID too (some U-Boot versions don't change PID)
        log("Trying ROM PID...")
        d2 = find(VID_ROM, PID_ROM)
        if d2:
            dev = d2
            log("Reconnected (ROM PID)")
        else:
            log("U-Boot not found!"); sys.exit(1)

    # === Phase 3: Flash partitions ===
    log("\n[UBT] Flashing...")
    for name, file in [("boot", "boot.PARTITION"), ("system", "system.PARTITION")]:
        path = os.path.join(base, file)
        if not os.path.isfile(path):
            log(f"Skip {name} — not found")
            continue
        mb = os.path.getsize(path)//1024//1024
        log(f"{name} ({mb}MB)... ", False)
        r = bulkcmd(dev, f"store erase {name}")
        r = bulkcmd(dev, f"download store {name} normal {os.path.getsize(path)}")
        # Send raw data via bulk
        with open(path, "rb") as f:
            data = f.read()
        p = 0
        while p < len(data):
            c = data[p:p+512*1024]
            try: dev.write(0x02, c, timeout=30000)
            except: time.sleep(0.1); continue
            p += len(c)
            if p % (512*1024*10) == 0:
                log(f"{p*100//len(data)}%", False)
        r = bulkcmd(dev, "save")
        log("OK")

    # === Done ===
    log("\nRebooting...")
    try: bulkcmd(dev, "reset")
    except: pass
    log("Done! Power cycle.")
    print("="*55)

if __name__ == "__main__":
    main()
