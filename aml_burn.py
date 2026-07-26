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
    """Find device, gentle init."""
    log("Scanning for Amlogic device...")
    for dev in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
        try:
            dev.set_configuration()
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
            log(f"Init failed: {e}")
            continue
    return None


def try_write(dev, data, ep=0x02):
    """Try bulk write, fall back to control if fails."""
    # Strategy 1: Bulk write (try first 64 bytes)
    try:
        n = dev.write(ep, data[:64], timeout=3000)
        if n > 0:
            return "bulk"
    except Exception:
        pass

    # Strategy 2: Control transfer 64 bytes
    try:
        dev.ctrl_transfer(0x40, 0x03, 0, 0, data[:64], timeout=3000)
        return "ctrl"
    except Exception:
        pass

    # Strategy 3: Tiny control, raw vendor
    try:
        dev.ctrl_transfer(0x40, 0xFF, 0, 0, data[:64], timeout=3000)
        return "tiny"
    except Exception:
        pass

    return None


def upload(dev, path, name):
    """Upload using detected method."""
    with open(path, "rb") as f:
        data = f.read()
    total = len(data)

    # Probe with first 64 bytes
    probe = data[:64]
    method = try_write(dev, probe)
    if method is None:
        log(f"ALL methods failed for {name}")
        return False
    log(f"Method: {method}")

    pos = 0
    while pos < total:
        chunk = data[pos:pos + CHUNK]
        if method == "bulk":
            try:
                dev.write(0x02, chunk, timeout=TIMEOUT)
            except Exception:
                log(f"Bulk failed at {pos//1024//1024}MB, fallback to ctrl")
                method = "ctrl"
                continue
        elif method in ("ctrl", "tiny"):
            for i in range(0, len(chunk), 4096):
                sub = chunk[i:i + 4096]
                try:
                    dev.ctrl_transfer(0x40, 0x03, 0, i // 4096, sub, timeout=5000)
                except Exception:
                    log(f"Ctrl failed at {pos//1024//1024}MB")
                    return False
        pos += len(chunk)
        if pos % (CHUNK * 5) == 0 or pos >= total:
            pct = pos * 100 // total
            log(f"  {name}: {pct}% ({pos//1024//1024}MB / {total//1024//1024}MB)")

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
