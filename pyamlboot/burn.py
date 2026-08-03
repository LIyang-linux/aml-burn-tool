#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0 OR MIT
"""
Amlogic USB Boot & Flash Tool — 基于 pyamlboot 协议库

两阶段加载烧录脚本，适配中兴 B860AV2.1-A (S905L3-B / GXL 平台)

启动链:
  ROM (BL1) → BL2 (DDR.USB) → TPL/U-Boot (UBOOT.USB) → eMMC 烧录

阶段 1 — ROM 模式 (VID=1b8e PID=c003, stage=0):
  ① 上传 DDR.USB (BL2) 到 0xd9000000
  ② 写入 BL2 参数到 0xd900c000 (U-Boot 加载地址 + 大小)
  ③ 运行 BL2 → 初始化 DDR 内存 → 设备重新枚举

阶段 2 — BL2 模式 (PID 不变, stage=8):
  ④ 上传 UBOOT.USB (TPL) 到 0x10000000
  ⑤ 运行 U-Boot → USB 烧录接口就绪

阶段 3 — U-Boot 烧录:
  ⑥ 通过 bulkCmd 擦除 + 写入各分区到 eMMC

用法:
  python burn.py <文件目录> [--no-flash] [--dry-run]
  python burn.py /path/to/files
  python burn.py /path/to/files --no-flash     # 只加载 U-Boot, 不烧录
  python burn.py /path/to/files --dry-run      # 检查文件, 不实际操作

依赖:
  pip install pyusb
  Linux: apt install libusb-1.0-0
  Windows: 通过 Zadig 安装 libusb0 或 WinUSB 驱动
"""
import sys
import os
import time
import struct
import argparse

# ---- 确保能导入同目录的 pyamlboot 包 ----
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import usb.core
    import usb.util
except ImportError:
    print("错误: 缺少 pyusb 依赖")
    print("  安装: pip install pyusb")
    sys.exit(1)

from pyamlboot.pyamlboot import AmlogicSoC

# ============================================================
#  平台常量 — GXL (S905L/S905L3/S905L3B)
# ============================================================

VID_AMLOGIC = 0x1b8e
PID_ROM     = 0xc003   # ROM/BL2 模式
PID_UBOOT   = 0xc004   # U-Boot 模式 (部分固件使用)

# 内存地址 (来自 platform.conf)
DDR_LOAD_ADDR  = 0xd9000000   # BL2 (DDR.USB) 加载地址
DDR_RUN_ADDR   = 0xd9000030   # BL2 运行入口 (部分平台 = DDR_LOAD + 0x30)
DDR_PRMS_ADDR  = 0xd900c000   # BL2 参数区
UBOOT_LOAD_ADDR = 0x10000000  # U-Boot (UBOOT.USB) 加载地址

# stage 值 (identify 返回的第 4 字节)
STAGE_ROM   = 0    # BL1 ROM
STAGE_BL2   = 8    # BL2/SPL (DDR 已初始化)
STAGE_TPL   = 16   # TPL/U-Boot

# USB 超时
USB_TIMEOUT      = 10000    # 10s 控制传输
BULK_TIMEOUT     = 30000    # 30s 批量传输
DEVICE_WAIT_MAX  = 30       # 等待设备重新枚举最大秒数

# 烧录分区定义
PARTITIONS = [
    {
        "name":   "bootloader",
        "file":   "bootloader.PARTITION",
        "cmd_erase":  "store erase bootloader",
        "cmd_write":  "download store bootloader normal {size}",
        "desc":   "U-Boot 引导 (写入 eMMC boot0/boot1)",
        "optional": False,
    },
    {
        "name":   "boot",
        "file":   "boot.PARTITION",
        "cmd_erase":  "store erase boot",
        "cmd_write":  "download store boot normal {size}",
        "desc":   "内核 + DTB + initramfs",
        "optional": False,
    },
    {
        "name":   "system",
        "file":   "system.PARTITION",
        "cmd_erase":  "store erase data",
        "cmd_write":  "download store system normal {size}",
        "desc":   "根文件系统",
        "optional": False,
    },
]


# ============================================================
#  工具函数
# ============================================================

def log(msg, end="\n"):
    print(f"  {msg}", end=end, flush=True)

