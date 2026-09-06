#!/bin/bash
# ==========================================================
# flash.sh - flash ESP32-S3 with binaries from bins/
#
# Usage:
#   ./flash.sh                  flash fw_1.bin (no erase)
#   ./flash.sh -e               erase flash + flash fw_1.bin
#   ./flash.sh -f fw_2.bin      flash another firmware from bins/
#   ./flash.sh -e -f fw_2.bin   erase + another firmware
#   ./flash.sh -m               open logs (screen) right after flashing
#
# Addresses (ESP32-S3, verified against partition-table.bin):
#   0x0      bootloader.bin
#   0x8000   partition-table.bin
#   0x10000  fw_*.bin (factory app)
# ==========================================================

set -e

CHIP="esp32s3"
BAUD="460800"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BINS_DIR="$SCRIPT_DIR/bins"
APP_BIN="fw_1.bin"
DO_ERASE=0
DO_MONITOR=0

# --- parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        -e|--erase)   DO_ERASE=1; shift ;;
        -f|--fw)      APP_BIN="$2"; shift 2 ;;
        -m|--monitor) DO_MONITOR=1; shift ;;
        -h|--help)    grep '^#' "$0" | head -16; exit 0 ;;
        *) echo "Unknown argument: $1 (help: ./flash.sh -h)"; exit 1 ;;
    esac
done

# --- esptool: prefer the course venv if present ---
if [[ -x "$SCRIPT_DIR/../.venv/bin/esptool" ]]; then
    ESPTOOL="$SCRIPT_DIR/../.venv/bin/esptool"
elif command -v esptool >/dev/null; then
    ESPTOOL="esptool"
else
    echo "ERROR: esptool not found. Activate venv or: pip install esptool"
    exit 1
fi

# --- check binaries exist ---
for f in bootloader.bin partition-table.bin "$APP_BIN"; do
    if [[ ! -f "$BINS_DIR/$f" ]]; then
        echo "ERROR: missing file $BINS_DIR/$f"
        echo "Contents of bins/:"; ls "$BINS_DIR"
        exit 1
    fi
done

# --- find port ---
PORT=$(ls /dev/cu.usbserial* 2>/dev/null | head -1)
if [[ -z "$PORT" ]]; then
    PORT=$(ls /dev/cu.SLAB* 2>/dev/null | head -1)
fi
if [[ -z "$PORT" ]]; then
    echo "ERROR: board not found (no /dev/cu.usbserial*)."
    echo "Check the cable. Ports in the system:"; ls /dev/cu.*
    exit 1
fi

echo "=========================================="
echo " Port:      $PORT"
echo " Chip:      $CHIP"
echo " Firmware:  $APP_BIN"
echo " Erase:     $([[ $DO_ERASE -eq 1 ]] && echo YES || echo no)"
echo "=========================================="

# --- erase (optional) ---
if [[ $DO_ERASE -eq 1 ]]; then
    echo ">>> Erasing entire flash..."
    "$ESPTOOL" --chip "$CHIP" --port "$PORT" erase-flash
fi

# --- flash ---
echo ">>> Flashing..."
"$ESPTOOL" --chip "$CHIP" --port "$PORT" --baud "$BAUD" write-flash \
    0x0      "$BINS_DIR/bootloader.bin" \
    0x8000   "$BINS_DIR/partition-table.bin" \
    0x10000  "$BINS_DIR/$APP_BIN"

echo ""
echo ">>> DONE. View logs: screen $PORT 115200   (exit: Ctrl+A, K, y)"

# --- monitor (optional) ---
if [[ $DO_MONITOR -eq 1 ]]; then
    echo ">>> Opening logs in 2 seconds..."
    sleep 2
    screen "$PORT" 115200
fi
