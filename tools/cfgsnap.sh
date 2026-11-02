#!/bin/bash
# Снимок 4K config всех uncore-устройств шины 0xff:  ./cfgsnap.sh <каталог>
# Запускать от root:  sudo ./cfgsnap.sh ../_refs/cfgsnap_B
set -e
OUT="${1:?usage: cfgsnap.sh <outdir>}"
mkdir -p "$OUT"
for d in /sys/bus/pci/devices/0000:ff:*; do
  n=$(basename "$d")
  dd if="$d/config" of="$OUT/$n.bin" bs=4096 count=1 2>/dev/null || cp "$d/config" "$OUT/$n.bin"
done
dmidecode -t 16 -t 17 > "$OUT/dmi.txt" 2>/dev/null || true
echo "снимок: $(ls "$OUT" | wc -l) файлов в $OUT"
