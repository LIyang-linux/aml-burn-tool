# Windows 魔改工具包

## 文件说明

| 文件 | 说明 |
|------|------|
| `launcher.bat` | 一键启动器，自动搜索工具、补丁 DLL、导入注册表、启动 |
| `patch_dll.py` | DLL 超时补丁器，修改 `UsbRomDrv.dll` 中的硬编码超时值 |
| `win_flash.py` | Python 替代方案，完全不依赖官方工具烧录 |
| `find_device.py` | USB 设备检测工具 (诊断用) |
| `patches/aml_sdc_burn.ini` | 修改版烧录配置 (`erase_bootloader=0`) |
| `patches/burning_tool_settings.reg` | 注册表补丁 (禁用 erase bootloader) |
| `patches/platform.conf` | gxl 平台配置 |

## 使用方法

### 方式 1: 一键启动器 (推荐)

1. 安装 Amlogic USB Burning Tool v2.1.6+
2. 右键 `launcher.bat` → **以管理员身份运行**
3. 启动器会自动:
   - 搜索 USB Burning Tool 安装路径
   - 备份并补丁 `UsbRomDrv.dll` (延长超时)
   - 导入注册表设置 (禁用 erase bootloader)
   - 复制补丁配置文件
   - 启动 USB Burning Tool
4. 在 GUI 中:
   - **取消勾选** `Erase bootloader`
   - **勾选** `Erase flash` + `Verify flash`
   - 导入 `.img` 文件，点 `Start`

### 方式 2: 手动补丁

```cmd
# 补丁 DLL (延长超时)
python patch_dll.py "C:\Program Files (x86)\Amlogic\USB_Burning_Tool\UsbRomDrv.dll"

# 导入注册表
regedit /s patches\burning_tool_settings.reg

# 手动复制配置
copy patches\aml_sdc_burn.ini "C:\Program Files (x86)\Amlogic\USB_Burning_Tool\"
```

### 方式 3: Python 替代方案 (无需官方工具)

```cmd
pip install pyusb
python win_flash.py /path/to/files
```

## DLL 补丁详情

`UsbRomDrv.dll` 中的超时常量修改:

| 原始值 | 补丁值 | 说明 |
|--------|--------|------|
| 5000ms | 120000ms | 擦除超时 5s → 120s |
| 10000ms | 120000ms | 擦除超时 10s → 120s |
| 15000ms | 120000ms | 擦除超时 15s → 120s |
| 20000ms | 120000ms | 擦除超时 20s → 120s |
| 30000ms | 120000ms | 擦除超时 30s → 120s |
| 3000ms | 30000ms | USB 传输 3s → 30s |
| 200ms | 2000ms | DDR 训练 200ms → 2000ms |

## 恢复原始 DLL

```cmd
# 恢复备份
copy "C:\Program Files (x86)\Amlogic\USB_Burning_Tool\UsbRomDrv.dll.bak" ^
     "C:\Program Files (x86)\Amlogic\USB_Burning_Tool\UsbRomDrv.dll"
```
