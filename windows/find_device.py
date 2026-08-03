#!/usr/bin/env python3
"""Find Amlogic device — scan ALL methods."""
import ctypes
from ctypes import wintypes, byref, Structure, sizeof

setupapi = ctypes.windll.setupapi
kernel32 = ctypes.windll.kernel32

DIGCF_ALLCLASSES = 0x04
DIGCF_DEVICEINTERFACE = 0x10
DIGCF_PRESENT = 0x02
SPDRP_HARDWAREID = 1
SPDRP_DEVICEDESC = 0  # Device description
SPDRP_CLASS = 7
SPDRP_DRIVER = 9
GENERIC_WRITE = 0x40000000
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# WinUSB GUID
WINUSB_GUID = (ctypes.c_ubyte * 16)(
    0xDE, 0xE8, 0x24, 0x3F, 0x53, 0xB9, 0xF5, 0x45,
    0x86, 0xD9, 0x2D, 0xA6, 0x74, 0x4A, 0x15, 0x21
)

class SP_DEVINFO_DATA(Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", ctypes.c_ubyte * 16),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]

print("=== Method 1: All devices ===")
hdi = setupapi.SetupDiGetClassDevsA(None, None, None, DIGCF_PRESENT)
if hdi != INVALID_HANDLE_VALUE:
    dev_data = SP_DEVINFO_DATA()
    dev_data.cbSize = sizeof(SP_DEVINFO_DATA)
    idx = 0
    while setupapi.SetupDiEnumDeviceInfo(hdi, idx, byref(dev_data)):
        idx += 1
        buf = ctypes.create_string_buffer(256)
        if setupapi.SetupDiGetDeviceRegistryPropertyA(hdi, byref(dev_data), SPDRP_HARDWAREID, None, buf, 256, None):
            hwid = buf.value.decode('utf-8', errors='ignore')
            if '1b8e' in hwid.lower() or 'c003' in hwid.lower():
                print(f"  [{idx}] {hwid}")
                # Get description
                buf2 = ctypes.create_string_buffer(256)
                setupapi.SetupDiGetDeviceRegistryPropertyA(hdi, byref(dev_data), SPDRP_DEVICEDESC, None, buf2, 256, None)
                print(f"       Desc: {buf2.value.decode('utf-8', errors='ignore')}")
                # Get instance ID
                buf3 = ctypes.create_unicode_buffer(256)
                setupapi.SetupDiGetDeviceInstanceIdW(hdi, byref(dev_data), buf3, 256, None)
                print(f"       InstID: {buf3.value}")
                # Get driver
                buf4 = ctypes.create_string_buffer(256)
                setupapi.SetupDiGetDeviceRegistryPropertyA(hdi, byref(dev_data), SPDRP_DRIVER, None, buf4, 256, None)
                print(f"       Driver: {buf4.value.decode('utf-8', errors='ignore')}")
    setupapi.SetupDiDestroyDeviceInfoList(hdi)
    if idx == 0:
        print("  No devices found at all!")
else:
    print("  Failed to enumerate")

print("\n=== Method 2: WinUSB device interfaces ===")
hdi2 = setupapi.SetupDiGetClassDevsA(WINUSB_GUID, None, None, 
    DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
if hdi2 != INVALID_HANDLE_VALUE:
    print(f"  HDI: {hdi2}")
    dev_data = SP_DEVINFO_DATA()
    dev_data.cbSize = sizeof(SP_DEVINFO_DATA)
    idx = 0
    while setupapi.SetupDiEnumDeviceInfo(hdi2, idx, byref(dev_data)):
        idx += 1
        print(f"  Found WinUSB device #{idx}")
    setupapi.SetupDiDestroyDeviceInfoList(hdi2)
    if idx == 0:
        print("  No WinUSB devices found → driver is NOT WinUSB!")
else:
    err = kernel32.GetLastError()
    print(f"  Failed: error {err} → probably not WinUSB driver")

print("\n=== Method 3: USB class ===")
hdi3 = setupapi.SetupDiGetClassDevsA(None, "USB", None, DIGCF_PRESENT)
if hdi3 != INVALID_HANDLE_VALUE:
    dev_data = SP_DEVINFO_DATA()
    dev_data.cbSize = sizeof(SP_DEVINFO_DATA)
    idx = 0
    while setupapi.SetupDiEnumDeviceInfo(hdi3, idx, byref(dev_data)):
        idx += 1
        buf = ctypes.create_string_buffer(256)
        if setupapi.SetupDiGetDeviceRegistryPropertyA(hdi3, byref(dev_data), SPDRP_HARDWAREID, None, buf, 256, None):
            hwid = buf.value.decode('utf-8', errors='ignore')
            if '1b8e' in hwid.lower():
                print(f"  [{idx}] {hwid}")
                buf3 = ctypes.create_unicode_buffer(256)
                setupapi.SetupDiGetDeviceInstanceIdW(hdi3, byref(dev_data), buf3, 256, None)
                print(f"       InstID: {buf3.value}")
    setupapi.SetupDiDestroyDeviceInfoList(hdi3)
    if idx == 0:
        print("  No USB devices found")
else:
    print("  Failed to enumerate USB class")

print("\n=== Done ===")