def header(msg):
    print(f"\n{'='*60}", flush=True)
    print(f"  {msg}", flush=True)
    print(f"{'='*60}", flush=True)

def progress(msg, pct, speed=""):
    print(f"\r  {msg}{pct}% {speed:>12}", end="", flush=True)

def fmt_size(n):
    if n >= 1024*1024:
        return f"{n/1024/1024:.1f}MB"
    elif n >= 1024:
        return f"{n/1024:.0f}KB"
    return f"{n}B"


# ============================================================
#  设备查找 — 支持重新枚举后查找
# ============================================================

def find_device(vid=VID_AMLOGIC, pid=PID_ROM, timeout=DEVICE_WAIT_MAX):
    """查找 Amlogic USB 设备，支持超时等待"""
    start = time.time()
    while time.time() - start < timeout:
        dev = usb.core.find(idVendor=vid, idProduct=pid)
        if dev is not None:
            try:
                dev.set_configuration()
                usb.util.claim_interface(dev, 0)
            except usb.core.USBError:
                pass  # 可能已被内核驱动占用
            return dev
        time.sleep(0.2)
    return None

def find_device_any_pid(vid=VID_AMLOGIC, timeout=DEVICE_WAIT_MAX):
    """查找 Amlogic 设备 (任意 PID)"""
    start = time.time()
    while time.time() - start < timeout:
        for dev in usb.core.find(find_all=True, idVendor=vid):
            try:
                dev.set_configuration()
                usb.util.claim_interface(dev, 0)
            except usb.core.USBError:
                pass
            return dev
        time.sleep(0.2)
    return None

def release_device(dev):
    """释放 USB 设备资源"""
    if dev is not None:
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass


# ============================================================
#  阶段 1: ROM 模式 — 上传 BL2, 初始化 DDR
# ============================================================

def stage1_rom_upload(dev, ddr_data):
    """
    ROM 阶段: 上传 DDR.USB (BL2) 到 SRAM, 设置参数, 运行 BL2

    流程:
      1. identify → 确认 stage=0 (ROM)
      2. writeLargeMemory → 上传 BL2 到 0xd9000000
      3. writeMemory → 写入 BL2 参数 (U-Boot 地址 + 大小)
      4. run → 执行 BL2 (初始化 DDR)
    """
    soc = AmlogicSoC.__new__(AmlogicSoC)
    soc.dev = dev

    # 1. 确认 ROM 阶段
    log("[1/5] 识别芯片阶段...")
    try:
        raw = soc.identify()
        stage = raw[3] if len(raw) >= 4 else -1
        stage_name = {0: "ROM (BL1)", 8: "BL2/SPL", 16: "TPL/U-Boot"}.get(stage, f"未知({stage})")
        log(f"  芯片阶段: {stage_name}")
        if stage != STAGE_ROM:
            log(f"  警告: 期望 ROM 阶段(0), 实际为 {stage}")
            log(f"  设备可能已部分加载, 尝试继续...")
    except Exception as e:
        log(f"  identify 失败: {e} (继续尝试...)")

    # 2. 上传 BL2 (DDR.USB) 到 0xd9000000
    log(f"[2/5] 上传 BL2 (DDR.USB) → 0x{DDR_LOAD_ADDR:08x} ...")
    log(f"  大小: {fmt_size(len(ddr_data))}")
    t0 = time.time()
    try:
        soc.writeLargeMemory(DDR_LOAD_ADDR, ddr_data, blockLength=64, appendZeros=True)
    except Exception as e:
        log(f"  错误: 上传 BL2 失败: {e}")
        return False
    log(f"  完成 ({time.time()-t0:.1f}s)")

    # 3. 写入 BL2 参数
    # 参数结构: U-Boot 加载地址, 入口(0=默认), 大小, ...
    log(f"[3/5] 写入 BL2 参数 → 0x{DDR_PRMS_ADDR:08x} ...")
    params = struct.pack('<16I',
        UBOOT_LOAD_ADDR,   # U-Boot 加载地址
        0,                  # 入口 (0 = 使用加载地址)
        len(ddr_data),      # BL2 大小 (部分固件需要)
        0, 0, 0, 0, 0,      # reserved
        0, 0, 0, 0, 0, 0, 0, 0
    )
    try:
        soc.writeMemory(DDR_PRMS_ADDR, params)
    except Exception as e:
        log(f"  错误: 写入参数失败: {e}")
        return False
    log("  完成")

    # 4. 运行 BL2 — 初始化 DDR
    log(f"[4/5] 运行 BL2 (DDR 初始化) @ 0x{DDR_LOAD_ADDR:08x} ...")
    try:
        soc.run(DDR_LOAD_ADDR, keep_power=True)
    except Exception as e:
        # usb.core.USBError 是正常的 — 设备会断开重连
        if "timed out" in str(e).lower() or "pipe" in str(e).lower():
            log("  设备断开 (正常行为)")
        else:
            log(f"  注意: {e}")

    log("[5/5] BL2 已启动, 等待设备重新枚举...")
    return True


