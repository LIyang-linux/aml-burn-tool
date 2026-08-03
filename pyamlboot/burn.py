#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0 OR MIT
"""
Amlogic USB Boot & Flash Tool — 基于 pyamlboot 协议库

严格遵循 pyamlboot 官方协议 (https://github.com/superna9999/pyamlboot)
适配中兴 B860AV2.1-A (S905L3-B / GXL 平台)

启动链 (三阶段, 严格匹配官方 pyamlboot boot.py):

  阶段 A — init_ddr (ROM 模式, stage=0):
    ① identify → 确认 stage=0
    ② writeMemory: BL2 (DDR.USB) → 0xd9000000  (小数据, writeMemory)
    ③ writeLargeMemory: usbbl2runpara_ddrinit.bin → 0xd900c000  (blockLength=32)
    ④ run(0xd9000000) → BL2 初始化 DDR
    ⑤ 等待 1s, identify → 确认 stage=8
    ⑥ run(0xd900c000) → BL2 读取 ddrinit 参数, 进入下一阶段

  阶段 B — load_uboot (BL2 模式, stage=8):
    ⑦ writeLargeMemory: BL2 (DDR.USB) → 0xd9000000  (再次写入, blockLength=64)
    ⑧ writeLargeMemory: usbbl2runpara_runfipimg.bin → 0xd900c000  (blockLength=48)
    ⑨ writeLargeMemory: TPL (UBOOT.USB) → 0x200c000  (blockLength=64, appendZeros)
    ⑩ run(0xd900c000) → BL2 加载并运行 TPL/U-Boot

  阶段 C — U-Boot 烧录:
    ⑪ 通过 bulkCmd 擦除 + 下载 + 写入各分区到 eMMC

关键区别 (与之前错误版本对比):
  - BL2 写入两次: 第1次用 writeMemory (小), 第2次用 writeLargeMemory (大)
  - 参数使用 usbbl2runpara 二进制文件, 不是手动构造 struct
  - TPL 加载到 0x200c000 (不是 0x10000000)
  - 最终 run(0xd900c000) 是参数地址 (不是 BL2 地址)

用法:
  python burn.py <文件目录> [--no-flash] [--dry-run]
  python burn.py /path/to/files
  python burn.py /path/to/files --no-flash     # 只加载 U-Boot, 不烧录
  python burn.py /path/to/files --dry-run      # 检查文件, 不实际操作

依赖:
  pip install pyusb
  Linux: apt install libusb-1.0-0
  Windows: 通过 Zadig 安装 libusb-win32 或 WinUSB 驱动
"""
import sys
import os
import time
import gzip
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
#  来自 pyamlboot 官方 boot.py GX Family 参数
# ============================================================

VID_AMLOGIC = 0x1b8e
PID_ROM     = 0xc003   # ROM/BL2 模式
PID_UBOOT   = 0xc004   # U-Boot 模式 (部分固件使用)

# 内存地址 — 严格匹配 pyamlboot GX Family
DDR_LOAD_ADDR   = 0xd9000000   # BL2 (DDR.USB) 加载地址
BL2_PARAMS_ADDR = 0xd900c000   # BL2 参数区 (usbbl2runpara 文件)
UBOOT_LOAD_ADDR = 0x0200c000   # TPL (UBOOT.USB) 加载地址 (注意: 不是 0x10000000!)

# 参数文件
DDR_INIT_FILE   = "usbbl2runpara_ddrinit.bin"     # DDR 初始化参数 (32 字节)
FIP_RUN_FILE    = "usbbl2runpara_runfipimg.bin"    # FIP 加载参数 (48 字节)

# 文件名映射 (Amlogic 烧录工具 → pyamlboot 命名)
# DDR.USB        = u-boot.bin.usb.bl2  (BL2)
# UBOOT.USB      = u-boot.bin.usb.tpl  (TPL/U-Boot)

# stage 值 (identify 返回的第 4 字节)
STAGE_ROM   = 0    # BL1 ROM
STAGE_BL2   = 8    # BL2/SPL (DDR 已初始化)
STAGE_TPL   = 16   # TPL/U-Boot

# USB 超时
DEVICE_WAIT_MAX  = 30       # 等待设备重新枚举最大秒数
BULK_TIMEOUT     = 30000    # 30s 批量传输

