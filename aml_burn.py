#!/usr/bin/env python3
"""
Amlogic USB Burn Tool — Skip ERASE BOOTLOADER
Compatible with eMMC chips that fail standard ERASE commands.
"""
import sys
import os
import time

try:
    import usb.core
    import usb.util
except ImportError:
    print("Install: pip install pyusb")
    sys.exit(1)

AML_VID = 0x1B8E
AML_PID = 0xC003
BULK_OUT = 0x02
BULK_IN = 0x81
TIMEOUT = 5000
CHUNK = 512 * 1024


def find_device():
    dev = usb.core.find(idVendor=AML_VID, idProduct=AML_PID)
    if dev is None:
        print("ERROR: Amlogic device (1B8E:C003) not found")
        sys.exit(1)
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    return dev


def upload(dev, path, name):
    size = os.path.getsize(path)
    print(f"  Uploading {name} ({size//1024}KB)...")
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    while pos < len(data):
        chunk = data[pos:pos + CHUNK]
        dev.write(BULK_OUT, chunk, timeout=TIMEOUT)
        pos += len(chunk)
    time.sleep(1)
    print(f"  {name} OK")


def write_raw(dev, path, name):
    size = os.path.getsize(path)
    print(f"  Writing {name} ({size//1024//1024}MB)...")
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    while pos < len(data):
        chunk = data[pos:pos + CHUNK]
        dev.write(BULK_OUT, chunk, timeout=TIMEOUT * 3)
        pos += len(chunk)
        if pos % (CHUNK * 20) == 0 or pos >= len(data):
            pct = min(100, pos * 100 // len(data))
            print(f"\r  {name}: {pct}%", end="")
    print()
    print(f"  {name}: done")


def main():
    if len(sys.argv) < 2:
        print("Usage: python aml_burn.py <image_dir>")
        sys.exit(1)

    d = sys.argv[1]
    ddr = os.path.join(d, "DDR.USB")
    ubt = os.path.join(d, "UBOOT.USB")
    boot = os.path.join(d, "boot.PARTITION")
    sysp = os.path.join(d, "system.PARTITION")

    for f, n in [(ddr, "DDR.USB"), (ubt, "UBOOT.USB"), (boot, "boot"), (sysp, "system")]:
        if not os.path.isfile(f):
            print(f"Missing: {n} in {d}")
            sys.exit(1)

    print("=" * 50)
    print(" Amlogic Burn Tool — NO ERASE BOOTLOADER")
    print("=" * 50)

    dev = find_device()
    print(f"Device: {dev.manufacturer} {dev.product}\n")

    # DDR init
    upload(dev, ddr, "DDR.USB")
    # USB burn U-Boot
    upload(dev, ubt, "UBOOT.USB")
    time.sleep(2)

    # Write partitions (NO erase)
    write_raw(dev, boot, "boot")
    write_raw(dev, sysp, "system")

    print("\nDone! Power cycle the box.\n")


if __name__ == "__main__":
    main()
