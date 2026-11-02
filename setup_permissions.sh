#!/bin/sh
# Однократная настройка доступа к SPD EEPROM для ramspd (запускать от root):
#   su -c '/путь/к/setup_permissions.sh g'
#   или: sudo ./setup_permissions.sh [имя_пользователя]
#
# Делает:
#   1. Загружает i2c-dev и SMBus-контроллер чипсета (i2c_i801 / i2c_piix4).
#   2. Создаёт группу i2c и добавляет в неё пользователя.
#   3. Правило udev: /dev/i2c-* -> группа i2c, режим 0660.
#   4. Автозагрузку модулей при старте системы.
# После этого НУЖНО перезайти в сессию (чтобы группа i2c применилась).
set -eu

if [ "$(id -u)" != 0 ]; then
    echo "Запустите от root: su -c '$0 <имя_пользователя>'" >&2
    exit 1
fi

USER="${1:-${SUDO_USER:-}}"
if [ -z "$USER" ]; then
    echo "Укажите пользователя: $0 <имя_пользователя>" >&2
    exit 1
fi

# 1. Модули ядра
modprobe i2c-dev || true
LOADED=""
for m in i2c_i801 i2c_piix4 i2c_designware_platform amd_isp; do
    if modprobe "$m" 2>/dev/null; then
        LOADED="$LOADED $m"
        echo "Загружен модуль: $m"
    fi
done
if [ -z "$LOADED" ]; then
    echo "ВНИМАНИЕ: SMBus-контроллер не загружен (или это не x86)." >&2
    echo "Посмотрите вывод: i2cdetect -l" >&2
fi

# 2. Группа
groupadd -f i2c
usermod -aG i2c "$USER"
echo "Пользователь $USER добавлен в группу i2c."

# 3. udev-правило (на дистрибутивах без него /dev/i2c-* принадлежат root:root)
cat > /etc/udev/rules.d/99-ramspd-i2c.rules <<'EOF'
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
EOF
udevadm control --reload-rules
udevadm trigger --subsystem-match=i2c 2>/dev/null || true

# 4. Автозагрузка модулей
{
    echo "i2c-dev"
    for m in $LOADED; do echo "$m"; done
} > /etc/modules-load.d/ramspd.conf

echo
echo "Готово. ПЕРЕКРОЙТЕ СЕССИЮ (logout/login или перезагрузка),"
echo "затем проверьте:  python3 ramspd.py"
echo "Без перелогина можно проверить прямо сейчас:  su - $USER -c 'python3 /путь/к/ramspd.py'"
