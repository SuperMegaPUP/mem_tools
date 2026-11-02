"""Обнаружение DIMM на i2c-шинах и чтение SPD EEPROM.

Стратегии чтения по типу памяти:
  * DDR2/DDR3 (24c001/24c512): SMBus Read Byte Data, 1-байтный адрес,
    окно 0..255; для DDR3 дополнительно пробуем 256..511 через I2C_RDWR
    (2-байтный адрес) — vendor-область, не обязательна.
  * DDR4 (EE1004/SPD5118): 512 байт, один адрес 0x50-0x57; выбор
    256-байтовой страницы записью (Send Byte) по адресу 0x36 (стр.0)
    или 0x37 (стр.1) на той же шине. Схема 1:1 как в ядровом ee1004.
  * DDR5 (SPD5118 в режиме I3C/I2C hub): 2-байтный адрес через I2C_RDWR,
    best-effort.
"""
import os
from .transport import SmbusBus, NackError, SmbusError

EE1004_SET_PAGE = 0x36          # 0x36 = страница 0, 0x37 = страница 1

TYPE_NAMES = {
    0x04: "SDR SDRAM", 0x06: "DDR SDRAM", 0x07: "DDR SGRAM",
    0x08: "DDR2 SDRAM", 0x0B: "DDR3 SDRAM", 0x09: "FB-DIMM",
    0x0C: "DDR4 SDRAM", 0x0E: "DDR4E SDRAM", 0x0F: "LPDDR3 SDRAM",
    0x10: "LPDDR4 SDRAM", 0x11: "LPDDR4X SDRAM",
    0x12: "DDR5 SDRAM", 0x13: "LPDDR5 SDRAM",
}

# семейство по ключевому байту 2 (DDR5 — по байту 1)
FAMILY = {
    0x08: "DDR2", 0x0B: "DDR3", 0x0F: "DDR3",
    0x0C: "DDR4", 0x0E: "DDR4", 0x10: "DDR4", 0x11: "DDR4",
    0x12: "DDR5", 0x13: "DDR5",
}

# имена адаптеров, на которых DIMM быть не может (DDC мониторов GPU)
_SKIP_HINTS = ("drm_dp", "ddc", "nvidia i2c", "aux", "dpddc")


def list_buses(only_dimm_capable=True):
    """[(nr, name)] всех i2c-адаптеров; по умолчанию только способные
    быть SMBus-шиной чипсета (не DDC-адаптеры видеокарт)."""
    out = []
    base = "/sys/bus/i2c/devices"
    try:
        entries = sorted(os.listdir(base))
    except OSError:
        return out
    for e in entries:
        if not e.startswith("i2c-"):
            continue
        nr = e[4:]
        if not nr.isdigit():
            continue
        name = ""
        try:
            with open(os.path.join(base, e, "name")) as f:
                name = f.read().strip()
        except OSError:
            pass
        if only_dimm_capable:
            low = name.lower()
            if any(h in low for h in _SKIP_HINTS):
                continue
        out.append((int(nr), name or f"i2c-{nr}"))
    return out


class Spd:
    def __init__(self, bus_nr, bus_name, addr, kind, data):
        self.bus_nr = bus_nr
        self.bus_name = bus_name
        self.addr = addr
        self.kind = kind          # DDR2/DDR3/DDR4/DDR5/Unknown
        self.type_name = TYPE_NAMES.get(data[2] if len(data) > 2 else -1,
                                        "Unknown")
        self.data = data          # bytes, индекс = номер байта SPD

    @property
    def label(self):
        return f"i2c-{self.bus_nr} @ 0x{self.addr:02x}"


def _read_page0_255(bus, addr):
    """0..255 через SMBus Read Byte Data; None если первый байт не читается."""
    first = bus.read_byte_data(addr, 0)
    if first is None:
        return None
    data = bytearray([first])
    for off in range(1, 256):
        b = bus.read_byte_data(addr, off)
        data.append(0xFF if b is None else b)
    return bytes(data)