# ============================================================
#  阶段 2: BL2 模式 — 上传 U-Boot
# ============================================================

def stage2_bl2_upload(dev, uboot_data):
    """
    BL2 阶段: DDR 已初始化, 上传 UBOOT.USB 并运行

    流程:
      1. identify → 确认 stage=8 (BL2)
      2. writeLargeMemory → 上传 U-Boot 到 0x10000000
      3. run → 执行 U-Boot
    """
    soc = AmlogicSoC.__new__(AmlogicSoC)
    soc.dev = dev

    # 1. 确认 BL2 阶段
    log("[1/3] 识别芯片阶段...")
    try:
        raw = soc.identify()
        stage = raw[3] if len(raw) >= 4 else -1
        stage_name = {0: "ROM (BL1)", 8: "BL2/SPL", 16: "TPL/U-Boot"}.get(stage, f"未知({stage})")
        log(f"  芯片阶段: {stage_name}")
        if stage == STAGE_ROM:
            log("  警告: 仍然在 ROM 阶段, BL2 可能未成功运行")
            log("  尝试继续上传 U-Boot...")
        elif stage == STAGE_TPL:
            log("  U-Boot 已在运行 (跳过上传)")
            return True
    except Exception as e:
        log(f"  identify 失败: {e} (继续尝试...)")

    # 2. 上传 U-Boot (UBOOT.USB) 到 0x10000000
    log(f"[2/3] 上传 U-Boot (UBOOT.USB) → 0x{UBOOT_LOAD_ADDR:08x} ...")
    log(f"  大小: {fmt_size(len(uboot_data))}")
    t0 = time.time()
    try:
        soc.writeLargeMemory(UBOOT_LOAD_ADDR, uboot_data, blockLength=64, appendZeros=True)
    except Exception as e:
        log(f"  错误: 上传 U-Boot 失败: {e}")
        return False
    log(f"  完成 ({time.time()-t0:.1f}s)")

    # 3. 运行 U-Boot
    log(f"[3/3] 运行 U-Boot @ 0x{UBOOT_LOAD_ADDR:08x} ...")
    try:
        soc.run(UBOOT_LOAD_ADDR, keep_power=True)
    except Exception as e:
        if "timed out" in str(e).lower() or "pipe" in str(e).lower():
            log("  设备响应中断 (正常行为)")
        else:
            log(f"  注意: {e}")

    log("U-Boot 启动中...")
    return True


# ============================================================
#  阶段 3: U-Boot 烧录 — 擦除 + 写入分区
# ============================================================

def wait_for_uboot(dev, timeout=15):
    """等待 U-Boot USB 接口就绪"""
    log("等待 U-Boot 就绪...")
    for i in range(timeout * 5):
        time.sleep(0.2)
        try:
            # 发送 nop 确认 U-Boot 在响应
            soc = AmlogicSoC.__new__(AmlogicSoC)
            soc.dev = dev
            soc.nop()
            log(f"U-Boot 就绪 ({i*0.2:.0f}s)")
            return True
        except Exception:
            continue
    log("警告: U-Boot 未响应 nop, 尝试继续...")
    return False

