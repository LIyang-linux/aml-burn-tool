#!/usr/bin/env python3
"""Amlogic USB Burn — control transfer mode for xHCI compatibility."""
import sys, os, time

try:
    import usb.core
    import usb.util
except ImportError:
    print("pip install pyusb")
    sys.exit(1)

AML_VID, AML_PID = 0x1B8E, 0xC003
TIMEOUT = 5000
CHUNK = 512 * 1024


def find():
    d = usb.core.find(idVendor=AML_VID, idProduct=AML_PID)
    if not d:
        print("Device not found")
        sys.exit(1)
    try:
        d.set_configuration()
    except:
        pass
    return d


def upload(dev, path, name):
    size = os.path.getsize(path)
    print(f"  Uploading {name} ({size//1024}KB)...")
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    while pos < len(data):
        chunk = data[pos:pos + CHUNK]
        try:
            dev.write(0x02, chunk, timeout=TIMEOUT)
        except usb.core.USBError as e:
            print(f"\n  Bulk failed, retrying with control...")
            # Fallback: use control transfers (endpoint 0)
            for i in range(0, len(chunk), 4096):
                sub = chunk[i:i + 4096]
                dev.ctrl_transfer(0x40, 0xA0, 0, 0, sub, timeout=3000)
        pos += len(chunk)
    print(f"  {name} OK")
    time.sleep(1)


def write_part(dev, path, name):
    size = os.path.getsize(path)
    print(f"  Writing {name} ({size//1024//1024}MB)...")
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    while pos < len(data):
        chunk = data[pos:pos + CHUNK]
        try:
            dev.write(0x02, chunk, timeout=TIMEOUT * 3)
        except usb.core.USBError:
            for i in range(0, len(chunk), 4096):
                sub = chunk[i:i + 4096]
                dev.ctrl_transfer(0x40, 0xA0, 0, 0, sub, timeout=3000)
        pos += len(chunk)
        pct = min(100, pos * 100 // len(data)) if len(data) else 100
        print(f"\r  {name}: {pct}%", end="")
    print(f"\n  {name}: done")


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
    print(f"Device: {dev.manufacturer} {dev.product}\n")

    upload(dev, ddr, "DDR.USB")
    upload(dev, ubt, "UBOOT.USB")
    time.sleep(2)
    write_part(dev, boot, "boot")
    write_part(dev, sysp, "system")
    print("\nDone!\n")


if __name__ == "__main__":
    main()
