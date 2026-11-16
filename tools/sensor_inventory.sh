#!/usr/bin/env bash
# Полный инвентарь сенсоров сервера (только чтение).
echo "===== BMC: сколько сенсоров по типам ====="
ipmitool sdr elist | awk -F'|' '{print $2}' | awk '{print $NF}' | sort | uniq -c | sort -rn
echo "===== BMC: все сенсоры с показаниями ====="
ipmitool sdr elist | grep -v "ns " | awk -F'|' '{gsub(/^ +| +$/,"",$1); gsub(/^ +| +$/,"",$5); printf "%-22s %s\n", $1, $5}'
echo "===== BMC: без показаний (забиты, но могут ожить) ====="
ipmitool sdr elist | grep "ns " | awk -F'|' '{gsub(/^ +| +$/,"",$1); printf "%s ", $1}'; echo
echo "===== BMC: производитель/прошивка ====="
ipmitool mc info | grep -E "Firmware|Manufacturer"
echo "===== AMD energy (amd_energy PMU) ====="
ls /sys/devices/amd_energy* 2>/dev/null && for f in /sys/devices/amd_energy*/energy*_input; do [ -e "$f" ] && echo "$f=$(cat $f)"; done
echo "===== GPU ====="
nvidia-smi --query-gpu=name,temperature.gpu,power.draw,power.limit,temperature.memory --format=csv,noheader 2>/dev/null || echo "nvidia-smi нет"
echo "===== NVMe ====="
for d in /sys/class/nvme/nvme*; do [ -e "$d/hwmon" ] && echo "$(basename $d) $(cat /sys/class/nvme/*/model 2>/dev/null | head -1): temp=$(cat $d/hwmon*/temp1_input 2>/dev/null)"; done
echo "===== NIC ====="
cat /sys/class/hwmon/hw1/temp1_label 2>/dev/null; cat /sys/class/hwmon/hw1/temp1_input 2>/dev/null
echo "===== thermal zones ====="
for z in /sys/class/thermal/thermal_zone*; do echo "$(cat $z/type)=$(cat $z/temp)"; done 2>/dev/null
