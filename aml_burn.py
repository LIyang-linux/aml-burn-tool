#!/usr/bin/env python3
"""
Amlogic USB Burn Tool — Universal Edition
Auto-detects driver type, tries all strategies, burns image.
"""
import sys, os, time, ctypes
from ctypes import wintypes, byref, Structure, sizeof

# ============================================================
# Win32 API Setup
# ============================================================
kernel32 = ctypes.windll.kernel32
setupapi = ctypes.windll.setupapi
winusb_dll = ctypes.windll.winusb

ULONG = wintypes.ULONG
HANDLE = wintypes.HANDLE
DWORD = wintypes.DWORD
SPDRP_HARDWAREID = 1
SPDRP_DEVICEDESC = 0
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE = ctypes.c_void_p(-1).value
GENERIC_WRITE = 0x40000000
GENERIC_READ = 0x80000000
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
WINUSB_GUID = (ctypes.c_ubyte * 16)(
    0xDE, 0xE8, 0x24, 0x3F, 0x53, 0xB9, 0xF5, 0x45,
    0x86, 0xD9, 0x2D, 0xA6, 0x74, 0x4A, 0x15, 0x21
)

class SP_DEVINFO_DATA(Structure):
    _fields_ = [("cbSize", DWORD), ("ClassGuid", ctypes.c_ubyte*16),
                ("DevInst", DWORD), ("Reserved", ctypes.c_void_p)]

CHUNK = 1024 * 1024
BULK_OUT = 0x02
BULK_IN = 0x81
TIMEOUT = 15000


def log(msg, level="INFO"):
    prefix = {"INFO": "  ", "OK": "  ✅", "FAIL": "  ❌", "WARN": "  ⚠️", "DBG": "  🔍"}
    print(f"{prefix.get(level, '  ')}{msg}", flush=True)


