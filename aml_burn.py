#!/usr/bin/env python3
"""Amlogic Burn Tool — MAXIMUM VERBOSE DEBUG. Every byte logged."""
import sys, os, time, traceback
import usb.core, usb.util

VID, PID = 0x1B8E, 0xC003
LOG_FILE = "aml_burn.log"


def log(msg, level="INFO"):
    line = f"[{time.strftime('%H:%M:%S')}] [{level}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def usb_error_str(e):
    return f"{type(e).__name__}: {e}"


def main():
    img = sys.argv[1] if len(sys.argv) > 1 else "."
    log("=" * 60)
    log("Amlogic Burn Tool — MAXIMUM VERBOSE DEBUG")
    log(f"Image dir: {img}")
    log(f"Log file: {LOG_FILE}")
    log("=" * 60)

    # ======================== PHASE 0: Device ========================
    log("\n>>> PHASE 0: Device Discovery")
    devs = list(usb.core.find(find_all=True, idVendor=VID, idProduct=PID))
    log(f"Devices found: {len(devs)}")
    if not devs:
        log("FATAL: No device", "ERROR")
        sys.exit(1)

    dev = devs[0]
    log(f"Device: {dev}")
    log(f"  bus={dev.bus} addr={dev.address} port={getattr(dev,'port_number','?')}")
    log(f"  speed={dev.speed} (2=HS 480Mbps, 3=SS 5Gbps)")
    log(f"  manufacturer={dev.manufacturer} product={dev.product}")
    log(f"  configurations={dev.bNumConfigurations}")

    # USB Descriptor dump
    try:
        raw = dev.ctrl_transfer(0x80, 0x06, 0x0100, 0x0000, 18, timeout=1000)
        log(f"  DeviceDesc: {' '.join(f'{b:02x}' for b in raw)}")
    except Exception as e:
        log(f"  DeviceDesc read failed: {usb_error_str(e)}", "WARN")

    # ======================== PHASE 1: USB Init ========================
    log("\n>>> PHASE 1: USB Initialization")
    try:
        dev.set_configuration()
        log("set_configuration: OK")
    except Exception as e:
        log(f"set_configuration: {usb_error_str(e)}", "WARN")
        try:
            dev.reset()
            time.sleep(1)
            dev.set_configuration()
            log("reset + set_configuration: OK")
        except Exception as e2:
            log(f"reset failed: {usb_error_str(e2)}", "ERROR")

    try:
        usb.util.claim_interface(dev, 0)
        log("claim_interface(0): OK")
    except Exception as e:
        log(f"claim_interface(0): {usb_error_str(e)}", "WARN")

    # Active config info
    try:
        cfg = dev.get_active_configuration()
        for intf in cfg:
            log(f"  Interface {intf.bInterfaceNumber}:")
            for ep in intf:
                log(f"    EP {ep.bEndpointAddress:#04x} type={ep.bmAttributes} max={ep.wMaxPacketSize}")
    except Exception as e:
        log(f"Active config read failed: {usb_error_str(e)}", "WARN")

    # ======================== PHASE 2: USB Probe ========================
    log("\n>>> PHASE 2: USB Transfer Probe")

    # Load DDR data
    ddr_path = os.path.join(img, "DDR.USB")
    with open(ddr_path, "rb") as f:
        ddr = f.read()
    log(f"DDR.USB loaded: {len(ddr)} bytes")

    # Probe results tracker
    results = {}

    # Test 1: Bulk OUT 1 byte
    log("\n--- Test 1: Bulk OUT, 1 byte ---")
    try:
        t = time.time()
        n = dev.write(0x02, ddr[:1], timeout=3000)
        dt = time.time() - t
        log(f"  wrote {n} byte in {dt*1000:.0f}ms")
        results['bulk_1'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['bulk_1'] = False

    # Test 2: Bulk OUT 64 bytes
    log("\n--- Test 2: Bulk OUT, 64 bytes ---")
    try:
        t = time.time()
        n = dev.write(0x02, ddr[:64], timeout=3000)
        dt = time.time() - t
        log(f"  wrote {n} bytes in {dt*1000:.0f}ms")
        results['bulk_64'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['bulk_64'] = False

    # Test 3: Bulk OUT 512 bytes
    log("\n--- Test 3: Bulk OUT, 512 bytes ---")
    try:
        t = time.time()
        n = dev.write(0x02, ddr[:512], timeout=5000)
        dt = time.time() - t
        log(f"  wrote {n} bytes in {dt*1000:.0f}ms")
        results['bulk_512'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['bulk_512'] = False

    # Test 4: Bulk OUT 4096 bytes
    log("\n--- Test 4: Bulk OUT, 4096 bytes ---")
    try:
        t = time.time()
        n = dev.write(0x02, ddr[:4096], timeout=10000)
        dt = time.time() - t
        log(f"  wrote {n} bytes in {dt*1000:.0f}ms")
        results['bulk_4K'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['bulk_4K'] = False

    # Test 5: Control OUT bRequest=0x01 (identify)
    log("\n--- Test 5: Control OUT bRequest=0x01, 8 bytes ---")
    try:
        t = time.time()
        dev.ctrl_transfer(0x40, 0x01, 0, 0, ddr[:8], timeout=3000)
        dt = time.time() - t
        log(f"  OK in {dt*1000:.0f}ms")
        results['ctrl_01'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['ctrl_01'] = False

    # Test 6: Control OUT bRequest=0x03 (write memory)
    log("\n--- Test 6: Control OUT bRequest=0x03, 64 bytes ---")
    try:
        t = time.time()
        dev.ctrl_transfer(0x40, 0x03, 0, 0, ddr[:64], timeout=3000)
        dt = time.time() - t
        log(f"  OK in {dt*1000:.0f}ms")
        results['ctrl_03'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['ctrl_03'] = False

    # Test 7: Control OUT bRequest=0x03, 512 bytes
    log("\n--- Test 7: Control OUT bRequest=0x03, 512 bytes ---")
    try:
        t = time.time()
        dev.ctrl_transfer(0x40, 0x03, 0, 0, ddr[:512], timeout=5000)
        dt = time.time() - t
        log(f"  OK in {dt*1000:.0f}ms")
        results['ctrl_03_512'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['ctrl_03_512'] = False

    # Test 8: Control OUT bRequest=0x03, 4096 bytes
    log("\n--- Test 8: Control OUT bRequest=0x03, 4096 bytes ---")
    try:
        t = time.time()
        dev.ctrl_transfer(0x40, 0x03, 0, 0, ddr[:4096], timeout=10000)
        dt = time.time() - t
        log(f"  OK in {dt*1000:.0f}ms")
        results['ctrl_03_4K'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['ctrl_03_4K'] = False

    # Test 9: Control OUT bRequest=0x03 with address in wValue
    log("\n--- Test 9: Control OUT bRequest=0x03, wValue=0x1234, 64 bytes ---")
    try:
        t = time.time()
        dev.ctrl_transfer(0x40, 0x03, 0x1234, 0, ddr[:64], timeout=3000)
        dt = time.time() - t
        log(f"  OK in {dt*1000:.0f}ms")
        results['ctrl_03_addr'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['ctrl_03_addr'] = False

    # Test 10: Control OUT bRequest=0x03, 65536 bytes (max)
    log("\n--- Test 10: Control OUT bRequest=0x03, 65536 bytes ---")
    try:
        t = time.time()
        dev.ctrl_transfer(0x40, 0x03, 0, 0, ddr[:65536], timeout=15000)
        dt = time.time() - t
        log(f"  OK in {dt*1000:.0f}ms")
        results['ctrl_03_max'] = True
    except Exception as e:
        log(f"  FAIL: {usb_error_str(e)}")
        results['ctrl_03_max'] = False

    # ======================== PHASE 3: Results ========================
    log("\n" + "=" * 60)
    log("PROBE RESULTS SUMMARY")
    log("=" * 60)
    for k, v in results.items():
        log(f"  {k}: {'✅ PASS' if v else '❌ FAIL'}")
    log("")

    # Determine best method
    if results.get('ctrl_03_max'):
        log("Best: Control OUT bRequest=0x03, 64KB chunks")
        method = ('ctrl', 0x03, 65536)
    elif results.get('ctrl_03_4K'):
        log("Best: Control OUT bRequest=0x03, 4KB chunks")
        method = ('ctrl', 0x03, 4096)
    elif results.get('ctrl_03_512'):
        log("Best: Control OUT bRequest=0x03, 512B chunks")
        method = ('ctrl', 0x03, 512)
    elif results.get('ctrl_03'):
        log("Best: Control OUT bRequest=0x03, 64B chunks")
        method = ('ctrl', 0x03, 64)
    elif results.get('bulk_4K'):
        log("Best: Bulk OUT, 4KB chunks")
        method = ('bulk', 0, 4096)
    elif results.get('bulk_512'):
        log("Best: Bulk OUT, 512B chunks")
        method = ('bulk', 0, 512)
    elif results.get('bulk_64'):
        log("Best: Bulk OUT, 64B chunks")
        method = ('bulk', 0, 64)
    else:
        log("NO WORKING TRANSFER METHOD FOUND!", "ERROR")
        log("This xHCI controller cannot communicate with Amlogic Boot ROM.", "ERROR")
        log("Hardware workaround required: USB 2.0 hub or different computer.", "ERROR")
        sys.exit(1)

    # ======================== PHASE 4: Upload ========================
    log(f"\n>>> PHASE 4: Upload DDR.USB via {method}")

    dtype, breq, csz = method
    pos = 0
    start = time.time()
    total = len(ddr)
    packets = (total + csz - 1) // csz

    while pos < total:
        chunk = ddr[pos:pos + csz]
        pkt = pos // csz
        try:
            if dtype == 'ctrl':
                dev.ctrl_transfer(0x40, breq, 0, 0, chunk, timeout=15000)
            else:
                dev.write(0x02, chunk, timeout=15000)
            pos += len(chunk)
        except Exception as e:
            log(f"  Packet {pkt}/{packets} FAIL: {usb_error_str(e)}", "ERROR")
            log(f"  Transfer stopped at {pos//1024}KB / {total//1024}KB", "ERROR")
            sys.exit(1)

        if pkt % max(1, packets // 20) == 0:
            pct = pos * 100 // total
            elapsed = time.time() - start
            kbps = (pos / 1024) / elapsed if elapsed > 0 else 0
            log(f"  Packet {pkt}/{packets}: {pct}%  {kbps:.0f}KB/s")

    log(f"DDR.USB uploaded in {time.time()-start:.0f}s")

    # ======================== DONE ========================
    log("\n" + "=" * 60)
    log("ALL PHASES COMPLETE!")
    log("=" * 60)


if __name__ == "__main__":
    main()
