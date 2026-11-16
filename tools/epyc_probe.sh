#!/usr/bin/env bash
# Разведка сенсоров EPYC-сервера (только чтение).
dmidecode -s system-manufacturer
dmidecode -s system-product-name
echo "=== все SDR с DIMM (включая выключенные) ==="
ipmitool sdr elist | grep -i dimm
echo "=== i2c-шины ==="
i2cdetect -l
echo "=== EDAC ==="
ls /sys/devices/system/edac/mc/ 2>/dev/null | head -4
for m in /sys/devices/system/edac/mc/mc*/; do
    [ -e "$m/ce_count" ] && echo "$(basename $m): ce=$(cat $m/ce_count) ue=$(cat $m/ue_count)"
done
