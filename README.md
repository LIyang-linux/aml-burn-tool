# Amlogic 烧录工具包 — 国产 eMMC 兼容版

中兴 B860AV2.1-A (S905L3-B) 及其他 Amlogic 盒子的 USB 线刷工具，解决 Windows 版 Amlogic USB Burning Tool 不兼容国产 eMMC 芯片的问题。

## 问题根因

国产 eMMC 芯片 (Foresee/江波龙, Biwin/佰维, YTXC, mafId=0xD6) 的擦除操作耗时超出 `UsbRomDrv.dll` 中硬编码的超时阈值，导致刷机卡在 **ERASE BOOTLOADER** 步骤超时失败。

## 魔改方案

| 层级 | 文件 | 修改内容 |
|------|------|----------|
| **DLL 补丁** | `patch_dll.py` | 搜索 `UsbRomDrv.dll` 中的超时常量，将擦除超时从 5-30s 延长到 120s |
| **注册表补丁** | `patches/burning_tool_settings.reg` | 禁用 `EraseBootloader`，启用 `EraseFlash` + `VerifyFlash` |
| **配置补丁** | `patches/aml_sdc_burn.ini` | `erase_bootloader = 0`，跳过擦除 boot 分区 |
| **启动器** | `launcher.bat` | 一键应用所有补丁并启动工具 |
| **Python 替代** | `win_flash.py` | 完全不依赖官方工具，纯 Python USB 烧录 |

## 目录结构

```
aml-burn-tool/
├── pyamlboot/                  # pyamlboot 协议库 (推荐方案)
│   ├── pyamlboot.py            # Amlogic USB Boot 协议核心库
│   ├── burn.py                 # 两阶段加载烧录脚本
│   ├── setup.py                # pip 安装支持
│   ├── requirements.txt        # Python 依赖
│   └── __init__.py             # 包初始化
├── windows/                    # Windows 魔改工具包
│   ├── launcher.bat            # 一键启动器 (自动补丁 + 启动)
│   ├── patch_dll.py            # DLL 超时补丁器
│   ├── win_flash.py            # Python 替代烧录方案
│   ├── find_device.py          # USB 设备检测工具
│   ├── patches/
│   │   ├── aml_sdc_burn.ini    # 修改版烧录配置
│   │   ├── burning_tool_settings.reg  # 注册表补丁
│   │   └── platform.conf       # 平台配置 (gxl)
│   └── README.md
├── linux/                      # Linux 烧录工具
│   ├── flash.sh                # 一键刷机脚本
│   ├── aml-flash               # 完整烧录工具 (v4.7.1)
│   ├── install.sh              # 依赖安装
│   ├── tools/                  # update + aml_image_v2_packer
│   └── README.md
├── python/                     # Python 工具集
│   ├── aml_burn.py             # GXL 协议烧录
│   ├── ddr_init.py             # DDR 初始化
│   ├── extract_img.py          # 镜像解包
│   ├── debug_burn.py           # 调试工具
│   └── read_emmc.py            # eMMC 读取
└── .github/workflows/
    └── build-release.yml       # CI/CD 自动打包 zip 发布
```

## 快速开始

### pyamlboot (推荐 — 纯 Python, 无需官方工具)

```sh
pip install pyusb
cd pyamlboot/
sudo python burn.py /path/to/files              # 完整烧录
sudo python burn.py /path/to/files --no-flash   # 只加载 U-Boot, 不烧录
sudo python burn.py /path/to/files --dry-run    # 只检查文件
sudo python burn.py /path/to/files --skip-bl    # 跳过 bootloader 分区
```

**两阶段加载流程:**
1. 阶段 1 (ROM): 上传 DDR.USB (BL2) → 初始化 DDR → 设备重新枚举
2. 阶段 2 (BL2): 上传 UBOOT.USB (U-Boot) → 运行 U-Boot
3. 阶段 3 (U-Boot): 通过 USB bulk 命令擦除 + 写入 eMMC 分区

### Windows

1. 安装 [Amlogic USB Burning Tool](https://firmware.jethome.com/jethome/firmware/tool/AML_Burn_Tool_V2.1.6.8.zip) v2.1.6+
2. 从 [Releases](../../releases) 下载最新 zip 并解压
3. 进入 `windows/` 目录，右键 `launcher.bat` → **以管理员身份运行**
4. 在 GUI 中：
   - **取消勾选** `Erase bootloader`
   - **勾选** `Erase flash` + `Verify flash`
   - 导入 `.img` 文件，点 `Start`

### Linux

```sh
cd linux/
sudo ./install.sh          # 安装依赖
sudo ./flash.sh /path/to/files   # 刷机
```

### Python 替代方案

```sh
pip install pyusb
# 方案 A: pyamlboot (推荐, 见上方说明)
cd pyamlboot/ && python burn.py /path/to/files
# 方案 B: 旧版脚本
cd windows/  # 或 python/
python win_flash.py /path/to/files
```

## 烧录所需文件

从 [B860AV2.1-A Releases](https://github.com/LIyang-linux/B860AV2.1-A/releases) 下载：

| 文件 | 说明 |
|------|------|
| `*.img.gz` | 完整线刷镜像 (解压后用 USB Burning Tool) |
| `DDR.USB` | DDR 初始化 (Python 方案需要) |
| `UBOOT.USB` | U-Boot 临时镜像 (Python 方案需要) |
| `bootloader.PARTITION` | U-Boot + FIP (Python 方案需要) |
| `boot.PARTITION` | 内核 + DTB (Python 方案需要) |
| `system.PARTITION` | 根文件系统 (Python 方案需要) |

## 超时补丁原理

```
eMMC 擦除流程:
  CMD35 (起始地址) → CMD36 (结束地址) → CMD38 (执行擦除)
                                              ↓
                                     eMMC 拉低 DAT0 (busy)
                                              ↓
                                  国产 eMMC: busy 持续 60-90s
                                              ↓
                          UsbRomDrv.dll 超时阈值: 5-30s → 超时!

补丁后:
  UsbRomDrv.dll 超时阈值: 120s → 充足等待
  aml_sdc_burn.ini: erase_bootloader=0 → 跳过擦除, 直接覆盖写入
```

## 适用设备

- 中兴 B860AV2.1-A (S905L3-B)
- 其他使用 S905/S905L/S905L3/S905L3B 的 Amlogic 盒子
- 使用国产 eMMC (mafId=0xD6) 的设备

## 技术参考

- [Amlogic 官方 USB 烧录指南](https://usermanual.wiki/Pdf/Amlogicupdateusbtooluserguide.323251948)
- [pyamlboot 开源实现](https://github.com/superna9999/pyamlboot)
- [Khadas 烧录工具文档](https://docs.jethome.com/en/controllers/linux/howto/amlogic/burning_tool.html)
