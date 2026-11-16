#!/usr/bin/env bash
# Разведка: RAPL-домены + nct6793 (только чтение).
echo "=== RAPL: все домены ==="
for r in /sys/class/powercap/intel-rapl:*/ /sys/class/powercap/intel-rapl:0:*/; do
    [ -d "$r" ] || continue
    n=$(cat "$r/name" 2>/dev/null)
    e=$(cat "$r/energy_uJ" 2>/dev/null)
    m=$(cat "$r/max_energy_range_uJ" 2>/dev/null)
    en=$(cat "$r/enabled" 2>/dev/null)
    echo "$n | $r | energy=$e | max=$m | enabled=$en"
done
echo "=== RAPL package-0: файлы ==="
ls /sys/class/powercap/intel-rapl:0/ 2>/dev/null
echo "=== nct6793: веера и температуры ==="
H=/sys/class/hwmon/hwmon2
for f in "$H"/fan*_input "$H"/temp*_input; do
    [ -e "$f" ] && echo "$(basename "$f"): $(cat "$f")"
done
echo "=== nct6793: напряжения дважды (стабильность) ==="
paste <(cat "$H"/in*_input) <(sleep 2; cat "$H"/in*_input) | head -20
