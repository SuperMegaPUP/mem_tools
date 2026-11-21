#!/usr/bin/env bash
# Разведка потребительской платформы (Intel B760): только чтение.
echo "=== DMI size (формат Arch) ==="
dmidecode -t 17 | grep -E "Size|Configured" | head -8
echo "=== MCHBAR (host bridge 00:00.0, BAR на 0x40) ==="
lo=$(setpci -s 0:0.0 0x40.l)
hi=$(setpci -s 0:0.0 0x44.l)
echo "cfg[0x40]=$lo cfg[0x44]=$hi"
base=$(( 16#$hi * 4294967296 + 16#$lo & ~4095 ))
printf "MCHBAR base: 0x%x\n" $base
echo "=== чтение MCHBAR через /dev/mem (первые разведки) ==="
for off in 0x0 0x40 0x2440 0x2444 0x2448 0x244c 0x2540 0x2544 0x2548 0x2550 0x2554 0x2558 0x2560 0x2564 0x2568 0x256c 0x2570; do
    addr=$((base + 16#$off))
    v=$(dd if=/dev/mem bs=4 skip=$((addr/4)) count=1 2>/dev/null | xxd -p -e)
    printf "MCHBAR+%s: %s\n" "$off" "$v"
done
echo "=== amdgpu hwmon ==="
for h in /sys/class/hwmon/hw*/; do
    if [ "$(cat $h/name)" = amdgpu ]; then
        for t in $h/temp*_input; do
            [ -e "$t" ] && echo "$(cat ${t%_input}_label 2>/dev/null || basename $t): $(cat $t)"
        done
        echo "power: $(cat $h/device/power1_average 2>/dev/null || cat $h/power1_average 2>/dev/null)"
    fi
done
echo "=== SMBus ==="
modprobe i2c_i801 2>/dev/null
i2cdetect -l 2>/dev/null | head -5
bus=$(i2cdetect -l 2>/dev/null | grep -m1 i801 | cut -f1 | cut -d- -f2)
[ -n "$bus" ] && i2cdetect -q -y $bus 0x50 0x57 2>/dev/null | tail -4
echo "=== PCI память-класс ==="
lspci -nn | grep -iE "memory|dram|host" | head -5
