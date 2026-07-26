#!/usr/bin/env python3
"""Amlogic Burn Tool — VERBOSE DEBUG MODE"""
import sys, os, time, traceback
import usb.core, usb.util

VID, PID = 0x1B8E, 0xC003
TIMEOUT = 5000


def dbg(msg):
    print(f"  [DBG] {msg}", flush=True)


def main():
    img = sys.argv[1] if len(sys.argv) > 1 else "."

    # Step 1: Find device
    dbg("Step 1: Finding device...")
    devs = list(usb.core.find(find_all=True, idVendor=VID, idProduct=PID))
    if not devs:
        print("FATAL: Device not found!")
        sys.exit(1)
    dev = devs[0]
    dbg(f"Found: {dev}")
    dbg(f"Bus: {dev.bus}, Address: {dev.address}")
    dbg(f"Port: {dev.port_number if hasattr(dev,'port_number') else '?'}")
    dbg(f"Speed: {dev.speed}")

    # Step 2: Set configuration
    dbg("Step 2: Set configuration...")
    try:
        dev.set_configuration()
        dbg("Configuration set OK")
    except Exception as e:
        dbg(f"set_configuration failed: {e}")
        try:
            dev.reset()
            time.sleep(1)
            dev.set_configuration()
            dbg("Configuration set after reset OK")
        except Exception as e2:
            dbg(f"Still failed after reset: {e2}")

    # Step 3: Claim interface
    dbg("Step 3: Claim interface...")
    try:
        if dev.is_kernel_driver_active(0):
            dbg("Detaching kernel driver from interface 0")
            dev.detach_kernel_driver(0)
        usb.util.claim_interface(dev, 0)
        dbg("Interface 0 claimed OK")
    except Exception as e:
        dbg(f"Claim interface 0 failed: {e}")
        # Try alternative
        try:
            usb.util.claim_interface(dev, 1)
            dbg("Interface 1 claimed OK")
        except Exception as e2:
            dbg(f"Claim interface 1 also failed: {e2}")

    # Step 4: Get active config
    dbg("Step 4: Active config...")
    cfg = dev.get_active_configuration()
    dbg(f"Config: {cfg}")
    for intf in cfg:
        dbg(f"  Interface {intf.bInterfaceNumber}: {intf.bAlternateSetting}")
        for ep in intf:
            dbg(f"    EP {ep.bEndpointAddress:#04x} type={ep.bmAttributes} max={ep.wMaxPacketSize}")

    # Step 5: Try control transfer (handshake)
    dbg("Step 5: Control transfer handshake...")
    for req in [0x01, 0x00, 0x02, 0xFE, 0xFF]:
        try:
            data = dev.ctrl_transfer(0xC0, req, 0, 0, 8, timeout=2000)
            dbg(f"Control IN req=0x{req:02X} → {data.hex() if data else 'empty'}")
        except Exception as e:
            dbg(f"Control IN req=0x{req:02X} → FAIL: {str(e)[:80]}")

    # Step 6: Try bulk write (1 byte to start)
    dbg("Step 6: Bulk write test (1 byte)...")
    try:
        n = dev.write(0x02, b'\x00', timeout=2000)
        dbg(f"Bulk 1 byte → wrote {n}, OK!")
    except Exception as e:
        dbg(f"Bulk 1 byte → FAIL: {str(e)[:80]}")

    # Step 7: Try bulk write (64 bytes)
    dbg("Step 7: Bulk write test (64 bytes)...")
    try:
        n = dev.write(0x02, b'\x00' * 64, timeout=2000)
        dbg(f"Bulk 64 bytes → wrote {n}, OK!")
    except Exception as e:
        dbg(f"Bulk 64 bytes → FAIL: {str(e)[:80]}")

    # Step 8: Try to read DDR.USB
    ddr = os.path.join(img, "DDR.USB")
    if os.path.exists(ddr):
        with open(ddr, "rb") as f:
            ddr_data = f.read()
        dbg(f"DDR.USB loaded: {len(ddr_data)} bytes")
        
        dbg("Step 8: Upload DDR.USB (first 512 bytes)...")
        try:
            n = dev.write(0x02, ddr_data[:512], timeout=TIMEOUT)
            dbg(f"Bulk 512 bytes → wrote {n}, OK!")
        except Exception as e:
            dbg(f"Bulk 512 bytes → FAIL: {str(e)[:80]}")
            # Try control
            try:
                dbg("Trying control transfer instead...")
                dev.ctrl_transfer(0x40, 0x03, 0, 0, ddr_data[:512], timeout=5000)
                dbg("Control 512 bytes OK!")
            except Exception as e2:
                dbg(f"Control 512 bytes → FAIL: {str(e2)[:80]}")

    print("\n=== DEBUG COMPLETE ===")


if __name__ == "__main__":
    main()
