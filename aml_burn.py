#!/usr/bin/env python3
"""Amlogic Burn — Native WinUSB (bypass libusb entirely)."""
import sys, os, time, ctypes
from ctypes import wintypes, byref, Structure, sizeof, POINTER

# Win32 types
ULONG = wintypes.ULONG
HANDLE = wintypes.HANDLE
LPVOID = wintypes.LPVOID
BOOL = wintypes.BOOL
GUID_STRUCT = ctypes.c_ubyte * 16

# WinUSB GUID {3f24e8de-b953-45f5-86d9-2da6744a1521}
WINUSB_GUID = GUID_STRUCT(
    0xDE, 0xE8, 0x24, 0x3F, 0x53, 0xB9, 0xF5, 0x45,
    0x86, 0xD9, 0x2D, 0xA6, 0x74, 0x4A, 0x15, 0x21
)

# Win32 API
kernel32 = ctypes.windll.kernel32
setupapi = ctypes.windll.setupapi
winusb_dll = ctypes.windll.winusb

# Constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = HANDLE(-1).value
DIGCF_PRESENT = 2
SPDRP_HARDWAREID = 1

TIMEOUT = 10000
CHUNK = 1024 * 1024


class SP_DEVINFO_DATA(Structure):
    _fields_ = [
        ("cbSize", ULONG),
        ("ClassGuid", ctypes.c_ubyte * 16),
        ("DevInst", ULONG),
        ("Reserved", LPVOID),
    ]


def enum_usb_devices():
    """Find all USB devices with Amlogic VID/PID via SetupAPI."""
    hdi = setupapi.SetupDiGetClassDevsA(None, "USB", None,
        DIGCF_PRESENT)
    if hdi == INVALID_HANDLE_VALUE:
        return []

    results = []
    dev_data = SP_DEVINFO_DATA()
    dev_data.cbSize = sizeof(SP_DEVINFO_DATA)

    idx = 0
    while setupapi.SetupDiEnumDeviceInfo(hdi, idx, byref(dev_data)):
        idx += 1
        buf = ctypes.create_string_buffer(256)
        if setupapi.SetupDiGetDeviceRegistryPropertyA(
            hdi, byref(dev_data), SPDRP_HARDWAREID, None, buf, 256, None):
            hwid = buf.value.decode('utf-8', errors='ignore').lower()
            if "vid_1b8e" in hwid and "pid_c003" in hwid:
                # Get device path
                buf2 = ctypes.create_unicode_buffer(512)
                if setupapi.SetupDiGetDeviceInstanceIdW(
                    hdi, byref(dev_data), buf2, 512, None):
                    # Build WinUSB path
                    guid_str = "{3f24e8de-b953-45f5-86d9-2da6744a1521}"
                    path = f"\\\\?\\usb#vid_1b8e&pid_c003#{buf2.value}#{guid_str}"
                    results.append(path)

    setupapi.SetupDiDestroyDeviceInfoList(hdi)
    return results


def open_winusb():
    """Open Amlogic device via WinUSB."""
    paths = enum_usb_devices()
    if not paths:
        print("ERROR: Device not found. Install WinUSB driver via Zadig!")
        print("  Zadig: Driver → WinUSB (not libusb-win32, not libusbK)")
        sys.exit(1)

    path = paths[0]
    print(f"  Path: {path}")
    
    # Open device
    h = kernel32.CreateFileW(
        path,
        GENERIC_WRITE,
        FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_OVERLAPPED,
        None,
    )
    if h == INVALID_HANDLE_VALUE:
        err = kernel32.GetLastError()
        print(f"ERROR: CreateFile failed ({err})")
        print("Make sure WinUSB driver is installed (Zadig → WinUSB)")
        sys.exit(1)

    # Initialize WinUSB
    wh = HANDLE()
    if not winusb_dll.WinUsb_Initialize(h, byref(wh)):
        err = kernel32.GetLastError()
        kernel32.CloseHandle(h)
        print(f"ERROR: WinUsb_Initialize failed ({err})")
        sys.exit(1)

    print("  WinUSB initialized OK")
    return h, wh


def upload(wh, path, name):
    """Upload file via WinUSB bulk pipe."""
    with open(path, "rb") as f:
        data = f.read()
    total = len(data)
    buf = (ctypes.c_ubyte * CHUNK)()
    pos = 0

    while pos < total:
        chunk = data[pos:pos + CHUNK]
        ctypes.memmove(buf, chunk, len(chunk))
        written = ULONG()

        if not winusb_dll.WinUsb_WritePipe(wh, 0x02, buf, len(chunk),
                                            byref(written), None):
            err = kernel32.GetLastError()
            print(f"\n  WinUsb_WritePipe failed at {pos//1024//1024}MB: error {err}")
            return False

        pos += len(chunk)
        pct = pos * 100 // total
        if pos % (CHUNK * 5) == 0 or pos >= total:
            print(f"\r  {name}: {pct}% ({pos//1024//1024}MB / {total//1024//1024}MB)", end="")

    print()
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python aml_burn.py <dir>")
        sys.exit(1)

    d = sys.argv[1]
    files = [
        ("DDR.USB", "DDR", 0),
        ("UBOOT.USB", "UBOOT", 0),
        ("boot.PARTITION", "boot", 0),
        ("system.PARTITION", "system", 0),
    ]

    for fname, _, _ in files:
        p = os.path.join(d, fname)
        if not os.path.isfile(p):
            print(f"Missing: {fname}")
            sys.exit(1)

    print("=" * 50)
    print(" Amlogic Burn — Native WinUSB")
    print("=" * 50)

    h, wh = open_winusb()

    for i, (fname, label, _) in enumerate(files):
        p = os.path.join(d, fname)
        mb = os.path.getsize(p) // 1024 // 1024
        print(f"\n[{i+1}/4] {label} ({mb}MB)")
        if not upload(wh, p, label):
            print("FAILED!")
            kernel32.CloseHandle(h)
            sys.exit(1)
        time.sleep(1)

    kernel32.CloseHandle(h)
    print("\nDone! Power cycle the box.\n")


if __name__ == "__main__":
    main()
