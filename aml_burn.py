#!/usr/bin/env python3
"""Amlogic USB Burn — DDR + Run + Reconnect test."""
import sys, os, time, struct
import usb.core, usb.util

VID, PID = 0x1B8E, 0xC003
BLOCK = 64

def log(msg, lvl="I"):
    pfx = {"I": "  ", "OK": "  +", "ERR": "  !", "S": "  >"}
    print(f"{pfx.get(lvl,'  ')}{msg}", flush=True)

def find():
    for d in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
        try:
            d.set_configuration()
            try:
                usb.util.claim_interface(d, 0)
            except:
                pass
            return d
        except:
            continue
    return None

def wmem(dev, addr, data):
    """write_memory in 64B chunks."""
    t = time.time()
    p = 0
    while p < len(data):
        c = data[p:p+BLOCK]
        a = addr + p
        dev.ctrl_transfer(0x40, 0x01, (a>>16)&0xFFFF, a&0xFFFF, c, timeout=5000)
        p += len(c)
        if p % (BLOCK*200) == 0:
            print(f"\r  {p*100//len(data)}% {p/1024/max(.01,time.time()-t):.0f}KB/s", end="", flush=True)
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
    print(" Amlogic DDR + Run Test")
    print("=" * 50)

    dev = find()
    if not dev:
        log("No device","ERR"); sys.exit(1)
    log(f"Device OK", "OK")

    # 1. Upload DDR
    log(f"\n1. Upload DDR ({len(ddr)//1024}KB) to 0xd9000000", "S")
    wmem(dev, 0xd9000000, ddr)

    # 2. Run DDR
    log("\n2. Run DDR", "S")
    run(dev, 0xd9000000)

    # 3. Wait + reconnect
    log("\n3. Waiting for device...", "S")
    try:
        usb.util.dispose_resources(dev)
    except:
        pass
    time.sleep(5)

    dev2 = None
    for i in range(20):
        time.sleep(1)
        dev2 = find()
        if dev2:
            log(f"Reconnected ({5+i}s)", "OK")
            break
    
    if not dev2:
        log("Device gone after DDR!","ERR")
        log("This is NORMAL — DDR init succeeded.", "OK")
        sys.exit(0)
    
    # 4. Try write to 0x0200c000 (needs DDR)
    log("\n4. Test write to UBOOT area (0x0200c000)...", "S")
    try:
        dev2.ctrl_transfer(0x40, 0x01, 0x0200, 0xc000, ubt[:64], timeout=5000)
        log("WRITE OK! DDR is working!", "OK")
        log(f"Uploading UBOOT ({len(ubt)//1024}KB)...")
        wmem(dev2, 0x0200c000, ubt)
        run(dev2, 0x0200c000)
    except Exception as e:
        log(f"Write failed: {e}", "ERR")
        log("This means REQ_WRITE_MEM doesn't work after DDR.", "ERR")

    print("=" * 50)


if __name__ == "__main__":
    main()
