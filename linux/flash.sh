#!/bin/sh
# flash.sh — B860AV2.1-A one-click flash
# Usage: ./flash.sh [directory_with_partition_files]

DIR="${1:-.}"

RED='\033[31m'; GREEN='\033[32m'; CYAN='\033[36m'; NC='\033[0m'
log()   { echo "${GREEN}[+]${NC} $1"; }
info()  { echo "${CYAN}[*]${NC} $1"; }
err()   { echo "${RED}[!]${NC} $1"; exit 1; }

# Check update tool
if ! command -v update >/dev/null 2>&1; then
    err "update tool not found! Run ./install.sh first"
fi

# Verify device is connected
info "Scanning for Amlogic device..."
if ! update scan 2>/dev/null | grep -q "1b8e:c003"; then
    err "No Amlogic device found!
  → Enter USB download mode: power off → hold reset → USB in → release
  → Then re-run: ./flash.sh $DIR"
fi
log "Device found"

# Check files
cd "$DIR"
for f in DDR.USB UBOOT.USB boot.PARTITION system.PARTITION bootloader.PARTITION; do
    if [ ! -f "$f" ]; then
        err "Missing: $f (in $DIR)"
    fi
done

info "Ready to flash. This will overwrite eMMC."
info "Files:"
for f in DDR.USB UBOOT.USB bootloader.PARTITION boot.PARTITION system.PARTITION; do
    sz=$(ls -lh "$f" 2>/dev/null | awk '{print $5}')
    [ -n "$sz" ] && echo "  $f ($sz)"
done
echo ""

# === Flashing sequence ===
# 1. DDR + UBOOT (uploaded automatically by update tool via AMLC protocol)
# 2. bootloader
# 3. boot partition
# 4. system partition

log "Step 1/4: Flashing bootloader..."
update partition bootloader bootloader.PARTITION

log "Step 2/4: Flashing boot partition..."
update partition boot boot.PARTITION

log "Step 3/4: Flashing system partition..."
update partition system system.PARTITION

log "Step 4/4: Done! Rebooting..."
update bulkcmd "reset" 2>/dev/null || true

echo ""
echo "============================================"
echo "  Flash complete! Device rebooting..."
echo "============================================"
