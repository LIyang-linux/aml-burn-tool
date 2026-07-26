#!/usr/bin/env python3
"""Amlogic Burn Tool v3 — full USB init + multi-strategy."""
import sys, os, time, struct
import usb.core
import usb.util

VID, PID = 0x1B8E, 0xC003
TIMEOUT = 10000
CHUNK = 512 * 1024
MAX_PKT = 65536


def log(msg):
    print(f"  {msg}")


def find_and_init():
    """Find device and fully initialize USB."""
    log("Scanning for Amlogic device...")
    for dev in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
        try:
            # Full reset sequence
            dev.reset()
            time.sleep(0.5)
            # Set configuration
            dev.set_configuration()
            # Claim interface 0
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
            except:
                pass
            try:
                usb.util.claim_interface(dev, 0)
            except:
                pass
            log(f"Found: {dev.manufacturer} {dev.product}")
            return dev
        except Exception as e:
            log(f"Init attempt failed: {e}")
            continue
    return None


def try_write(dev, data, ep=0x02):
    """Try bulk write, fall back to control if fails."""
    # Strategy 1: Bulk write
    try:
        n = dev.write(ep, data[:4096], timeout=3000)
        if n > 0:
            return "bulk"
    except Exception:
        pass

    # Strategy 2: Control transfer in 4KB chunks
    try:
        for i in range(0, min(65536, len(data)), 4096):
            chunk = data[i:i + 4096]
            n = dev.ctrl_transfer(0x40, 0x03, 0, i // 4096, chunk, timeout=2000)
        return "ctrl"
    except Exception:
        pass

    # Strategy 3: Tiny control transfer (64 bytes)
    try:
        for i in range(0, min(1024, len(data)), 64):
            chunk = data[i:i + 64]
            dev.ctrl_transfer(0x40, 0xFF, 0, i, chunk, timeout=1000)
        return "tiny"
    except Exception:
        pass

    return None


def upload(dev, path, name):
    """Upload file to device using best available strategy."""
    with open(path, "rb") as f:
        data = f.read()
    total = len(data)

    # Probe best transfer method with first 64KB
    probe = data[:65536]
    method = try_write(dev, probe)
    if method is None:
        log(f"ALL transfer methods failed for {name}")
        return False
    log(f"Method: {method}")

    pos = 65536  # Already sent probe
    while pos < total:
        chunk = data[pos:pos + CHUNK]
        if not try_write(dev, chunk):
            log(f"Transfer failed at {pos//1024//1024}MB")
            return False
        pos += len(chunk)
        if pos % (CHUNK * 5) == 0:
            pct = pos * 100 // total
            log(f"  {name}: {pct}% ({pos//1024//1024}MB / {total//1024//1024}MB)")

    log(f"{name}: OK")
    return True


def main():
    img = sys.argv[1] if len(sys.argv) > 1 else "."
    ddr = os.path.join(img, "DDR.USB")
    ubt = os.path.join(img, "UBOOT.USB")
    boot = os.path.join(img, "boot.PARTITION")
    sysp = os.path.join(img, "system.PARTITION")

    for f, n in [(ddr, "DDR"), (ubt, "UBOOT"), (boot, "boot"), (sysp, "system")]:
        if not os.path.isfile(f):
            print(f"ERROR: Missing {n} -> {f}")
            sys.exit(1)

    print("=" * 50)
    print(" Amlogic Burn v3 — Auto-detect transfer mode")
    print("=" * 50)

    dev = find_and_init()
    if not dev:
        print("ERROR: Cannot connect to device")
        sys.exit(1)

    for step, f, name in [
        (1, ddr, "DDR.USB"),
        (2, ubt, "UBOOT.USB"),
        (3, boot, "boot.PARTITION"),
        (4, sysp, "system.PARTITION"),
    ]:
        log(f"[{step}/4] {name} ({os.path.getsize(f)//1024//1024}MB)")
        if not upload(dev, f, name):
            print(f"\nFAILED at step {step}")
            sys.exit(1)
        time.sleep(1)

    print("\nDone! Power cycle.\n")


if __name__ == "__main__":
    main()
