# Amlogic Linux USB Burn Tool

基于 Amlogic 官方 `update` 工具（WorldCup 协议），一键在 **Linux 虚拟机**上刷机，解决 Windows xHCI 主控不兼容问题。

## 安装

```sh
sudo ./install.sh
```

**自动适配：**
- **Alpine Linux** → `apk add libusb-compat eudev`
- **Debian/Ubuntu** → `apt install libusb-0.1-4`
- **Arch Linux** → `pacman -S libusb-compat`
- **Fedora** → `dnf install libusb`

## 使用方法

### 一键刷机

```sh
# 将所有分区文件放同一目录
cp Armbian_artifacts/*.PARTITION ./
cp Armbian_artifacts/DDR.USB ./
cp Armbian_artifacts/UBOOT.USB ./

# 盒子进下载模式 → 闪
sudo ./flash.sh .
```

### 单独命令

```sh
update scan                          # 扫描设备
update identify                      # 识别芯片
update partition bootloader bootloader.PARTITION
update partition boot boot.PARTITION
update partition system system.PARTITION
update bulkcmd "reset"               # 重启
```

## 所需文件

从 [B860AV2.1-A CI Artifacts](https://github.com/LIyang-linux/B860AV2.1-A/actions) 下载：

| 文件 | 作用 |
|---|---|
| `DDR.USB` | DDR 初始化 |
| `UBOOT.USB` | 临时 U-Boot (WorldCup 协议) |
| `bootloader.PARTITION` | U-Boot + FIP |
| `boot.PARTITION` | 内核 + DTB + logo |
| `system.PARTITION` | 根文件系统 |

## 为什么用这个？

```
Windows USB 3.0 (xHCI) = Amlogic Boot ROM 不兼容 → 刷机失败
Linux + VirtualBox EHCI  = 完美兼容 → 5 分钟刷完

VirtualBox 设置:
  内存: 1GB
  USB 控制器: USB 2.0 (EHCI)  ← 关键！
  启动 → 设备菜单 → USB → Amlogic → 直通
```

## 许可

`update` 二进制来自 [osmc/aml-flash-tool](https://github.com/osmc/aml-flash-tool)，为 Amlogic 官方工具。
