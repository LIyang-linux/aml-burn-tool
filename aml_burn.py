#!/usr/bin/env python3
"""
Amlogic USB Burn Tool — CORRECT Protocol Edition
Based on pyamlboot reverse engineering.
Pure control transfer — no bulk (xHCI compatible).
"""
import sys, os, time
import usb.core, usb.util

VID, PID = 0x1B8E, 0xC003

# Correct Amlogic Boot ROM request codes (from pyamlboot)
REQ_WRITE_MEM     = 0x01   # Write small memory (up to 64 bytes, control transfer)
REQ_READ_MEM      = 0x02   # Read small memory
REQ_RUN_IN_ADDR   = 0x05   # Execute code at address
REQ_IDENTIFY_HOST = 0x20   # Identify / get chip ID
REQ_PASSWORD      = 0x35   # Unlock (may not be needed)

BLOCK_SIZE = 64  # Maximum per control transfer


def log(msg, level="INFO"):
    icon = {"INFO": "  ", "OK": "  ✅", "FAIL": "  ❌", "STEP": "  🔧"}
    print(f"{icon.get(level, '  ')}{msg}", flush=True)


def find_device():
    devs = list(usb.core.find(find_all=True, idVendor=VID, idProduct=PID))
    if not devs:
        return None
    d = devs[0]
    try:
        d.set_configuration()
        usb.util.claim_interface(d, 0)
    except:
        pass
    return d


def write_simple(dev, address, data):
    """Write up to 64 bytes to memory via control transfer.
    REQ_WRITE_MEM: wValue=addr_hi, wIndex=addr_lo
    """
    if len(data) > BLOCK_SIZE:
        raise ValueError(f"Max {BLOCK_SIZE} bytes")
    dev.ctrl_transfer(
        bmRequestType=0x40,           # Host-to-Device, Vendor, Device
        bRequest=REQ_WRITE_MEM,       # 0x01
        wValue=(address >> 16) & 0xFFFF,
        wIndex=address & 0xFFFF,
        data_or_wLength=data,
        timeout=5000
    )


def write_memory(dev, address, data):
    """Write arbitrary data to memory in 64-byte chunks."""
    total = len(data)
    pos = 0
    errors = 0
    start = time.time()
    label = f"0x{address:08x}"

    while pos < total:
        chunk = data[pos:pos + BLOCK_SIZE]
        addr = address + pos
        try:
            write_simple(dev, addr, chunk)
            errors = 0
            pos += len(chunk)
        except Exception as e:
            errors += 1
            if errors > 10:
                log(f"Write failed at +{pos//1024}KB: {e}", "FAIL")
                return False
            time.sleep(0.05)

        if pos % (BLOCK_SIZE * 200) == 0 or pos >= total:
            elapsed = max(0.01, time.time() - start)
            kbps = (pos / 1024) / elapsed
            pct = pos * 100 // total
            print(f"\r  {label}: {pct}% {kbps:.0f}KB/s", end="", flush=True)

    elapsed = time.time() - start
    print(f"\r  {label}: 100% ({total//1024}KB, {elapsed:.0f}s, {total/1024/elapsed:.0f}KB/s)")
    return True


def identify(dev):
    """Get chip identification."""
    try:
        data = dev.ctrl_transfer(0xC0, REQ_IDENTIFY_HOST, 0, 0, 16, timeout=3000)
        log(f"Chip ID response: {' '.join(f'{b:02x}' for b in data)}")
        return bytearray(data)
    except Exception as e:
        log(f"Identify failed: {e}", "FAIL")
        # Try alternate identify
        try:
            data = dev.ctrl_transfer(0xC0, 0x03, 0, 0, 16, timeout=3000)
            log(f"Alt identify: {' '.join(f'{b:02x}' for b in data)}")
            return bytearray(data)
        except:
            return None


def run(dev, address):
    """Execute code at address."""
    log(f"Running at 0x{address:08x}...")
    try:
        dev.ctrl_transfer(0x40, REQ_RUN_IN_ADDR, (address >> 16) & 0xFFFF,
                         address & 0xFFFF, timeout=3000)
        log(f"Run command sent", "OK")
        time.sleep(2)
        return True
    except Exception as e:
        log(f"Run failed: {e}", "FAIL")
        return False


