#!/usr/bin/env bash
# Якорь нагрузки: package W (RAPL) + напряжения nct6793 до/во время/после.
H=/sys/class/hwmon/hwmon2
R=/sys/class/powercap/intel-rapl:0

read_power() {  # $1 = метка окна, $2 = секунд
    local e1 e2
    e1=$(cat "$R/energy_uj")
    sleep "$2"
    e2=$(cat "$R/energy_uj")
    echo "$1: $(( (e2 - e1) / 1000000 / 1 )) Вт (окно ${2}с, Δ=$(( (e2-e1)/1000 )) мДж)"
}

read_v() {
    local out=""
    for i in 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14; do
        out="$out in$i=$(cat $H/in${i}_input)"
    done
    echo "$1:$out"
}

echo "constraint: $(cat $R/constraint_0_power_limit_uw) мкВт ($(cat $R/constraint_0_name))"
echo "--- покой ---"
read_v "V-до"
read_power "покой" 4
echo "--- нагрузка CPU (2 ядра, ~10 c) ---"
( yes >/dev/null & Y1=$!; yes >/dev/null & Y2=$!
  read_v "V-во-время"
  read_power "нагрузка" 6
  kill $Y1 $Y2 2>/dev/null )
echo "--- после ---"
read_v "V-после"
read_power "после" 4
echo "fan2=$(cat $H/fan2_input) temp7=$(cat $H/temp7_input)"
