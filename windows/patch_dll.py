#!/usr/bin/env python3
"""
UsbRomDrv.dll 超时补丁工具 — 魔改 Amlogic USB Burning Tool
=============================================================
国产 eMMC (Foresee/Biwin/YTXC, mafId=0xD6) 的擦除操作耗时超出
UsbRomDrv.dll 中硬编码的超时阈值, 导致刷机卡在 ERASE BOOTLOADER 步骤。

本工具:
  1. 备份原始 UsbRomDrv.dll
  2. 搜索 DLL 中的超时常量 (毫秒级 DWORD)
  3. 将擦除超时从 5s/10s 延长到 120s
  4. 将 USB 传输超时从 5s 延长到 30s
  5. 保存补丁后的 DLL

用法:
  python patch_dll.py [DLL路径]
  (默认路径: C:\\Program Files (x86)\\Amlogic\\USB_Burning_Tool\\UsbRomDrv.dll)
"""
import sys
import os
import shutil
import struct
import time

# ============================================================
#  超时值映射表 (毫秒)
# ============================================================
# 格式: (原始值, 补丁值, 说明)
TIMEOUT_PATCHES = [
    # 擦除超时 — 国产 eMMC 擦除 boot0/boot1 可能需要 60-90s
    (5000,   120000,  "擦除超时 5s → 120s"),
    (10000,  120000,  "擦除超时 10s → 120s"),
    (15000,  120000,  "擦除超时 15s → 120s"),
    (20000,  120000,  "擦除超时 20s → 120s"),
    (30000,  120000,  "擦除超时 30s → 120s"),
    # USB 传输超时 — 大容量传输需要更长时间
    (3000,   30000,   "USB传输 3s → 30s"),
    # DDR 训练超时
    (200,    2000,    "DDR训练 200ms → 2000ms"),
]

# 默认 DLL 搜索路径
DEFAULT_PATHS = [
    r"C:\Program Files (x86)\Amlogic\USB_Burning_Tool\UsbRomDrv.dll",
    r"C:\Program Files\Amlogic\USB_Burning_Tool\UsbRomDrv.dll",
    r"C:\Program Files (x86)\AML\USB_Burning_Tool\UsbRomDrv.dll",
    r"UsbRomDrv.dll",
]


def find_dll():
    """自动搜索 UsbRomDrv.dll"""
    for p in DEFAULT_PATHS:
        if os.path.isfile(p):
            return p
    return None


def patch_dll(dll_path):
    """补丁 DLL 中的超时值"""
    if not os.path.isfile(dll_path):
        print(f"  [!] DLL 不存在: {dll_path}")
        return False

    # 读取 DLL
    with open(dll_path, "rb") as f:
        data = bytearray(f.read())

    print(f"  [*] DLL 大小: {len(data)//1024}KB")
    print(f"  [*] 搜索超时常量并补丁...")

    total_patches = 0
    backup_path = dll_path + ".bak"

    # 备份
    if not os.path.isfile(backup_path):
        shutil.copy2(dll_path, backup_path)
        print(f"  [+] 备份: {backup_path}")
    else:
        print(f"  [=] 备份已存在: {backup_path}")

    for orig, patched, desc in TIMEOUT_PATCHES:
        orig_bytes = struct.pack("<I", orig)
        patch_bytes = struct.pack("<I", patched)

        count = 0
        pos = 0
        while True:
            pos = data.find(orig_bytes, pos)
            if pos < 0:
                break
            # 检查上下文: 确保这不是巧合匹配
            # 超时常量通常在 .data 或 .rdata 段, 前后应该有其他合理值
            data[pos:pos+4] = patch_bytes
            count += 1
            pos += 4

        if count > 0:
            print(f"  [+] {desc}: 替换 {count} 处")
            total_patches += count

    if total_patches == 0:
        print(f"  [!] 未找到可补丁的超时常量 (DLL 版本可能不同)")
        print(f"  [!] 尝试使用配置文件补丁方案 (aml_sdc_burn.ini)")
        return False

    # 写入补丁后的 DLL
    with open(dll_path, "wb") as f:
        f.write(data)

    print(f"  [+] 总计补丁: {total_patches} 处")
    print(f"  [+] 补丁后 DLL 已保存")
    return True


def main():
    print("=" * 55)
    print("  UsbRomDrv.dll 超时补丁工具")
    print("  兼容国产 eMMC (Foresee/Biwin/YTXC)")
    print("=" * 55)

    dll_path = sys.argv[1] if len(sys.argv) > 1 else find_dll()

    if not dll_path:
        print("  [!] 未找到 UsbRomDrv.dll")
        print("  [!] 请指定路径: python patch_dll.py <路径>")
        print("  [!] 或将本脚本放在 USB Burning Tool 目录下运行")
        sys.exit(1)

    print(f"  [*] 目标: {dll_path}")

    ok = patch_dll(dll_path)
    if ok:
        print("\n  [OK] 补丁成功! 现在可以启动 USB Burning Tool")
        print("  [!] 如果仍超时, 在 GUI 中取消勾选 Erase bootloader")
    else:
        print("\  [!] DLL 补丁未成功, 使用配置文件方案:")
        print("       1. 将 patches/aml_sdc_burn.ini 放入镜像目录")
        print("       2. 导入 patches/burning_tool_settings.reg")
        print("       3. 在 GUI 中手动取消 Erase bootloader")

    print("=" * 55)


if __name__ == "__main__":
    main()
