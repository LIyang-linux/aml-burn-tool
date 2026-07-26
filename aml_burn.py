#!/usr/bin/env python3
"""Amlogic USB Burn — 64-byte packet mode for xHCI compatibility."""
import sys, os, time

# Force libusb1 backend
os.environ["PYUSB_BACKEND"] = "libusb1"

import usb.core
import usb.backend.libusb1

backend = usb.backend.libusb1.get_backend()
if backend is None:
    print("ERROR: libusb1 backend not available.")
    print("Install: pip install libusb1")
    print("Also copy libusb-1.0.dll to Windows\\System32")
    sys.exit(1)

AML_VID, AML_PID = 0x1B8E, 0xC003
TIMEOUT = 8000  # Longer timeout for small packets
MAX_PACKET = 64   # USB control endpoint max packet size


def find():
    """Find device using explicit libusb1 backend."""
    for d in usb.core.find(find_all=True, backend=backend,
                           idVendor=AML_VID, idProduct=AML_PID):
        try:
            # Detach kernel driver
            for cfg in d:
                for intf in cfg:
                    if d.is_kernel_driver_active(intf.bInterfaceNumber):
                        d.detach_kernel_driver(intf.bInterfaceNumber)
            d.set_configuration()
            return d
        except usb.core.USBError:
            return d
    return None


def upload_small(dev, path, name):
    """Upload using 64-byte packets via endpoint 0 (control)."""
    size = os.path.getsize(path)
    print(f"  Uploading {name} ({size//1024}KB, {size//MAX_PACKET} packets)...")

    with open(path, "rb") as f:
        data = f.read()

    sent = 0
    errors = 0
    while sent < len(data):
        chunk = data[sent:sent + MAX_PACKET]
        try:
            # Use control transfer on endpoint 0 (0x40=host-to-device, vendor)
            dev.ctrl_transfer(0x40, 0xA0, sent & 0xFFFF, (sent >> 16) & 0xFFFF,
                             chunk, timeout=TIMEOUT)
            sent += len(chunk)
            errors = 0
            if sent % (MAX_PACKET * 1000) == 0:
                print(f"\r  {sent//1024}/{size//1024}KB", end="")
        except usb.core.USBError as e:
            errors += 1
            if errors > 10:
                print(f"\n  FAILED after {errors} retries at {sent//1024}KB")
                return False
            time.sleep(0.01)

    print(f"\r  {name} OK ({sent//1024}KB)   ")
    return True


def write_raw(dev, path, name):
    """Write partition using the same 64-byte packet approach."""
    size = os.path.getsize(path)
    mb = size // 1024 // 1024
    print(f"  Writing {name} ({mb}MB)...")

    with open(path, "rb") as f:
        data = f.read()

    sent = 0
    while sent < len(data):
        chunk = data[sent:sent + MAX_PACKET]
        dev.ctrl_transfer(0x40, 0xA0, sent & 0xFFFF, (sent >> 16) & 0xFFFF,
                         chunk, timeout=TIMEOUT)
        sent += len(chunk)
        if sent % (MAX_PACKET * 50000) == 0:
            pct = sent * 100 // len(data)
            print(f"\r  {name}: {pct}% ({sent//1024//1024}MB/{mb}MB)", end="")

    print(f"\r  {name}: 100% ({mb}MB) done!   ")


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
            print(f"Missing: {n} ({f})")
            sys.exit(1)

    print("=" * 50)
    print(" Amlogic Burn — 64-byte packet mode")
    print(f" Backend: {backend}")
    print("=" * 50)

    dev = find()
    if dev is None:
        print("ERROR: Device not found (VID:1B8E PID:C003)")
        print("Install WinUSB driver via Zadig: libusbK or WinUSB")
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

    print("\nDone! Power cycle the box.\n")


if __name__ == "__main__":
    main()