# ============================================================
# Phase 1: Device Discovery (try ALL methods)
# ============================================================
def find_device():
    """Find Amlogic 1B8E:C003 via every possible method."""
    log("Scanning for Amlogic device (VID:1B8E PID:C003)...")
    results = []

    # Method 1: All devices
    hdi = setupapi.SetupDiGetClassDevsA(None, None, None, DIGCF_PRESENT)
    if hdi != INVALID_HANDLE:
        dd = SP_DEVINFO_DATA()
        dd.cbSize = sizeof(SP_DEVINFO_DATA)
        i = 0
        while setupapi.SetupDiEnumDeviceInfo(hdi, i, byref(dd)):
            i += 1
            buf = ctypes.create_string_buffer(256)
            if setupapi.SetupDiGetDeviceRegistryPropertyA(hdi, byref(dd), SPDRP_HARDWAREID, None, buf, 256, None):
                hw = buf.value.decode('utf-8', errors='ignore').lower()
                if '1b8e' in hw and 'c003' in hw:
                    desc_buf = ctypes.create_string_buffer(256)
                    setupapi.SetupDiGetDeviceRegistryPropertyA(hdi, byref(dd), 0, None, desc_buf, 256, None)
                    inst_buf = ctypes.create_unicode_buffer(256)
                    setupapi.SetupDiGetDeviceInstanceIdW(hdi, byref(dd), inst_buf, 256, None)
                    results.append(("all", inst_buf.value, desc_buf.value.decode('utf-8', errors='ignore')))
        setupapi.SetupDiDestroyDeviceInfoList(hdi)
        log(f"Method 1 (all devices): {len(results)} found")
    else:
        log("Method 1: inaccessible", "WARN")

    # Method 2: WinUSB interface
    hdi2 = setupapi.SetupDiGetClassDevsA(WINUSB_GUID, None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdi2 != INVALID_HANDLE:
        dd = SP_DEVINFO_DATA()
        dd.cbSize = sizeof(SP_DEVINFO_DATA)
        i = 0
        while setupapi.SetupDiEnumDeviceInfo(hdi2, i, byref(dd)):
            i += 1
            inst_buf = ctypes.create_unicode_buffer(256)
            setupapi.SetupDiGetDeviceInstanceIdW(hdi2, byref(dd), inst_buf, 256, None)
            if '1b8e' in inst_buf.value.lower():
                results.append(("winusb", inst_buf.value, "WinUSB"))
        setupapi.SetupDiDestroyDeviceInfoList(hdi2)
        log(f"Method 2 (WinUSB interfaces): {i} total, {sum(1 for r in results if r[0]=='winusb')} Amlogic")
    else:
        log("Method 2: WinUSB not available on this system", "DBG")

    # Method 3: pyusb fallback
    try:
        import usb.core
        pydevs = list(usb.core.find(find_all=True, idVendor=0x1B8E, idProduct=0xC003))
        log(f"Method 3 (pyusb/libsub): {len(pydevs)} found")
        if pydevs:
            d = pydevs[0]
            try:
                d.set_configuration()
            except:
                pass
            results.append(("pyusb", pydevs, str(d)))
    except Exception as e:
        log(f"Method 3 (pyusb): {str(e)[:60]}", "DBG")

    if not results:
        return None, None
    return results, hdi


# ============================================================
# Phase 2: Try Open via WinUSB
# ============================================================
def try_winusb(devices):
    """Try to open device via WinUSB with multiple path formats."""
    for method, data, desc in devices:
        if method == "pyusb":
            continue
        inst_id = data
        for guid in [
            "{3f24e8de-b953-45f5-86d9-2da6744a1521}",
            "{dee824ef-729b-4a0e-9c69-b452f5e6f76b}",
            "{a5dcbf10-6530-11d2-901f-00c04fb951ed}",
        ]:
            for fmt in [
                f"\\\\?\\usb#vid_1b8e&pid_c003#{inst_id}#{guid}",
                f"\\\\?\\usb#{inst_id}#{guid}",
            ]:
                h = kernel32.CreateFileW(fmt, GENERIC_WRITE | GENERIC_READ,
                    FILE_SHARE_WRITE, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
                if h != INVALID_HANDLE:
                    wh = HANDLE()
                    if winusb_dll.WinUsb_Initialize(h, byref(wh)):
                        log(f"WinUSB opened: {fmt[:80]}...", "OK")
                        return ("winusb", h, wh)
                    kernel32.CloseHandle(h)

    return ("none", None, None)


# ============================================================
# Phase 3: Try Open via pyusb
# ============================================================
def try_pyusb(devices):
    """Try to claim device via pyusb."""
    for method, data, desc in devices:
        if method == "pyusb":
            devs = data
            if devs:
                d = devs[0]
                try:
                    d.set_configuration()
                except:
                    pass
                return ("pyusb", d, None)
    return ("none", None, None)


# ============================================================
# Phase 4: Upload & Burn
# ============================================================
def upload_winusb(wh, path, name, step, total_steps):
    """Upload via WinUSB bulk pipe."""
    with open(path, "rb") as f:
        data = f.read()
    size = len(data)
    mb = size // 1024 // 1024
    buf = (ctypes.c_ubyte * CHUNK)()
    pos = 0
    start = time.time()

    while pos < size:
        chunk = data[pos:pos + CHUNK]
        ctypes.memmove(buf, chunk, len(chunk))
        written = ULONG()
        if not winusb_dll.WinUsb_WritePipe(wh, BULK_OUT, buf, len(chunk), byref(written), None):
            err = kernel32.GetLastError()
            log(f"WritePipe failed at {pos//1024//1024}MB (error {err})", "FAIL")
            return False
        pos += len(chunk)
        pct = pos * 100 // size
        elapsed = time.time() - start
        speed = (pos / 1024 / 1024) / elapsed if elapsed > 0 else 0
        print(f"\r  [{step}/{total_steps}] {name}: {pct}%  {speed:.1f}MB/s", end="", flush=True)

    print()
    return True


def upload_pyusb(dev, path, name, step, total_steps):
    """Upload via pyusb — verbose debug mode."""
    import usb.core
    with open(path, "rb") as f:
        data = f.read()
    size = len(data)
    start = time.time()
    log(f"{name}: {size} bytes, will try multiple methods")

    # === Test 1: Bulk write 1 byte ===
    log("Test 1: Bulk OUT 1 byte...")
    try:
        n = dev.write(0x02, data[:1], timeout=3000)
        log(f"→ OK! wrote {n} byte", "OK")
        method = "bulk"
        chunk = CHUNK
    except Exception as e:
        log(f"→ FAIL: {e}", "FAIL")

        # === Test 2: Bulk write 64 bytes ===
        log("Test 2: Bulk OUT 64 bytes...")
        try:
            n = dev.write(0x02, data[:64], timeout=3000)
            log(f"→ OK! wrote {n} bytes", "OK")
            method = "bulk"
            chunk = CHUNK
        except Exception as e:
            log(f"→ FAIL: {e}", "FAIL")

            # === Test 3: Control OUT 64 bytes, bRequest=0x03 ===
            log("Test 3: Control OUT bRequest=0x03, 64 bytes...")
            try:
                dev.ctrl_transfer(0x40, 0x03, 0, 0, data[:64], timeout=3000)
                log("→ OK!", "OK")
                method = "ctrl-4K"
                chunk = 4096
            except Exception as e:
                log(f"→ FAIL: {e}", "FAIL")

                # === Test 4: Control OUT, alternate bRequest ===
                log("Test 4: Control OUT bRequest=0xA0, 64 bytes...")
                try:
                    dev.ctrl_transfer(0x40, 0xA0, 0, 0, data[:64], timeout=3000)
                    log("→ OK!", "OK")
                    method = "ctrl-4K"
                    chunk = 4096
                except Exception as e:
                    log(f"→ FAIL: {e}", "FAIL")

                    # === Test 5: Control OUT, bRequest=0xFF ===
                    log("Test 5: Control OUT bRequest=0xFF, 64 bytes...")
                    try:
                        dev.ctrl_transfer(0x40, 0xFF, 0, 0, data[:64], timeout=3000)
                        log("→ OK!", "OK")
                        method = "ctrl-4K"
                        chunk = 4096
                    except Exception as e:
                        log(f"→ FAIL: {e}", "FAIL")
                        log("ALL 5 strategies exhausted. xHCI is incompatible.", "FAIL")
                        return False

    # === Upload with working method ===
    log(f"Uploading via {method}, chunk={chunk}...")
    pos = 0
    errors = 0
    while pos < size:
        piece = data[pos:pos + chunk]
        try:
            if method == "bulk":
                dev.write(0x02, piece, timeout=TIMEOUT)
            else:
                for i in range(0, len(piece), 4096):
                    sub = piece[i:i + 4096]
                    dev.ctrl_transfer(0x40, 0x03, 0, i // 4096, sub, timeout=5000)
            errors = 0
            pos += len(piece)
        except Exception as e:
            errors += 1
            log(f"Error at {pos//1024//1024}MB (error #{errors}): {str(e)[:80]}", "WARN")
            if errors > 5:
                return False
            time.sleep(0.1)

        if pos % (chunk * 20) == 0 or pos >= size:
            elapsed = max(0.01, time.time() - start)
            speed = (pos / 1024 / 1024) / elapsed
            pct = pos * 100 // size
            print(f"\r  [{step}/{total_steps}] {name}: {pct}%  {speed:.1f}MB/s  ", end="", flush=True)

    print()
    log(f"Uploaded in {time.time()-start:.0f}s", "OK")
    return True


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("  Amlogic USB Burn Tool — Universal Edition")
    print("=" * 60)

    img = sys.argv[1] if len(sys.argv) > 1 else "."

    # Check files
    files = [
        ("DDR.USB", "DDR init", 0),
        ("UBOOT.USB", "USB U-Boot", 0),
        ("boot.PARTITION", "boot partition", 0),
        ("system.PARTITION", "rootfs", 0),
    ]
    for fname, label, _ in files:
        p = os.path.join(img, fname)
        if not os.path.isfile(p):
            print(f"ERROR: Missing {fname} in {img}")
            sys.exit(1)
        sz = os.path.getsize(p)
        files[files.index((fname, label, _))] = (fname, label, sz)
        log(f"{fname}: {sz//1024//1024}MB")

    # Phase 1: Find
    print(f"\n{'─'*40}\nPhase 1: Device Discovery\n{'─'*40}")
    devices, _ = find_device()
    if not devices:
        log("Device not found!", "FAIL")
        log("→ Enter USB download mode: power off → hold reset → USB in → release", "WARN")
        sys.exit(1)

    # Phase 2: Open
    print(f"\n{'─'*40}\nPhase 2: Open Device\n{'─'*40}")
    method, handle1, handle2 = try_winusb(devices)
    if method == "none":
        method, handle1, handle2 = try_pyusb(devices)
    if method == "none":
        log("Cannot open device with any method", "FAIL")
        sys.exit(1)
    log(f"Opened via: {method}", "OK")

    # Phase 3: Burn
    print(f"\n{'─'*40}\nPhase 3: Flashing\n{'─'*40}")
    total = len(files)
    for i, (fname, label, _) in enumerate(files):
        p = os.path.join(img, fname)
        if method == "winusb":
            if not upload_winusb(handle2, p, label, i+1, total):
                kernel32.CloseHandle(handle1)
                sys.exit(1)
        elif method == "pyusb":
            if not upload_pyusb(handle1, p, label, i+1, total):
                sys.exit(1)
        time.sleep(1)

    # Cleanup
    if method == "winusb":
        kernel32.CloseHandle(handle1)

    print(f"\n{'─'*40}")
    log("ALL DONE! Power cycle the box.", "OK")
    print("─" * 40)


if __name__ == "__main__":
    main()
