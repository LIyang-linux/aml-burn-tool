#!/bin/sh
# flash.sh — Python DDR init + update partition flash
# Phase 1: Python loads DDR/BL2 via control transfer (xHCI/CTRL safe)
# Phase 2: update tool flashes partitions via bulk (BL2/TLP required)

set -e

DIR="${1:-.}"
RED='\033[31m'; GREEN='\033[32m'; CYAN='\033[36m'; NC='\033[0m'
log()   { echo "${GREEN}[+]${NC} $1"; }
info()  { echo "${CYAN}[*]${NC} $1"; }
err()   { echo "${RED}[!]${NC} $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check files
for f in DDR.USB UBOOT.USB; do
    [ -f "$DIR/$f" ] || err "Missing $DIR/$f"
done

# === Phase 1: Python DDR init ===
info "Phase 1: Python DDR init (control transfer)..."
python3 "$SCRIPT_DIR/../ddr_init.py" "$DIR" || err "DDR init failed!"

# === Phase 2: Wait for BL2/U-Boot ===
info "Phase 2: Waiting for U-Boot..."
for i in $(seq 1 30); do
    if update identify 2>/dev/null | grep -qi "firmware"; then
        log "U-Boot ready ($i s)"
        break
    fi
    sleep 1
done
update identify 2>/dev/null | grep -qi "firmware" || err "U-Boot not responding!"

# === Phase 3: Flash partitions ===
if [ -f "$DIR/boot.PARTITION" ]; then
    sz=$(ls -lh "$DIR/boot.PARTITION" | awk '{print $5}')
    info "Flashing boot ($sz)..."
    update partition boot "$DIR/boot.PARTITION" || err "boot flash failed!"
    log "boot done"
fi

if [ -f "$DIR/system.PARTITION" ]; then
    sz=$(ls -lh "$DIR/system.PARTITION" | awk '{print $5}')
    info "Flashing system ($sz)..."
    update partition system "$DIR/system.PARTITION" || err "system flash failed!"
    log "system done"
fi

# === Phase 4: Reboot ===
info "Rebooting..."
update bulkcmd "reset" 2>/dev/null || true
log "Done! Remove USB and power cycle."
