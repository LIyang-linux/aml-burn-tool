#!/usr/bin/env python3
"""
Minimal DDR init via USB control transfer. Called by flash.sh.
Uploads DDR + params + runs BL2, then exits.
"""
import sys, os, time, struct

os.environ["PYUSB_BACKEND"] = "libusb0"
import usb.core, usb.util

VID = 0x1B8E; PID = 0xC003; BLK = 64
RW = 0x01; RD = 0x02; RR = 0x05; TO = 5000
DDR_LOAD = 0xd9000000
PRM_LOAD = 0xd900c000
UBT_LOAD = 0x0200c000


def upload(dev, addr, data):
    total = len(data); pos = 0; t0 = time.time()
    while pos < total:
        chunk = data[pos:pos + BLK]
        try:
            dev.ctrl_transfer(0x40, RW, ((addr + pos) >> 16) & 0xFFFF, (addr + pos) & 0xFFFF, chunk, timeout=TO)
            pos += BLK
            if pos % (BLK * 50) == 0:
                dev.ctrl_transfer(0xC0, RD, 0, 0, 4, timeout=2000)
        except:
            time.sleep(0.01)
        if pos % (BLK * 100) == 0:
            print(f"  {pos * 100 // total}%", flush=True)
    print(f"  OK ({total // 1024}KB, {time.time() - t0:.0f}s)", flush=True)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    ddr = open(f"{d}/DDR.USB", "rb").read()
    ubt = open(f"{d}/UBOOT.USB", "rb").read()

    dev = None
    for x in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
        try: x.set_configuration(); usb.util.claim_interface(x, 0); dev = x; break
        except: pass
    if not dev:
        print("No device", flush=True); sys.exit(1)

    print(f"[DDR] Upload {len(ddr)//1024}KB...", flush=True)
    upload(dev, DDR_LOAD, ddr)

    fp = struct.pack("<16I", UBT_LOAD, 0, len(ubt), 0,0,0,0,0,0,0,0,0,0,0,0,0)
    print(f"[DDR] Write params...", flush=True)
    upload(dev, PRM_LOAD, fp)

    print(f"[DDR] Run BL2...", flush=True)
    dev.ctrl_transfer(0x40, RR, (DDR_LOAD>>16)&0xFFFF, DDR_LOAD&0xFFFF, struct.pack("<I", DDR_LOAD|0x10), timeout=3000)

    try: usb.util.dispose_resources(dev)
    except: pass
    print("[DDR] Done!", flush=True)


if __name__ == "__main__":
    main()
