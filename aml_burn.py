#!/usr/bin/env python3
"""
Amlogic USB Burn — AMLC Protocol Edition (pyamlboot PROTOCOL.md based)
"""
import sys, os, time, struct
import usb.core, usb.util

VID, PID = 0x1B8E, 0xC003

# Correct Amlogic Boot ROM commands (from PROTOCOL.md)
REQ_WRITE_MEM     = 0x01   # Simple write, up to 64 bytes
REQ_READ_MEM      = 0x02   # Simple read
REQ_FILL_MEM      = 0x03   # Fill memory
REQ_MODIFY_MEM    = 0x04   # Modify memory
REQ_RUN           = 0x05   # Run at address (needs 4 bytes data!)
REQ_WRITE_AUX     = 0x06   # Write register
REQ_READ_AUX      = 0x07   # Read register
REQ_WR_LARGE      = 0x11   # Large write (control setup + bulk data)
REQ_RD_LARGE      = 0x12   # Large read
REQ_IDENTIFY      = 0x20   # Identify
REQ_TPL_CMD       = 0x30   # TPL command
REQ_TPL_STAT      = 0x31   # TPL status
REQ_DOWNLOAD      = 0x50   # AMLC download command
REQ_UPLOAD        = 0x60   # AMLC upload command
REQ_BULKCMD       = 0x34   # Bulk command
REQ_WRITE_MEDIA   = 0x32   # Write to eMMC
REQ_READ_MEDIA    = 0x33   # Read from eMMC
REQ_PASSWORD      = 0x35   # Unlock
REQ_NOP           = 0x36   # No-op
REQ_GET_AMLC      = 0x50   # Get AMLC info

BLOCK_SIZE = 64
DDR_LOAD = 0xd9000000   # GXL DDR init address
UBOOT_LOAD = 0x0200c000 # GXL U-Boot load address


def log(msg, level="INFO"):
    icon = {"INFO": "  ", "OK": "  ✅", "FAIL": "  ❌", "STEP": "  🔧", "BULK": "  📦"}
    print(f"{icon.get(level, '  ')}{msg}", flush=True)


def find(reset=False):
    """Find device, optionally with full reset."""
    devs = list(usb.core.find(find_all=True, idVendor=VID, idProduct=PID))
    if not devs:
        return None
    d = devs[0]
    try:
        if reset:
            try:
                d.reset()
            except:
                pass
        d.set_configuration()
        usb.util.claim_interface(d, 0)
    except:
        pass
    return d


def ctrl_out(dev, bReq, wVal, wIdx, data=b""):
    """Control OUT transfer."""
    return dev.ctrl_transfer(0x40, bReq, wVal, wIdx, data, timeout=5000)


def ctrl_in(dev, bReq, wVal, wIdx, length):
    """Control IN transfer."""
    return bytes(dev.ctrl_transfer(0xC0, bReq, wVal, wIdx, length, timeout=5000))


def bulk_out(dev, data):
    """Bulk OUT on endpoint 0x02."""
    return dev.write(0x02, data, timeout=10000)


def bulk_in(dev, size=512):
    """Bulk IN on endpoint 0x81."""
    try:
        return bytes(dev.read(0x81, size, timeout=3000))
    except:
        return b""


def write_mem(dev, addr, data):
    """Simple write memory in 64-byte chunks."""
    total = len(data)
    pos = 0
    errors = 0
    t0 = time.time()
    while pos < total:
        chunk = data[pos:pos + BLOCK_SIZE]
        a = addr + pos
        try:
            ctrl_out(dev, REQ_WRITE_MEM, (a >> 16) & 0xFFFF, a & 0xFFFF, chunk)
            errors = 0
            pos += len(chunk)
        except Exception as e:
            errors += 1
            if errors > 10:
                log(f"Write mem failed at {pos//1024}KB: {e}", "FAIL")
                return False
            time.sleep(0.05)
        if pos % (BLOCK_SIZE * 200) == 0 or pos >= total:
            pct = pos * 100 // total
            elapsed = max(0.01, time.time() - t0)
            kbps = (pos / 1024) / elapsed
            print(f"\r  {pct}% {kbps:.0f}KB/s", end="", flush=True)
    elapsed = time.time() - t0
    print(f"\r  100% ({total//1024}KB in {elapsed:.0f}s)")
    return True


