#!/usr/bin/env python3
"""Read eMMC bootloader via Amlogic Boot ROM — identify + read mem."""
import sys, os, time
import usb.core, usb.util

VID, PID = 0x1B8E, 0xC003

# Amlogic Boot ROM commands (from pyamlboot source)
REQ_IDENTIFY_HOST = 0x01
REQ_GET_AMLC       = 0x20
REQ_READ_MEM       = 0x06
REQ_RD_LARGE_MEM   = 0x18
REQ_WRITE_MEM      = 0x12
REQ_WR_LARGE_MEM   = 0x19
REQ_RUN_IN_ADDR    = 0x02
REQ_NOP            = 0x00
REQ_TPL_CMD        = 0x40
REQ_TPL_STAT       = 0x41


def log(msg):
    print(f"  {msg}", flush=True)


def main():
    print("=" * 50)
    print("  Amlogic eMMC Reader")
    print("=" * 50)

    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if not dev:
        print("Device not found")
        sys.exit(1)

    try:
        dev.set_configuration()
        usb.util.claim_interface(dev, 0)
    except:
        pass

    log(f"Device: {dev.manufacturer} {dev.product}")

    # === Step 1: Identify ===
    log("\n--- Identify ---")
    try:
        data = dev.ctrl_transfer(0xC0, REQ_IDENTIFY_HOST, 0, 0, 16, timeout=3000)
        log(f"Identify: {' '.join(f'{b:02x}' for b in data)}")
        if len(data) >= 4:
            chip_id = int.from_bytes(bytes(data[:4]), 'little')
            log(f"Chip ID: {chip_id:#010x}")
    except Exception as e:
        log(f"Identify failed: {e}")

    # === Step 2: Get AMLC (Amlogic Chip) info ===
    log("\n--- Get AMLC ---")
    try:
        data = dev.ctrl_transfer(0xC0, REQ_GET_AMLC, 0, 0, 64, timeout=3000)
        log(f"AMLC: {' '.join(f'{b:02x}' for b in data)}")
    except Exception as e:
        log(f"Get AMLC failed: {e}")

    # === Step 3: NOP (ping) ===
    log("\n--- NOP ping ---")
    try:
        data = dev.ctrl_transfer(0xC0, REQ_NOP, 0, 0, 8, timeout=3000)
        log(f"NOP: {' '.join(f'{b:02x}' for b in data)}")
    except Exception as e:
        log(f"NOP failed: {e}")

    # === Step 4: Read memory at various offsets ===
    # eMMC bootloader is at offset 0 on Amlogic
    # Boot ROM memory map for GXL:
    #   0xd9000000 = DDR init area
    #   0x10000000 = U-Boot load area
    # But we want to read eMMC, not memory...
    # Boot ROM can read eMMC via large read commands

    log("\n--- Read memory tests ---")
    
    # Try read at common Amlogic memory addresses
    addrs = [
        (0x01000000, "U-Boot load area"),
        (0x01010000, "U-Boot +64KB"),
        (0xd9000000, "DDR init area"),
        (0x00000000, "Zero"),
        (0x10000000, "U-Boot alt"),
    ]
    
    for addr, desc in addrs:
        try:
            data = dev.ctrl_transfer(0xC0, REQ_READ_MEM, 
                                     addr & 0xFFFF, 
                                     (addr >> 16) & 0xFFFF,
                                     64, timeout=3000)
            if data and len(data) > 0:
                log(f"Read {desc} (0x{addr:08x}): {len(data)} bytes")
                log(f"  {' '.join(f'{b:02x}' for b in data[:32])}")
            else:
                log(f"Read {desc}: empty")
        except Exception as e:
            log(f"Read {desc} (0x{addr:08x}): {e}")

    # === Step 5: Try large read ===
    log("\n--- Read large memory ---")
    for req in [REQ_RD_LARGE_MEM, REQ_READ_MEM, 0x05, 0x07, 0x08]:
        try:
            data = dev.ctrl_transfer(0xC0, req, 0, 0x0100, 512, timeout=5000)
            if data and len(data) > 0:
                log(f"req=0x{req:02x}: {len(data)} bytes!")
                log(f"  {' '.join(f'{b:02x}' for b in data[:32])}")
                # Save to file
                with open(f"emmc_dump_0x{req:02x}.bin", "wb") as f:
                    f.write(bytes(data))
                log(f"  Saved to emmc_dump_0x{req:02x}.bin")
                break
        except Exception as e:
            log(f"req=0x{req:02x}: {str(e)[:60]}")

    # === Step 6: Try TPL commands ===
    log("\n--- TPL commands ---")
    for req in [REQ_TPL_CMD, REQ_TPL_STAT]:
        try:
            data = dev.ctrl_transfer(0xC0, req, 0, 0, 8, timeout=2000)
            log(f"req=0x{req:02x}: {' '.join(f'{b:02x}' for b in data) if data else 'empty'}")
        except Exception as e:
            log(f"req=0x{req:02x}: {str(e)[:60]}")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
