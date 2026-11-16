#!/usr/bin/env bash
# Мгновенное потребление CPU-пакета (RAPL), окно $1 секунд (по умолчанию 5).
R=/sys/class/powercap/intel-rapl:0
S=${1:-5}
e1=$(cat "$R/energy_uj"); t1=$(date +%s%N)
sleep "$S"
e2=$(cat "$R/energy_uj"); t2=$(date +%s%N)
awk -v de=$((e2 - e1)) -v dt=$((t2 - t1)) -v lim=$(cat "$R/constraint_0_power_limit_uw") \
    -v tot=$(cat "$R/energy_uj") -v mx=$(cat "$R/max_energy_range_uj") 'BEGIN {
    w = de / 1e6 / (dt / 1e9)
    printf "CPU package: %.1f Вт за окно %.1f с\n", w, dt / 1e9
    printf "Лимит (long_term): %.0f Вт → загрузка по энергии %.0f%%\n", lim / 1e6, w / (lim / 1e6) * 100
    printf "Энергия с загрузки: %.1f кДж (аппаратный цикл %.0f кДж, обороты досчитывает ядро)\n", \
        tot / 1e6, mx / 1e6
}'
grep -m1 MHz /proc/cpuinfo | sed 's/^/Частота сейчас: /'