def _ee1004_get_page(bus):
    """0 или 1 — какая страница выбрана сейчас (ACK на 0x36 => стр.0).
    None если механизму страниц нет (нет устройства 0x36/0x37)."""
    ack0 = bus.read_byte(EE1004_SET_PAGE)
    if ack0 is not None:
        return 0
    ack1 = bus.read_byte(EE1004_SET_PAGE + 1)
    # NACK на 0x36 и любой ответ на 0x37 => активна страница 1
    return 1


def _ee1004_set_page(bus, page):
    bus.write_byte(EE1004_SET_PAGE + page, 0x00)
    # некоторые модули выбирают страницу, но не отвечают — проверим
    return _ee1004_get_page(bus) == page


def _read_ddr4(bus, addr):
    cur = _ee1004_get_page(bus)
    if cur is None:
        cur = 0
    if cur != 0 and not _ee1004_set_page(bus, 0):
        return None
    lo = _read_page0_255(bus, addr)
    if lo is None:
        return None
    hi = b""
    if _ee1004_set_page(bus, 1):
        hi = _read_page0_255(bus, addr) or b""
    _ee1004_set_page(bus, cur)          # восстановить
    return lo + hi


def _read_upper_rdwr(bus, addr, start=256, length=256):
    """Старшая половина 24c512 (DDR3) через 2-байтный адрес."""
    out = bytearray()
    while len(out) < length:
        off = start + len(out)
        n = min(64, length - len(out))
        r = bus.rdwr(addr, [0x00, off & 0xFF], n)
        if r is None or len(r) != n:
            return None
        out += r
    return bytes(out)


def _read_ddr5(bus, addr, length=256):
    """SPD5118: запись 2-байтного адреса, затем чтение. best-effort."""
    out = bytearray()
    while len(out) < length:
        off = len(out)
        n = min(64, length - len(out))
        r = bus.rdwr(addr, [off >> 8, off & 0xFF], n)
        if r is None or len(r) != n:
            if not out:
                # fallback: simple read_byte_data (может работать на части hub)
                first = bus.read_byte_data(addr, 0)
                if first is None:
                    return None
                out.append(first)
                for o in range(1, 128):
                    b = bus.read_byte_data(addr, o)
                    out.append(0xFF if b is None else b)
                return bytes(out)
            return bytes(out)
        out += r
    return bytes(out)


def probe_dimms(bus_nr, bus_name=None, addrs=range(0x50, 0x58)):
    """Найти и прочитать все SPD EEPROM на шине bus_nr."""
    results = []
    try:
        bus = SmbusBus(bus_nr)
    except PermissionError:
        raise
    except OSError as e:
        raise SmbusError(f"Не открыть /dev/i2c-{bus_nr}: {e.strerror}", e.errno)
    with bus:
        for addr in addrs:
            try:
                first = bus.read_byte_data(addr, 0)
            except SmbusError:
                continue
            if first is None:
                continue
            b1 = bus.read_byte_data(addr, 1)
            b2 = bus.read_byte_data(addr, 2)
            if b1 is None or b2 is None:
                continue
            kind = FAMILY.get(b2)
            if kind is None and b1 == 0x12:
                kind = "DDR5"
            kind = kind or f"Unknown(0x{b2:02x})"
            data = None
            if kind == "DDR4":
                data = _read_ddr4(bus, addr)
            elif kind == "DDR5":
                data = _read_ddr5(bus, addr)
            if data is None:
                data = _read_page0_255(bus, addr)
                if data is None:
                    continue
                if kind == "DDR3":
                    up = _read_upper_rdwr(bus, addr)
                    if up:
                        data += up
            results.append(Spd(bus_nr, bus_name or f"i2c-{bus_nr}",
                               addr, kind, data))
    return results


def scan_all(addrs=range(0x50, 0x58)):
    """Обход всех подходящих SMBus-шин."""
    dimms, bus_list = [], []
    for nr, name in list_buses():
        bus_list.append((nr, name))
        try:
            dimms.extend(probe_dimms(nr, name, addrs))
        except SmbusError:
            continue
    return dimms, bus_list
