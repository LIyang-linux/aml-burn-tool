#!/usr/bin/env python3
"""Amlogic USB Burn — xHCI workaround with control transfers."""
import sys, os, time
import usb.core

AML_VID, AML_PID = 0x1B8E, 0xC003
TIMEOUT = 8000
MAX_PACKET = 64


def find():
    for d in usb.core.find(find_all=True, idVendor=AML_VID, idProduct=AML_PID):
        try:
            d.set_configuration()
        except:
            pass
        return d
    return None


def upload_small(dev, path, name):
    size = os.path.getsize(path)
    packets = size // MAX_PACKET
    print(f"  Uploading {name} ({size//1024}KB, {packets} packets)...")

    with open(path, "rb") as f:
        data = f.read()

    sent = 0
    errors = 0
    while sent < len(data):
        chunk = data[sent:sent + MAX_PACKET]
        try:
            dev.ctrl_transfer(0x40, 0xA0, sent & 0xFFFF, (sent >> 16) & 0xFFFF,
                             chunk, timeout=TIMEOUT)
            sent += len(chunk)
            errors = 0
            if sent % (MAX_PACKET * 1000) == 0:
                print(f"\r  {sent//1024}/{size//1024}KB", end="")
        except usb.core.USBError:
            errors += 1
            if errors > 10:
                print(f"\n  FAILED at {sent//1024}KB")
                return False
            time.sleep(0.01)

    print(f"\r  {name} OK ({size//1024}KB)     ")
    return True


def write_raw(dev, path, name):
    size = os.path.getsize(path)
    mb = size // 1024 // 1024
    print(f"  Writing {name} ({mb}MB)...")

    with open(path, "rb") as f:
        data = f.read()

    sent = 0
    while sent < len(data):
        chunk = data[sent:sent + MAX_PACKET]
        dev.ctrl_transfer(0x40, 0xA1, sent & 0xFFFF, (sent >> 16) & 0xFFFF,
                         chunk, timeout=TIMEOUT)
        sent += len(chunk)
        if sent % (MAX_PACKET * 50000) == 0:
            pct = sent * 100 // len(data)
            print(f"\r  {name}: {pct}% ({sent//1024//1024}MB/{mb}MB)", end="")

    print(f"\r  {name}: 100% done!   ")


def main():
    if len(sys.argv) < 2:
        print("Usage: python aml_burn.py <dir>")
        sys.exit(1)

    d = sys.argv[1]
    ddr = os.path.join(d, "DDR.USB")
    ubt = os.path.join(d, "UBOOT.USB")
    boot = os.path.join(d, "boot.PARTITION")
    sysp = os.path.join(d, "system.PARTITION")

    for f, n in [(ddr, "DDR"), (ubt, "UBOOT"), (boot, "boot"), (sysp, "system")]:
        if not os.path.isfile(f):
            print(f"Missing: {n}")
            sys.exit(1)

    print("=" * 50)
    print(" Amlogic Burn — control transfer mode")
    print("=" * 50)

    dev = find()
    if dev is None:
        print("ERROR: Device not found (VID:1B8E PID:C003)")
        sys.exit(1)

    print(f"Device: {dev.manufacturer} {dev.product}\n")

    if not upload_small(dev, ddr, "DDR.USB"):
        sys.exit(1)
    time.sleep(1)

    if not upload_small(dev, ubt, "UBOOT.USB"):
        sys.exit(1)
    time.sleep(2)

    write_raw(dev, boot, "boot")
    write_raw(dev, sysp, "system")

    print("\nDone!\n")


if __name__ == "__main__":
    main()