def main():
    print("=" * 60)
    print("  Amlogic Burn Tool — Correct Protocol Edition")
    print("=" * 60)

    img = sys.argv[1] if len(sys.argv) > 1 else "."
    ddr_path = os.path.join(img, "DDR.USB")
    ubt_path = os.path.join(img, "UBOOT.USB")
    boot_path = os.path.join(img, "boot.PARTITION")
    sys_path = os.path.join(img, "system.PARTITION")

    for f, n in [(ddr_path, "DDR"), (ubt_path, "UBOOT"), 
                 (boot_path, "boot"), (sys_path, "system")]:
        if not os.path.isfile(f):
            print(f"Missing: {n}")
            sys.exit(1)

    # Find device
    log("Finding device...", "STEP")
    dev = find_device()
    if not dev:
        log("Device not found!", "FAIL")
        sys.exit(1)
    log(f"Device: {dev.manufacturer} {dev.product}", "OK")

    # Identify
    log("\nIdentify chip...", "STEP")
    chip = identify(dev)

    # Determine GXL addresses
    # GXL (S905L): DDR at 0xd9000000, BL2 params at 0xd900c000
    DDR_LOAD = 0xd9000000
    BL2_PARAMS = 0xd900c000
    UBOOT_LOAD = 0x200c000   # GXL U-Boot load address

    # Load DDR
    with open(ddr_path, "rb") as f:
        ddr_data = f.read()
    with open(ubt_path, "rb") as f:
        ubt_data = f.read()
    with open(boot_path, "rb") as f:
        boot_data = f.read()
    with open(sys_path, "rb") as f:
        sys_data = f.read()

    log(f"\nFiles: DDR={len(ddr_data)} UBOOT={len(ubt_data)} boot={len(boot_data)//1024//1024}MB system={len(sys_data)//1024//1024}MB")

    # === Step 1: Upload to DDR ===
    log(f"\nStep 1: Upload DDR to 0x{DDR_LOAD:08x}", "STEP")
    if not write_memory(dev, DDR_LOAD, ddr_data):
        log("DDR upload failed!", "FAIL")
        sys.exit(1)
    log("DDR uploaded", "OK")

    time.sleep(1)

    # === Step 2: Run DDR — device WILL re-enumerate ===
    log(f"\nStep 2: Run DDR at 0x{DDR_LOAD:08x}", "STEP")
    run(dev, DDR_LOAD)
    log("DDR init running... device will re-enumerate", "OK")
    
    # Wait and re-find device (DDR init causes USB reset)
    log("Waiting for device to re-enumerate...", "STEP")
    # DDR init takes ~2-5 seconds on GXL, then device reappears
    time.sleep(8)
    dev = None
    for i in range(30):
        time.sleep(1)
        dev = find_device()
        if dev:
            log(f"Device reconnected after {8+i}s", "OK")
            break
    
    if not dev:
        log("Device did not reconnect within 38 seconds!", "FAIL")
        log("Try: power cycle the box, then re-run", "INFO")
        sys.exit(1)

    # === Step 3: Upload UBOOT ===
    log(f"\nStep 3: Upload UBOOT to 0x{UBOOT_LOAD:08x}", "STEP")
    if not write_memory(dev, UBOOT_LOAD, ubt_data):
        log("UBOOT upload failed!", "FAIL")
        sys.exit(1)
    log("UBOOT uploaded", "OK")

    time.sleep(1)

    # === Step 4: Run UBOOT ===
    log(f"\nStep 4: Run UBOOT at 0x{UBOOT_LOAD:08x}", "STEP")
    run(dev, UBOOT_LOAD)

    log("\n" + "=" * 60)
    log("ALL DONE! eMMC burning via USB not yet implemented.", "OK")
    log("(need to reverse U-Boot USB gadget protocol)", "INFO")
    log("=" * 60)


if __name__ == "__main__":
    main()