def run_addr(dev, addr):
    """Run code at address (with proper 4-byte data)."""
    # PROTOCOL.md: first byte ORed with 0x10
    addr_bytes = struct.pack("<I", addr)
    addr_bytes = bytes([addr_bytes[0] | 0x10]) + addr_bytes[1:]
    ctrl_out(dev, REQ_RUN, (addr >> 16) & 0xFFFF, addr & 0xFFFF, addr_bytes)
    log(f"Running at 0x{addr:08x}")


def amlc_download(dev):
    """Get AMLC download info."""
    ctrl_out(dev, REQ_DOWNLOAD, 0x0200, 0)
    return bulk_in(dev, 512)


def amlc_upload(dev, offset, size_kb):
    """Upload data via AMLC protocol (bulk required)."""
    # wValue = offset/64K, wIndex = chunk size in bytes
    wVal = (offset // 65536) & 0xFFFF
    ctrl_out(dev, REQ_UPLOAD, wVal, size_kb - 1)


def main():
    print("=" * 60)
    print("  Amlogic Burn — AMLC Protocol Edition")
    print("=" * 60)

    img = sys.argv[1] if len(sys.argv) > 1 else "."
    ddr_p = os.path.join(img, "DDR.USB")
    ubt_p = os.path.join(img, "UBOOT.USB")

    with open(ddr_p, "rb") as f:
        ddr = f.read()
    with open(ubt_p, "rb") as f:
        ubt = f.read()

    # === Find device ===
    log("Find device...", "STEP")
    dev = find()
    if not dev:
        log("Not found!", "FAIL")
        sys.exit(1)
    log(f"{dev.manufacturer} {dev.product}", "OK")

    # === Identify ===
    sid = ctrl_in(dev, REQ_IDENTIFY, 0, 0, 8)
    log(f"ID: {' '.join(f'{b:02x}' for b in sid)}")

    # === Step 1: Simple write DDR to 0xd9000000 ===
    log("\n=== Step 1: Upload DDR via REQ_WRITE_MEM ===", "STEP")
    log(f"Address: 0x{DDR_LOAD:08x}, Size: {len(ddr)} bytes ({len(ddr)//1024}KB)")
    if not write_mem(dev, DDR_LOAD, ddr):
        sys.exit(1)

    # === Step 2: Try AMLC protocol for UBOOT ===
    log("\n=== Step 2: AMLC Download (get loader info) ===", "STEP")
    amlc = amlc_download(dev)
    if amlc and len(amlc) > 0:
        log(f"AMLC: {amlc[:32].hex()}")
        log(f"AMLC text: {amlc[:16]}")
        
        # Parse AMLC header
        if amlc[:4] == b"AMLC":
            data_size = struct.unpack("<I", amlc[8:12])[0]
            offset = struct.unpack("<I", amlc[12:16])[0]
            log(f"  dataSize={data_size} offset={offset}")
            
            # Try bulk upload
            log("\n=== Step 3: Try AMLC Upload (bulk) ===", "STEP")
            try:
                amlc_upload(dev, offset, data_size)
                bulk_out(dev, ubt[:min(16384, len(ubt))])
                resp = bulk_in(dev)
                log(f"Bulk response: {resp[:16].hex() if resp else 'empty'}", "OK")
            except Exception as e:
                log(f"AMLC bulk failed (xHCI): {str(e)[:60]}", "FAIL")
    else:
        log("No AMLC response. Trying REQ_WRITE_MEM for UBOOT after DDR run...", "INFO")
        
        # === Run DDR ===
        log("\n=== Run DDR init ===", "STEP")
        run_addr(dev, DDR_LOAD + 0x10)  # Entry point offset
        time.sleep(2)
        
        # Re-find — old device is gone after DDR
        log("Re-find after DDR...")
        try:
            usb.util.dispose_resources(dev)
        except:
            pass
        dev = None
        time.sleep(3)
        for i in range(30):
            time.sleep(1)
            dev2 = find(reset=(i==0))  # reset on first attempt
            if dev2:
                dev = dev2
                log(f"Reconnected ({3+i}s)", "OK")
                break
        
        # Try AMLC again
        log("\n=== Try AMLC again after DDR ===", "STEP")
        amlc = amlc_download(dev)
        if amlc and len(amlc) > 0:
            log(f"AMLC: {amlc[:32].hex()}")

    print("\n" + "=" * 60)
    log("Done.", "OK")
    print("=" * 60)


if __name__ == "__main__":
    main()