def send_bulk_cmd(dev, cmd, read_response=True):
    """发送 bulkcmd 到 U-Boot, 可选读取响应"""
    soc = AmlogicSoC.__new__(AmlogicSoC)
    soc.dev = dev
    try:
        soc.bulkCmd(cmd)
    except Exception as e:
        log(f"  bulkCmd 异常: {e}")
        return ""

    if not read_response:
        return ""

    # 读取响应 (从 bulk IN 端点)
    time.sleep(0.3)
    try:
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
        )
        if ep_in is not None:
            data = ep_in.read(512, timeout=3000)
            return bytes(data).decode(errors='ignore')
    except Exception:
        pass
    return ""

def send_bulk_data(dev, data, chunk_size=512*1024):
    """通过 bulk OUT 端点发送分区数据"""
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
    )
    if ep_out is None:
        log("  错误: 找不到 bulk OUT 端点")
        return False

    total = len(data)
    offset = 0
    t0 = time.time()
    last_pct = -1
    retry_count = 0
    MAX_RETRIES = 30

    while offset < total:
        actual_len = min(chunk_size, total - offset)
        chunk = data[offset:offset + actual_len]
        # 对齐到 64 字节 (USB 控制传输要求)
        padded = chunk
        if len(padded) % 64 != 0:
            padded = padded + b'\x00' * (64 - len(padded) % 64)

        try:
            ep_out.write(padded, timeout=BULK_TIMEOUT)
            offset += actual_len  # 按实际数据量前进, 不含 padding
            retry_count = 0
        except Exception as e:
            retry_count += 1
            if retry_count > MAX_RETRIES:
                log(f"\n  错误: 传输失败, 重试超过 {MAX_RETRIES} 次")
                return False
            log(f"\n  传输异常 @ {fmt_size(offset)}: {e}, 重试 {retry_count}/{MAX_RETRIES}")
            time.sleep(0.3)
            continue

        pct = offset * 100 // total
        if pct != last_pct:
            elapsed = max(0.01, time.time() - t0)
            speed = f"{offset/1024/elapsed:.0f}KB/s"
            eta = f"~{(total-offset)/1024/max(1,offset/1024/elapsed):.0f}s"
            progress("  写入", pct, f"{speed} {eta}")
            last_pct = pct

    elapsed = time.time() - t0
    log(f"\n  传输完成: {fmt_size(total)} / {elapsed:.1f}s / {total/1024/elapsed:.0f}KB/s")
    return True

def flash_partition(dev, part, base_dir):
    """擦除并写入单个分区"""
    name = part["name"]
    file_path = os.path.join(base_dir, part["file"])

    log(f"\n--- 烧录分区: {name} ({part['desc']}) ---")

    if not os.path.isfile(file_path):
        if part.get("optional"):
            log(f"  跳过: 文件不存在 ({part['file']})")
            return True
        log(f"  错误: 文件不存在: {file_path}")
        return False

    data = open(file_path, "rb").read()
    size = len(data)
    log(f"  文件: {part['file']} ({fmt_size(size)})")

    # 1. 擦除分区
    log(f"  擦除 {name} ...")
    resp = send_bulk_cmd(dev, part["cmd_erase"])
    if resp:
        log(f"  擦除响应: {resp.strip()[:80]}")
    time.sleep(1)  # 等待擦除完成

    # 2. 准备下载
    cmd = part["cmd_write"].format(size=size)
    log(f"  下载命令: {cmd}")
    resp = send_bulk_cmd(dev, cmd)
    if resp:
        log(f"  响应: {resp.strip()[:80]}")
    time.sleep(0.5)

    # 3. 发送数据
    log(f"  传输数据 ...")
    ok = send_bulk_data(dev, data)
    if not ok:
        log(f"  错误: 数据传输失败")
        return False

    # 4. 保存
    time.sleep(0.5)
    log(f"  保存 ...")
    resp = send_bulk_cmd(dev, "save")
    if resp:
        log(f"  保存响应: {resp.strip()[:80]}")
    time.sleep(1)

    log(f"  {name} 烧录完成")
    return True


# ============================================================
#  文件检查
# ============================================================

