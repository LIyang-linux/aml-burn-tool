#!/usr/bin/env python3
"""Amlogic USB Burn — DDR + Run Test with libusb0 backend."""
import sys, os, time, struct
import usb.core, usb.util
import usb.backend.libusb0

VID, PID = 0x1B8E, 0xC003
BLOCK = 64
BE = usb.backend.libusb0.get_backend()

def log(msg, lvl="I"):
    pfx = {"I":"  ","OK":"  +","ERR":"  !","S":"  >"}
    print(f"{pfx.get(lvl,'  ')}{msg}", flush=True)

def find():
    for d in usb.core.find(find_all=True, backend=BE, idVendor=VID, idProduct=PID):
        try:
            d.set_configuration()
            try: usb.util.claim_interface(d, 0)
            except: pass
            return d
        except: continue
    return None

def wmem(dev, addr, data):
    t = time.time()
    p = 0
    errors = 0
    while p < len(data):
        c = data[p:p+BLOCK]
        a = addr + p
        try:
            dev.ctrl_transfer(0x40, 0x01, (a>>16)&0xFFFF, a&0xFFFF, c, timeout=5000)
            errors = 0
            p += len(c)
            time.sleep(0.001)
        except Exception as e:
            errors += 1
            if errors > 20:
                log(f"Failed at {p//1024}KB: {e}", "ERR")
                return False
            time.sleep(0.1)
            try:
                dev.set_configuration()
                usb.util.claim_interface(dev, 0)
            except: pass
        if p % (BLOCK*100) == 0:
            print(f"\r  {p*100//len(data)}%", end="", flush=True)
    print(f"\r  100% ({len(data)//1024}KB, {time.time()-t:.0f}s)")
    return True

def run(dev, addr):
    d = struct.pack("<I", addr | 0x10)
    dev.ctrl_transfer(0x40, 0x05, (addr>>16)&0xFFFF, addr&0xFFFF, d, timeout=3000)
    log(f"Run at 0x{addr:08x}", "OK")

def main():
    img = sys.argv[1] if len(sys.argv) > 1 else "."
    with open(os.path.join(img,"DDR.USB"),"rb") as f: ddr = f.read()
    with open(os.path.join(img,"UBOOT.USB"),"rb") as f: ubt = f.read()

    print("=" * 50)
    print(" Amlogic DDR + Run Test [libusb0]")
    print("=" * 50)

    dev = find()
    if not dev: log("No device","ERR"); sys.exit(1)
    log(f"Device OK (backend={dev.backend.__class__.__name__})", "OK")

    # 1. Upload DDR
    log(f"\n1. Upload DDR ({len(ddr)//1024}KB)", "S")
    wmem(dev, 0xd9000000, ddr)

    # 2. Run DDR
    log("\n2. Run DDR", "S")
    run(dev, 0xd9000000)

    # 3. Reconnect
    log("\n3. Reconnecting...", "S")
    try: usb.util.dispose_resources(dev)
    except: pass
    time.sleep(5)
    dev2 = None
    for i in range(20):
        time.sleep(1)
        dev2 = find()
        if dev2:
            log(f"OK ({5+i}s, backend={dev2.backend.__class__.__name__})", "OK")
            break
    if not dev2:
        log("Device gone (DDR init OK!)", "OK")
        sys.exit(0)

    # 4. Test UBOOT write
    log("\n4. UBOOT to 0x0200c000", "S")
    try:
        dev2.ctrl_transfer(0x40, 0x01, 0x0200, 0xc000, ubt[:64], timeout=5000)
        log("Probe OK!", "OK")
        wmem(dev2, 0x0200c000, ubt)
        run(dev2, 0x0200c000)
        log("All done!", "OK")
    except Exception as e:
        log(f"Write failed: {e}", "ERR")

    print("=" * 50)

if __name__ == "__main__":
    main()
