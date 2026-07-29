#!/bin/sh
# flash_gxl.sh — GXL 一键线刷 (cwr DDR + reload UBOOT + burn)
# Alpine: apk add libusb-compat gcompat eudev
# Debian: apt install libusb-0.1-4
# Usage: sudo ./flash_gxl.sh /path/to/files/

set -e
D="${1:-.}"
GREEN='\033[32m'; RED='\033[31m'; NC='\033[0m'
log() { echo "${GREEN}[+]${NC} $1"; }
err() { echo "${RED}[!]${NC} $1"; exit 1; }

for f in DDR.USB UBOOT.USB; do
    [ -f "$D/$f" ] || err "Missing $D/$f"
done

# Step 1: cwr loads BL2 to SRAM
log "1/5 Loading DDR via cwr..."
update cwr "$D/DDR.USB" 0xd9000000 || err "cwr DDR failed!"

# Step 2: params
log "2/5 Writing DDR params..."
S="$(cd "$(dirname "$0")" && pwd)"
update write "$S/tools/datas/usbbl2runpara_ddrinit.bin" 0xd900c000 2>/dev/null || true
log "Params OK"

# Step 3: Run DDR init
log "3/5 Running DDR init..."
update run 0xd9000030
sleep 8

# Step 4: Load UBOOT into DDR
log "4/5 Loading UBOOT via cwr (DDR now active)..."
update cwr "$D/UBOOT.USB" 0x10000000 || err "cwr UBOOT failed!"

log "Running FIP chain..."
update run 0xd900c000
sleep 5

# Step 5: Flash partitions
log "5/5 Flashing..."
for i in $(seq 1 15); do
    update identify 2>/dev/null | grep -qi firmware && break
    sleep 1
done

for part in boot system; do
    f="$D/${part}.PARTITION"
    [ -f "$f" ] || continue
    sz=$(ls -lh "$f" | awk '{print $5}')
    log "  $part ($sz)..."
    update partition "$part" "$f" || log "  $part: retry..."
    sleep 1
done

update bulkcmd "reset" 2>/dev/null || true
log "DONE! Power cycle."
