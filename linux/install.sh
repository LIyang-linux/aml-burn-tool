#!/bin/sh
# install.sh — Install Amlogic USB Burning Tool for Linux
# Supports: Debian, Ubuntu, Alpine, Arch, Fedora
# Based on Amlogic official update tool (from osmc/aml-flash-tool)

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
RED='\033[31m'; GREEN='\033[32m'; NC='\033[0m'
log() { echo "${GREEN}[+]${NC} $1"; }
err() { echo "${RED}[!]${NC} $1"; exit 1; }

echo "============================================"
echo " Amlogic USB Burn Tool — Linux Installer"
echo "============================================"
echo ""

# Detect OS
if [ -f /etc/alpine-release ]; then
    OS="alpine"
elif [ -f /etc/debian_version ]; then
    OS="debian"
elif [ -f /etc/arch-release ]; then
    OS="arch"
elif [ -f /etc/fedora-release ]; then
    OS="fedora"
else
    OS="unknown"
fi
log "Detected OS: $OS"

# Install libusb-0.1 (required by update binary)
case "$OS" in
    alpine)
        log "Installing libusb-compat + eudev..."
        apk add --no-cache libusb-compat eudev
        ;;
    debian)
        log "Installing libusb-0.1-4..."
        apt-get update -qq
        apt-get install -y -qq libusb-0.1-4
        ;;
    arch)
        log "Installing libusb-compat..."
        pacman -S --noconfirm libusb-compat
        ;;
    fedora)
        log "Installing libusb..."
        dnf install -y libusb
        ;;
    *)
        err "Unknown OS. Install libusb-0.1 manually and re-run."
        ;;
esac

# Install update binary
log "Installing update binary to /usr/local/bin/update..."
cp "$DIR/update" /usr/local/bin/update
chmod +x /usr/local/bin/update

# Install udev rules for non-root access
log "Setting up udev rules..."
cat > /etc/udev/rules.d/70-worldcup.rules << 'EOF'
# Amlogic WorldCup USB device
SUBSYSTEMS=="usb", ATTRS{idVendor}=="1b8e", ATTRS{idProduct}=="c003", MODE="0666", SYMLINK+="worldcup"
EOF

# Reload udev
case "$OS" in
    alpine)
        udevadm control --reload-rules 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
        rc-update add udev 2>/dev/null || true
        ;;
    debian|fedora)
        udevadm control --reload-rules 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
        ;;
    arch)
        udevadm control --reload 2>/dev/null || true
        udevadm trigger 2>/dev/null || true
        ;;
esac

log "Done!"
echo ""

# Link aml-flash-tool.sh for direct .img flashing
cp "$DIR/aml-flash-tool.sh" /usr/local/bin/aml-flash-tool.sh
chmod +x /usr/local/bin/aml-flash-tool.sh

echo ""
echo "Usage:"
echo "  update scan          — scan for Amlogic device"
echo "  update identify      — check device identity"
echo "  update partition PARTITION_TYPE FILE"
echo "     PARTITION_TYPE: bootloader, boot, system, logo, ..."
echo ""
echo "Example (from B860AV2.1-A CI artifacts):"
echo "  update partition bootloader bootloader.PARTITION"
echo "  update partition boot      boot.PARTITION"
echo "  update partition system    system.PARTITION"
echo ""
echo "  ./flash.sh  — auto-flash all partitions"
