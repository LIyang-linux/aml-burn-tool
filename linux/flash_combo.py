#!/usr/bin/env python3
"""
DDR loader + flash wrapper for Amlogic update tool.
Phase 1: Python uploads DDR + runs BL2 (control transfers, xHCI-safe)
Phase 2: Amlogic update tool flashes partitions (bulk, DDR required)
"""
import sys, os, time, struct, subprocess

os.environ["PYUSB_BACKEND"] = "libusb0"
import usb.core, usb.util

VID = 0x1B8E; PID = 0xC003; BLK = 64
RW = 0x01; RD = 0x02; RR = 0x05
TO = 5000
DDR_LOAD = 0xd9000000
PRM_LOAD = 0xd900c000
UBT_LOAD = 0x0200c000


def log(m, end=True):
    if end: print(f"  {m}", flush=True)
    else:   print(f"\r  {m}", end="", flush=True)


def init():
    for d in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
        try:
            d.set_configuration()
            usb.util.claim_interface(d, 0)
            return d
        except:
            pass
    return None


def upload(dev, addr, data, label=""):
    total = len(data)
    pos = 0
    errors = 0
    t0 = time.time()
    while pos < total:
        chunk = data[pos:pos + BLK]
        a = addr + pos
        try:
            dev.ctrl_transfer(0x40, RW, (a >> 16) & 0xFFFF, a & 0xFFFF, chunk, timeout=TO)
            errors = 0
            pos += BLK
            if pos % (BLK * 50) == 0:
                dev.ctrl_transfer(0xC0, RD, 0, 0, 4, timeout=2000)
        except:
            errors += 1
            if errors > 100:
                log(f"FAIL @ {pos // 1024}KB", False)
                return False
            time.sleep(0.01)
            continue
        if pos % (BLK * 200) == 0:
            el = max(0.01, time.time() - t0)
            log(f"{label}{pos * 100 // total}% {pos / 1024 / el:.0f}KB/s", False)
    el = max(0.01, time.time() - t0)
    log(f"{label}OK {total // 1024}KB {el:.0f}s")
    return True


def run(dev, addr):
    v = addr | 0x10
    dev.ctrl_transfer(0x40, RR, (addr >> 16) & 0xFFFF, addr & 0xFFFF, struct.pack("<I", v), timeout=3000)
    log(f"Jump 0x{addr:08x}")


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    ddr = open(f"{base}/DDR.USB", "rb").read()
    ubt = open(f"{base}/UBOOT.USB", "rb").read()

    print("=" * 55)
    print("  Amlogic Flash — DDR(CTRL) + update(BULK)")
    print("=" * 55)
    log(f"DDR={len(ddr) // 1024}KB  UBOOT={len(ubt) // 1024}KB")

    # Partitions
    bp = f"{base}/boot.PARTITION"
    sp = f"{base}/system.PARTITION"
    has_parts = os.path.isfile(bp) and os.path.isfile(sp)

    # === PHASE 1: Python DDR init ===
    dev = init()
    if not dev:
        log("No device! Enter maskrom mode.")
        sys.exit(1)
    log(f"Device found", False)

    log("\n[Python] Upload DDR...")
    if not upload(dev, DDR_LOAD, ddr, "DDR "):
        sys.exit(1)

    fp = struct.pack("<16I", UBT_LOAD, 0, len(ubt), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    upload(dev, PRM_LOAD, fp, "PRM ")

    log("\n[Python] Run BL2...")
    run(dev, DDR_LOAD)

    # Release Python's USB handle
    try:
        usb.util.dispose_resources(dev)
    except:
        pass

    # === PHASE 2: Amlogic update tool ===
    log("\n[Update] Waiting for device after DDR init...")
    for i in range(30):
        time.sleep(1)
        result = subprocess.run(
            ["update", "identify"],
            capture_output=True, text=True, timeout=5
        )
        if "firmware" in result.stdout.lower():
            log(f"Device ready ({i + 1}s)")
            break
    else:
        log("Device not responding. Try 'update identify' manually.")
        sys.exit(1)

    if has_parts:
        for cmd, file, name in [
            (["update", "partition", "boot", bp], bp, "boot"),
            (["update", "partition", "system", sp], sp, "system"),
        ]:
            mb = os.path.getsize(file) // 1024 // 1024
            log(f"\n[Update] Flashing {name} ({mb}MB)...")
            r = subprocess.run(cmd, capture_output=False, timeout=600)
            if r.returncode != 0:
                log(f"{name} FAIL!", False)

        log("\n[Update] Rebooting...")
        subprocess.run(["update", "bulkcmd", "reset"], timeout=10)
    else:
        log("\nPartition files not found. U-Boot is running — you can flash manually.")
        log("  update partition boot boot.PARTITION")
        log("  update partition system system.PARTITION")

    print("=" * 55)
    log("Done!")
    print("=" * 55)


if __name__ == "__main__":
    main()
