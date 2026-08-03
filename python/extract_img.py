#!/usr/bin/env python3
"""Extract Amlogic .img into DDR.USB, UBOOT.USB, boot.PARTITION, system.PARTITION."""
import sys
import os


def extract(img_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(img_path, "rb") as f:
        data = f.read()

    print(f"Image: {len(data)//1024//1024}MB")

    # Amlogic GXL burn image layout:
    # DDR.USB:  offset 0,     size varies (~48KB typically)
    # UBOOT.USB: follows DDR, size varies (~672KB for GXL)
    # boot:      FAT32 partition at known boundary (64MB)
    # system:    ext4 partition at boot end

    fat_magic = b"MSDOS5.0"
    ext_magic = b"\x53\xef"

    fat_pos = data.find(fat_magic)
    if fat_pos < 0:
        print("ERROR: FAT32 boot partition not found")
        sys.exit(1)

    boot_start = fat_pos - 3  # boot sector offset 3 = OEM name

    # DDR.USB + UBOOT.USB + config files are before boot
    # DDR is first ~48KB, UBOOT follows to boot_start
    ddr_size = min(48 * 1024, boot_start)
    uboot_size = boot_start - ddr_size

    # DDR.USB
    with open(os.path.join(out_dir, "DDR.USB"), "wb") as f:
        f.write(data[:ddr_size])
    print(f"  DDR.USB: {ddr_size//1024}KB")

    # UBOOT.USB
    with open(os.path.join(out_dir, "UBOOT.USB"), "wb") as f:
        f.write(data[ddr_size:boot_start])
    print(f"  UBOOT.USB: {uboot_size//1024}KB")

    # System starts after 64MB boot
    system_start = boot_start + 64 * 1024 * 1024
    ext_search = max(0, system_start - 4096)
    ext_pos = data[ext_search:ext_search + 65536].find(ext_magic)
    if ext_pos > 0:
        system_start = ext_search + ext_pos - 0x438
        print(f"  system: found at 0x{system_start:x}")

    # boot.PARTITION
    with open(os.path.join(out_dir, "boot.PARTITION"), "wb") as f:
        f.write(data[boot_start:system_start])
    print(f"  boot.PARTITION: {(system_start - boot_start)//1024//1024}MB")

    # system.PARTITION
    with open(os.path.join(out_dir, "system.PARTITION"), "wb") as f:
        f.write(data[system_start:])
    print(f"  system.PARTITION: {(len(data) - system_start)//1024//1024}MB")

    print(f"\nDone! python aml_burn.py {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python extract_img.py <image.img> <output_dir>")
        sys.exit(1)
    extract(sys.argv[1], sys.argv[2])