# 烧录分区定义
# files: 按优先级尝试的文件名列表 (支持 .gz 自动解压)
PARTITIONS = [
    {
        "name":   "bootloader",
        "files":  ["bootloader.PARTITION"],
        "cmd_erase":  "store erase bootloader",
        "cmd_write":  "download store bootloader normal {size}",
        "desc":   "U-Boot 引导 (写入 eMMC boot0/boot1)",
        "optional": False,
    },
    {
        "name":   "boot",
        "files":  ["boot.PARTITION", "boot.fat32", "boot.fat32.gz", "boot.img", "boot.img.gz"],
        "cmd_erase":  "store erase boot",
        "cmd_write":  "download store boot normal {size}",
        "desc":   "内核 + DTB + initramfs",
        "optional": False,
    },
    {
        "name":   "system",
        "files":  ["system.PARTITION", "rootfs.ext4", "rootfs.ext4.gz", "system.img", "system.img.gz"],
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
#  设备查找
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
                pass
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

def make_soc(dev):
    """从已有 dev 创建 AmlogicSoC 实例 (跳过 __init__ 的设备查找)"""
    soc = AmlogicSoC.__new__(AmlogicSoC)
    soc.dev = dev
    return soc


# ============================================================
#  阶段 A: init_ddr — ROM 模式, 上传 BL2, 初始化 DDR
#  严格匹配 pyamlboot boot.py init_ddr() 方法
# ============================================================

def init_ddr(dev, bl2_data, ddrinit_params, params_dir):
    """
    ROM 阶段: 上传 BL2, 初始化 DDR

    匹配 pyamlboot boot.py:
      soc_id()                           → identify
      write_file(BL2, DDR_LOAD)          → writeMemory (小数据)
      write_file(DDR_INIT, BL2_PARAMS, large=32)  → writeLargeMemory
      run(DDR_LOAD)                      → run BL2
      wait(1) + soc_id()                 → 确认 stage=8
      run(BL2_PARAMS)                    → 运行 ddrinit 参数
      wait(1)
    """
    soc = make_soc(dev)

    # 1. identify — 确认 ROM 阶段
    log("[1/6] 识别芯片阶段...")
    try:
        raw = soc.identify()
        rom_major = raw[0] if len(raw) > 0 else 0
        rom_minor = raw[1] if len(raw) > 1 else 0
        stage = raw[3] if len(raw) > 3 else -1
        log(f"  ROM: {rom_major}.{rom_minor} Stage: {raw[2] if len(raw) > 2 else 0}.{stage}")
        if stage != STAGE_ROM:
            log(f"  警告: 期望 ROM 阶段(0), 实际为 {stage}")
            log(f"  设备可能已部分加载, 尝试继续...")
    except Exception as e:
        log(f"  identify 失败: {e} (继续尝试...)")

    # 2. writeMemory: 上传 BL2 (DDR.USB) 到 0xd9000000
    #    官方 pyamlboot 第一次用 writeMemory (小块传输)
    log(f"[2/6] 上传 BL2 (DDR.USB) → 0x{DDR_LOAD_ADDR:08x} (writeMemory) ...")
    log(f"  大小: {fmt_size(len(bl2_data))}")
    t0 = time.time()
    try:
        soc.writeMemory(DDR_LOAD_ADDR, bl2_data)
    except Exception as e:
        log(f"  错误: 上传 BL2 失败: {e}")
        return False
    log(f"  完成 ({time.time()-t0:.1f}s)")

    # 3. writeLargeMemory: 写入 usbbl2runpara_ddrinit.bin 到 0xd900c000
    #    官方 pyamlboot 使用 large=32 (blockLength=32)
    log(f"[3/6] 写入 DDR 初始化参数 → 0x{BL2_PARAMS_ADDR:08x} (blockLength=32) ...")
    log(f"  文件: {DDR_INIT_FILE} ({len(ddrinit_params)} 字节)")
    try:
        soc.writeLargeMemory(BL2_PARAMS_ADDR, ddrinit_params, blockLength=32)
    except Exception as e:
        log(f"  错误: 写入参数失败: {e}")
        return False
    log("  完成")

    # 4. run(0xd9000000) — 执行 BL2, 初始化 DDR
    log(f"[4/6] 运行 BL2 @ 0x{DDR_LOAD_ADDR:08x} (DDR 初始化) ...")
    try:
        soc.run(DDR_LOAD_ADDR, keep_power=True)
    except Exception as e:
        if "timed out" in str(e).lower() or "pipe" in str(e).lower():
            log("  设备断开 (正常行为)")
        else:
            log(f"  注意: {e}")

    # 5. 等待 1s, identify — 确认进入 BL2 阶段 (stage=8)
    log("[5/6] 等待设备重新枚举 (1s) ...")
    time.sleep(1)
    soc = make_soc(dev)  # 重新创建 (设备可能已重置)
    try:
        raw = soc.identify()
        stage = raw[3] if len(raw) > 3 else -1
        log(f"  ROM: {raw[0]}.{raw[1]} Stage: {raw[2]}.{stage}")
        if stage == STAGE_BL2:
            log("  DDR 初始化成功, 进入 BL2 阶段")

            # 6. run(0xd900c000) — 运行 ddrinit 参数 (BL2 继续执行)
            log(f"[6/6] 运行 BL2 参数 @ 0x{BL2_PARAMS_ADDR:08x} ...")
            try:
                soc.run(BL2_PARAMS_ADDR, keep_power=True)
            except Exception as e:
                if "timed out" in str(e).lower() or "pipe" in str(e).lower():
                    log("  设备断开 (正常行为)")
                else:
                    log(f"  注意: {e}")
        else:
            log(f"  警告: 期望 stage=8, 实际 stage={stage}")
            log("  DDR 初始化可能未完成, 尝试继续...")
    except Exception as e:
        log(f"  identify 失败: {e}")
        log("  尝试继续...")

    log("init_ddr 完成")
    return True


# ============================================================
#  阶段 B: load_uboot — BL2 模式, 上传 TPL/U-Boot
#  严格匹配 pyamlboot boot.py load_uboot() 方法
# ============================================================

def load_uboot(dev, bl2_data, fip_params, uboot_data):
    """
    BL2 阶段: 上传 BL2 (再次), FIP 参数, TPL

    匹配 pyamlboot boot.py:
      write_file(BL2, DDR_LOAD, large=64)          → writeLargeMemory (第二次, 大块)
      write_file(FIP_FILE, BL2_PARAMS, large=48)   → writeLargeMemory
      write_file(TPL, UBOOT_LOAD, large=64, fill=True) → writeLargeMemory (appendZeros)
    """
    soc = make_soc(dev)

    # 1. identify — 确认 BL2 阶段
    log("[1/4] 识别芯片阶段...")
    try:
        raw = soc.identify()
        stage = raw[3] if len(raw) > 3 else -1
        log(f"  ROM: {raw[0]}.{raw[1]} Stage: {raw[2]}.{stage}")
        if stage == STAGE_TPL:
            log("  U-Boot 已在运行 (跳过加载)")
            return True
        elif stage == STAGE_ROM:
            log("  警告: 仍在 ROM 阶段, init_ddr 可能未成功")
    except Exception as e:
        log(f"  identify 失败: {e} (继续尝试...)")

    # 2. writeLargeMemory: BL2 (DDR.USB) → 0xd9000000 (第二次写入, blockLength=64)
    log(f"[2/4] 上传 BL2 (DDR.USB) → 0x{DDR_LOAD_ADDR:08x} (writeLargeMemory, blockLength=64) ...")
    log(f"  大小: {fmt_size(len(bl2_data))}")
    t0 = time.time()
    try:
        soc.writeLargeMemory(DDR_LOAD_ADDR, bl2_data, blockLength=64, appendZeros=True)
    except Exception as e:
        log(f"  错误: 上传 BL2 失败: {e}")
        return False
    log(f"  完成 ({time.time()-t0:.1f}s)")

    # 3. writeLargeMemory: usbbl2runpara_runfipimg.bin → 0xd900c000 (blockLength=48)
    log(f"[3/4] 写入 FIP 加载参数 → 0x{BL2_PARAMS_ADDR:08x} (blockLength=48) ...")
    log(f"  文件: {FIP_RUN_FILE} ({len(fip_params)} 字节)")
    try:
        soc.writeLargeMemory(BL2_PARAMS_ADDR, fip_params, blockLength=48)
    except Exception as e:
        log(f"  错误: 写入参数失败: {e}")
        return False
    log("  完成")

    # 4. writeLargeMemory: TPL (UBOOT.USB) → 0x200c000 (blockLength=64, appendZeros=True)
    log(f"[4/4] 上传 TPL (UBOOT.USB) → 0x{UBOOT_LOAD_ADDR:08x} (blockLength=64, appendZeros) ...")
    log(f"  大小: {fmt_size(len(uboot_data))}")
    t0 = time.time()
    try:
        soc.writeLargeMemory(UBOOT_LOAD_ADDR, uboot_data, blockLength=64, appendZeros=True)
    except Exception as e:
        log(f"  错误: 上传 TPL 失败: {e}")
        return False
    log(f"  完成 ({time.time()-t0:.1f}s)")

    log("load_uboot 完成")
    return True


# ============================================================
#  run_uboot — 执行 U-Boot
#  匹配 pyamlboot boot.py run_uboot() 方法
# ============================================================

def run_uboot(dev):
    """
    运行 U-Boot:
      如果 stage==8: run(0xd900c000)  → BL2 读取 FIP 参数, 加载并运行 TPL
      否则:          run(0xd9000000)  → 直接运行 BL2
    """
    soc = make_soc(dev)

    try:
        raw = soc.identify()
        stage = raw[3] if len(raw) > 3 else -1
    except Exception:
        stage = -1

    if stage == STAGE_BL2:
        addr = BL2_PARAMS_ADDR
        log(f"运行 U-Boot: run(0x{addr:08x}) [BL2 → TPL]")
    else:
        addr = DDR_LOAD_ADDR
        log(f"运行 U-Boot: run(0x{addr:08x}) [直接 BL2]")

    try:
        soc.run(addr, keep_power=True)
    except Exception as e:
        if "timed out" in str(e).lower() or "pipe" in str(e).lower():
            log("  设备响应中断 (正常行为)")
        else:
            log(f"  注意: {e}")

    log("U-Boot 启动中...")
    return True


# ============================================================
#  阶段 C: U-Boot 烧录
# ============================================================

def wait_for_uboot(dev, timeout=15):
    """等待 U-Boot USB 接口就绪"""
    log("等待 U-Boot 就绪...")
    for i in range(timeout * 5):
        time.sleep(0.2)
        try:
            soc = make_soc(dev)
            soc.nop()
            log(f"U-Boot 就绪 ({i*0.2:.0f}s)")
            return True
        except Exception:
            continue
    log("警告: U-Boot 未响应 nop, 尝试继续...")
    return False

def send_bulk_cmd(dev, cmd, read_response=True):
    """发送 bulkcmd 到 U-Boot, 可选读取响应"""
    soc = make_soc(dev)
    try:
        soc.bulkCmd(cmd)
    except Exception as e:
        log(f"  bulkCmd 异常: {e}")
        return ""

    if not read_response:
        return ""

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
        padded = chunk
        if len(padded) % 64 != 0:
            padded = padded + b'\x00' * (64 - len(padded) % 64)

        try:
            ep_out.write(padded, timeout=BULK_TIMEOUT)
            offset += actual_len
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

def find_partition_file(part, base_dir):
    """在 base_dir 中查找分区文件, 返回 (路径, 是否gzip) 或 None"""
    for fname in part["files"]:
        path = os.path.join(base_dir, fname)
        if os.path.isfile(path):
            is_gz = fname.endswith(".gz")
            return (path, is_gz, fname)
    return None

def load_partition_data(part, base_dir):
    """查找并加载分区数据, 自动解压 .gz"""
    result = find_partition_file(part, base_dir)
    if result is None:
        return None, None, None

    path, is_gz, fname = result
    if is_gz:
        log(f"  解压: {fname} ...")
        with gzip.open(path, "rb") as f:
            data = f.read()
        log(f"  解压完成: {fmt_size(len(data))} (原压缩: {fmt_size(os.path.getsize(path))})")
    else:
        data = open(path, "rb").read()

    return data, fname, len(data)

def flash_partition(dev, part, base_dir):
    """擦除并写入单个分区"""
    name = part["name"]

    log(f"\n--- 烧录分区: {name} ({part['desc']}) ---")

    result = find_partition_file(part, base_dir)
    if result is None:
        if part.get("optional"):
            log(f"  跳过: 文件不存在 (尝试过: {', '.join(part['files'])})")
            return True
        log(f"  错误: 文件不存在, 尝试过: {', '.join(part['files'])}")
        return False

    path, is_gz, fname = result

    if is_gz:
        log(f"  解压: {fname} ...")
        with gzip.open(path, "rb") as f:
            data = f.read()
        log(f"  解压完成: {fmt_size(len(data))} (原压缩: {fmt_size(os.path.getsize(path))})")
    else:
        data = open(path, "rb").read()

    size = len(data)
    log(f"  文件: {fname} ({fmt_size(size)})")

    # 1. 擦除分区
    log(f"  擦除 {name} ...")
    resp = send_bulk_cmd(dev, part["cmd_erase"])
    if resp:
        log(f"  擦除响应: {resp.strip()[:80]}")
    time.sleep(1)

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

    # 4. 检查下载状态
    time.sleep(0.5)
    resp = send_bulk_cmd(dev, "download get_status")
    if resp:
        log(f"  状态: {resp.strip()[:80]}")

    # 5. 保存
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

def check_files(base_dir, params_dir, dry_run=False):
    """检查所需文件是否齐全"""
    log("检查烧录文件...")

    # 固定文件名 (非分区)
    fixed_files = [
        ("DDR.USB", "BL2 引导镜像", base_dir),
        ("UBOOT.USB", "TPL/U-Boot 镜像", base_dir),
        (DDR_INIT_FILE, "DDR 初始化参数", params_dir),
        (FIP_RUN_FILE, "FIP 加载参数", params_dir),
    ]

    all_found = True

    for fname, desc, search_dir in fixed_files:
        path = os.path.join(search_dir, fname)
        if os.path.isfile(path):
            size = os.path.getsize(path)
            log(f"  [OK] {fname:35s} {fmt_size(size):>10s}  {desc}")
        else:
            log(f"  [缺失] {fname:35s}              {desc}")
            all_found = False

    # 分区文件 (支持多文件名 + .gz)
    for part in PARTITIONS:
        result = find_partition_file(part, base_dir)
        if result is not None:
            path, is_gz, fname = result
            size = os.path.getsize(path)
            gz_tag = " (gz)" if is_gz else ""
            log(f"  [OK] {fname:35s} {fmt_size(size):>10s}  {part['desc']}{gz_tag}")
        else:
            if part.get("optional"):
                log(f"  [可选] {part['files'][0]:35s}              {part['desc']}")
            else:
                tried = " / ".join(part["files"])
                log(f"  [缺失] {tried:35s}              {part['desc']}")
                all_found = False

    if not all_found:
        log("\n错误: 必需文件缺失!")
        log(f"  参数文件 ({DDR_INIT_FILE}, {FIP_RUN_FILE}) 应在:")
        log(f"    {params_dir}")
        log(f"  DDR.USB / UBOOT.USB 从 B860AV2.1-A Releases 下载")
        log(f"  分区文件支持: boot.PARTITION / boot.fat32 / boot.fat32.gz")
        log(f"                system.PARTITION / rootfs.ext4 / rootfs.ext4.gz")
        return False

    log("文件检查通过")
    return True


# ============================================================
#  主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Amlogic USB Boot & Flash Tool (pyamlboot 协议)",
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

注意:
  - 需要 usbbl2runpara_ddrinit.bin 和 usbbl2runpara_runfipimg.bin
    这两个文件已包含在本目录中 (从 pyamlboot 项目获取)
  - DDR.USB 和 UBOOT.USB 从 B860AV2.1-A Releases 下载
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
    # 参数文件目录 (本脚本所在目录)
    params_dir = os.path.dirname(os.path.abspath(__file__))

    header("Amlogic USB Boot & Flash Tool (pyamlboot)")
    log(f"文件目录: {base_dir}")
    log(f"参数目录: {params_dir}")
    log(f"模式: {'检查' if args.dry_run else '仅加载U-Boot' if args.no_flash else '完整烧录'}")
    log(f"平台: GXL (S905L/S905L3/S905L3B)")
    log(f"协议: pyamlboot 官方三阶段加载")

    # ---- 检查文件 ----
    if not check_files(base_dir, params_dir, args.dry_run):
        sys.exit(1)

    if args.dry_run:
        log("\n--dry-run: 文件检查完成, 退出")
        sys.exit(0)

    # ---- 读取文件 ----
    log("\n读取烧录文件...")
    bl2_data = open(os.path.join(base_dir, "DDR.USB"), "rb").read()
    uboot_data = open(os.path.join(base_dir, "UBOOT.USB"), "rb").read()
    ddrinit_params = open(os.path.join(params_dir, DDR_INIT_FILE), "rb").read()
    fip_params = open(os.path.join(params_dir, FIP_RUN_FILE), "rb").read()
    log(f"  DDR.USB (BL2):           {fmt_size(len(bl2_data))}")
    log(f"  UBOOT.USB (TPL):         {fmt_size(len(uboot_data))}")
    log(f"  {DDR_INIT_FILE}:   {len(ddrinit_params)} 字节")
    log(f"  {FIP_RUN_FILE}:  {len(fip_params)} 字节")

    # ============================================================
    #  阶段 A: init_ddr — ROM 模式
    # ============================================================
    header("阶段 A: init_ddr — ROM 模式, 上传 BL2, 初始化 DDR")

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
        log("  4. Windows: 通过 Zadig 安装了 libusb-win32/WinUSB 驱动")
        log("  5. 有 root/管理员权限")
        log("  6. 不要使用 AMD 机器的 USB3 端口 (已知兼容性问题)")
        sys.exit(1)

    log("设备已连接")

    ok = init_ddr(dev, bl2_data, ddrinit_params, params_dir)
    release_device(dev)
    dev = None

    if not ok:
        log("\n错误: init_ddr 失败!")
        sys.exit(1)

    # ============================================================
    #  等待设备重新枚举
    # ============================================================
    log("\n等待设备重新枚举 (init_ddr → BL2 模式)...")
    time.sleep(2)

    dev = find_device(VID_AMLOGIC, PID_ROM, timeout=DEVICE_WAIT_MAX)
    if dev is None:
        log("PID=c003 未找到, 尝试 PID=c004 ...")
        dev = find_device(VID_AMLOGIC, PID_UBOOT, timeout=5)
    if dev is None:
        log("尝试任意 Amlogic PID ...")
        dev = find_device_any_pid(VID_AMLOGIC, timeout=5)

    if dev is None:
        log("\n错误: init_ddr 后设备未重新出现!")
        log("可能原因:")
        log("  1. BL2 (DDR.USB) 不匹配此设备")
        log("  2. DDR 初始化失败")
        log("  3. USB 连接不稳定/供电不足")
        log("  4. AMD USB 控制器兼容性问题")
        sys.exit(1)

    log("设备重新连接成功")
    product_id = dev.idProduct
    log(f"  PID: 0x{product_id:04x}")

    # ============================================================
    #  阶段 B: load_uboot — BL2 模式, 上传 TPL
    # ============================================================
    header("阶段 B: load_uboot — BL2 模式, 上传 TPL/U-Boot")

    ok = load_uboot(dev, bl2_data, fip_params, uboot_data)
    if not ok:
        log("\n错误: load_uboot 失败!")
        release_device(dev)
        sys.exit(1)

    # ============================================================
    #  run_uboot — 执行 U-Boot
    # ============================================================
    header("运行 U-Boot")

    ok = run_uboot(dev)
    release_device(dev)
    dev = None

    # 等待 U-Boot 启动并重新枚举
    time.sleep(3)

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
        log("可能原因:")
        log("  1. UBOOT.USB (TPL) 不匹配此设备")
        log("  2. U-Boot 不支持 USB 烧录模式 (需要 Amlogic vendor U-Boot)")
        log("  3. 供电不足")
        sys.exit(1)

    log("U-Boot 设备已连接")
    wait_for_uboot(dev, timeout=15)

    # ============================================================
    #  阶段 C: 烧录 (可选)
    # ============================================================
    if args.no_flash:
        header("完成 — U-Boot 已加载到内存 (--no-flash)")
        log("U-Boot 正在运行, 未执行 eMMC 烧录")
        log("可通过串口/网络连接 U-Boot 进行操作")
        release_device(dev)
        sys.exit(0)

    header("阶段 C: U-Boot 烧录 — 写入 eMMC")

    # 初始化存储
    log("初始化 eMMC 存储...")
    resp = send_bulk_cmd(dev, "store init 1")
    if resp:
        log(f"  响应: {resp.strip()[:120]}")
    else:
        log("  (无响应, 可能 U-Boot 不支持 store 命令)")
        log("  如果 U-Boot 是 mainline 版本, 不支持 Amlogic store 命令")
        log("  需要使用 Amlogic vendor U-Boot 或改用 UMS 模式")
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
        log("保存设置...")
        send_bulk_cmd(dev, "save_setting")
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