def check_files(base_dir, dry_run=False):
    """检查所需文件是否齐全"""
    log("检查烧录文件...")
    required = ["DDR.USB", "UBOOT.USB"]
    for part in PARTITIONS:
        if not part.get("optional"):
            required.append(part["file"])

    all_found = True
    for fname in required:
        path = os.path.join(base_dir, fname)
        if os.path.isfile(path):
            size = os.path.getsize(path)
            log(f"  [OK] {fname:30s} {fmt_size(size):>10s}")
        else:
            tag = "可选" if any(p["file"] == fname and p.get("optional") for p in PARTITIONS) else "缺失"
            log(f"  [{tag}] {fname:30s}")
            if tag == "缺失":
                all_found = False

    if not all_found:
        log("\n错误: 必需文件缺失!")
        return False

    log("文件检查通过")
    return True


# ============================================================
#  主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Amlogic USB Boot & Flash Tool (pyamlboot)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python burn.py /path/to/files              # 完整烧录
  python burn.py /path/to/files --no-flash   # 只加载 U-Boot 不烧录
  python burn.py /path/to/files --dry-run    # 只检查文件
  python burn.py /path/to/files --skip-bl    # 跳过 bootloader 分区

进入 USB 烧录模式:
  1. 拔掉电源, 用 USB 线连接盒子
  2. 用牙签/回形针按住 reset 孔 (或短接 AV 口触点)
  3. 插上电源, 2 秒后松开 reset
  4. 设备应出现在 USB 设备列表中 (VID=1b8e PID=c003)
        """
    )
    parser.add_argument("dir", nargs="?", default=".",
                        help="烧录文件所在目录 (默认当前目录)")
    parser.add_argument("--no-flash", action="store_true",
                        help="只加载 U-Boot 到内存, 不烧录 eMMC")
    parser.add_argument("--dry-run", action="store_true",
                        help="只检查文件, 不实际操作设备")
    parser.add_argument("--skip-bl", action="store_true",
                        help="跳过 bootloader 分区 (已有 U-Boot 时使用)")
    parser.add_argument("--retry", type=int, default=3,
                        help="设备查找重试次数 (默认 3)")

    args = parser.parse_args()
    base_dir = os.path.abspath(args.dir)

    header("Amlogic USB Boot & Flash Tool")
    log(f"文件目录: {base_dir}")
    log(f"模式: {'检查' if args.dry_run else '仅加载U-Boot' if args.no_flash else '完整烧录'}")
    log(f"平台: GXL (S905L/S905L3/S905L3B)")

    # ---- 检查文件 ----
    if not check_files(base_dir, args.dry_run):
        sys.exit(1)

    if args.dry_run:
        log("\n--dry-run: 文件检查完成, 退出")
        sys.exit(0)

    # ---- 读取文件 ----
    log("\n读取烧录文件...")
    ddr_data = open(os.path.join(base_dir, "DDR.USB"), "rb").read()
    uboot_data = open(os.path.join(base_dir, "UBOOT.USB"), "rb").read()
    log(f"  DDR.USB:  {fmt_size(len(ddr_data))}")
    log(f"  UBOOT.USB: {fmt_size(len(uboot_data))}")

    # ============================================================
    #  阶段 1: ROM 模式
    # ============================================================
    header("阶段 1: ROM 模式 — 上传 BL2, 初始化 DDR")

    log("搜索设备 (VID=1b8e PID=c003)...")
    dev = None
    for attempt in range(args.retry):
        log(f"  尝试 {attempt+1}/{args.retry} ...")
        dev = find_device(VID_AMLOGIC, PID_ROM, timeout=10)
        if dev is not None:
            break
        log("  未找到设备, 重试...")

    if dev is None:
        log("\n错误: 未找到 Amlogic USB 设备!")
        log("请确认:")
        log("  1. 设备已进入 USB 烧录模式 (按住 reset 上电)")
        log("  2. USB 线已连接")
        log("  3. Linux: 安装了 libusb (apt install libusb-1.0-0)")
        log("  4. Windows: 通过 Zadig 安装了 libusb0/WinUSB 驱动")
        log("  5. 有 root/管理员权限")
        sys.exit(1)

    log("设备已连接")

    ok = stage1_rom_upload(dev, ddr_data)
    release_device(dev)
    dev = None

    if not ok:
        log("\n错误: 阶段 1 失败!")
        sys.exit(1)

    # ============================================================
    #  等待设备重新枚举
    # ============================================================
    log("\n等待设备重新枚举 (BL2 → USB)...")
    time.sleep(2)

    # 设备可能保持 PID=c003 或变为 c004
    dev = find_device(VID_AMLOGIC, PID_ROM, timeout=DEVICE_WAIT_MAX)
    if dev is None:
        log("PID=c003 未找到, 尝试 PID=c004 ...")
        dev = find_device(VID_AMLOGIC, PID_UBOOT, timeout=5)
    if dev is None:
        log("尝试任意 Amlogic PID ...")
        dev = find_device_any_pid(VID_AMLOGIC, timeout=5)

    if dev is None:
        log("\n错误: BL2 运行后设备未重新出现!")
        log("可能原因:")
        log("  1. BL2 (DDR.USB) 不匹配此设备")
        log("  2. DDR 初始化失败")
        log("  3. USB 连接不稳定")
        sys.exit(1)

    log("设备重新连接成功")
    product_id = dev.idProduct
    log(f"  PID: 0x{product_id:04x} ({'U-Boot' if product_id == PID_UBOOT else 'ROM/BL2'})")

    # ============================================================
    #  阶段 2: BL2 模式 — 上传 U-Boot
    # ============================================================
    header("阶段 2: BL2 模式 — 上传 U-Boot")

    ok = stage2_bl2_upload(dev, uboot_data)

    # 如果 U-Boot 已经在运行 (stage=16), 不需要重新上传
    if not ok:
        log("\n错误: 阶段 2 失败!")
        release_device(dev)
        sys.exit(1)

    # 等待 U-Boot USB 接口就绪
    # 设备可能再次重新枚举
    time.sleep(3)
    release_device(dev)
    dev = None

    # 重新查找 U-Boot 设备
    log("\n搜索 U-Boot USB 接口...")
    dev = find_device(VID_AMLOGIC, PID_ROM, timeout=10)
    if dev is None:
        dev = find_device(VID_AMLOGIC, PID_UBOOT, timeout=5)
    if dev is None:
        dev = find_device_any_pid(VID_AMLOGIC, timeout=5)

    if dev is None:
        if args.no_flash:
            log("\nU-Boot 可能已启动 (但 USB 接口未检测到)")
            log("如果设备已通过串口/网络可访问, 说明 U-Boot 运行成功")
            header("完成 — U-Boot 已加载 (不烧录)")
            sys.exit(0)
        log("\n错误: U-Boot 启动后设备未出现!")
        sys.exit(1)

    log("U-Boot 设备已连接")
    wait_for_uboot(dev, timeout=15)

    # ============================================================
    #  阶段 3: 烧录 (可选)
    # ============================================================
    if args.no_flash:
        header("完成 — U-Boot 已加载到内存 (--no-flash)")
        log("U-Boot 正在运行, 未执行 eMMC 烧录")
        log("可通过串口/网络连接 U-Boot 进行操作")
        release_device(dev)
        sys.exit(0)

    header("阶段 3: U-Boot 烧录 — 写入 eMMC")

    # 初始化存储
    log("初始化 eMMC 存储...")
    resp = send_bulk_cmd(dev, "store init 1")
    if resp:
        log(f"  响应: {resp.strip()[:120]}")
    time.sleep(2)

    # 烧录各分区
    success_count = 0
    fail_count = 0

    for part in PARTITIONS:
        if args.skip_bl and part["name"] == "bootloader":
            log(f"\n--- 跳过分区: {part['name']} (--skip-bl) ---")
            continue

        ok = flash_partition(dev, part, base_dir)
        if ok:
            success_count += 1
        else:
            fail_count += 1
            log(f"\n警告: {part['name']} 烧录失败, 继续下一个分区...")

    # 完成
    log(f"\n烧录统计: 成功 {success_count}, 失败 {fail_count}")

    if fail_count == 0:
        log("\n全部分区烧录成功!")
        log("重启设备...")
        send_bulk_cmd(dev, "reset", read_response=False)
        time.sleep(1)
        header("烧录完成 — 拔掉 USB 线, 重新上电启动")
    else:
        log("\n部分分区烧录失败, 建议检查日志后重试")
        header("烧录完成 (有错误)")

    release_device(dev)


if __name__ == "__main__":
    main()
