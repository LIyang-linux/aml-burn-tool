#!/bin/sh
# flash.sh — Pure shell: update write DDR + update partition flash
# No Python dependency. Works on Alpine with libusb + update binary.

DIR="${1:-.}"
GREEN='\033[32m'; CYAN='\033[36m'; RED='\033[31m'; NC='\033[0m'
log()   { echo "${GREEN}[+]${NC} $1"; }
info()  { echo "${CYAN}[*]${NC} $1"; }
err()   { echo "${RED}[!]${NC} $1"; exit 1; }

# Check update tool
command -v update >/dev/null 2>&1 || err "update not found! Run sudo ./install.sh first"

# Check files
for f in DDR.USB UBOOT.USB; do
    [ -f "$DIR/$f" ] || err "Missing $DIR/$f"
done

# === Phase 1: Load DDR via update write ===
info "Loading DDR to 0xd9000000..."
# update write: load file to memory address
update write "$DIR/DDR.USB" 0xd9000000 || {
    # Try alternate syntax: update cur/write
    update cwr/write "$DIR/DDR.USB" 0xd9000000 || err "DDR write failed!"
}
log "DDR loaded"

info "Loading DDR params to 0xd900c000..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
update write "$SCRIPT_DIR/tools/datas/usbbl2runpara_ddrinit.bin" 0xd900c000 2>/dev/null || true
log "Params loaded"

info "Loading UBOOT to 0x200c000..."
update write "$DIR/UBOOT.USB" 0x200c000 || err "UBOOT write failed!"
log "UBOOT loaded"

# === Phase 2: Run BL2 ===
info "Running BL2 at 0xd9000000..."
update run 0xd9000000 || true
log "BL2 started"

# === Phase 3: Wait for U-Boot ===
info "Waiting for U-Boot..."
for i in $(seq 1 30); do
    sleep 1
    if update identify 2>/dev/null | grep -qi "firmware"; then
        log "U-Boot ready (${i}s)"
        break
    fi
    [ $i -eq 30 ] && err "U-Boot not responding after 30s!"
done

# === Phase 4: Flash partitions ===
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

# === Phase 5: Reboot ===
info "Rebooting..."
update bulkcmd "reset" 2>/dev/null || true
echo ""
log "ALL DONE! Power cycle the box."
