"""Декодер SPD DDR3 (JESD400-5 / Annex K).

Формулы 1:1 портированы из i2c-tools decode-dimms (GPL-2.0+),
b[N] — N-й байт SPD (raw index). Проверено на реальном дампе
сверкой с выводом decode-dimms 4.4.
"""
from .common import (MODULE_TYPES_DDR3, adjust_ctime, cas_string, ceil,
                     crc16_ccitt, jep106_name, location_code, manufacture_date,
                     part_number, ref_card, spd_written)

STANDARD_SPEEDS = (7.5 / 8, 7.5 / 7, 1.25, 1.5, 1.875, 2.5)  # tCK, ns


def _mtb_ftb(b1, b2, mtb_ns, ftb_ns):
    """Время = b1 (MTB, без знака) + b2 (FTB, знаковое ps)."""
    if b2 & 0x80:
        b2 -= 0x100
    return b1 * mtb_ns + b2 * ftb_ns


def decode(b):
    """b — bytes SPD DDR3 (минимум 150 байт, лучше 256+). Возвращает dict."""
    d = {}
    d["spd_revision"] = f"{b[1] >> 4}.{b[1] & 0xF}"
    d["module_type"] = (MODULE_TYPES_DDR3[b[3]] if b[3] < len(MODULE_TYPES_DDR3)
                        else f"Reserved (0x{b[3]:02X})")

    # CRC (байты 126-127 little-endian)
    cover = 116 if (b[0] & 0x80) else 125
    crc_calc = crc16_ccitt(b[:cover + 1])
    crc_stored = (b[127] << 8) | b[126]
    d["crc"] = {"cover": f"0-{cover}", "stored": f"0x{crc_stored:04X}",
                "calc": f"0x{crc_calc:04X}", "ok": crc_stored == crc_calc}

    # размеры EEPROM
    spd_len = (b[0] >> 4) & 7
    total = 64 << (b[0] & 0x0F)
    used = {0: 128, 1: 176, 2: 256, 3: 512}.get(spd_len, 0)
    d["eeprom_bytes_written"] = used
    d["eeprom_bytes_total"] = total

    # временные базы
    if (b[9] & 0x0F) == 0 or b[11] == 0:
        d["error"] = "некорректные временные базы SPD"
        return d
    ftb_ns = ((b[9] >> 4) / (b[9] & 0x0F)) / 1000.0     # ps -> ns
    mtb_ns = b[10] / b[11]                              # уже в ns (напр. 1/8=0.125)

    def t(b1, b2):
        return _mtb_ftb(b1, b2, mtb_ns, ftb_ns)

    # скорость
    ctime = adjust_ctime(t(b[12], b[34]), ftb_ns)
    ddrclk = int(2 * 1000 / ctime)
    tbits = 1 << ((b[8] & 7) + 3)
    pcclk = int(ddrclk * tbits / 8)
    pcclk -= pcclk % 100
    d["speed_mts"] = ddrclk
    d["pcn_rating"] = f"PC3-{pcclk}"

    # объём
    cap = (b[4] & 15) + 28
    cap += (b[8] & 7) + 3
    cap -= (b[7] & 7) + 2
    cap -= 20 + 3
    ranks = ((b[7] >> 3) & 31) + 1
    d["size_mb"] = (1 << cap) * ranks
    d["ranks"] = ranks
    d["banks"] = 1 << (((b[4] >> 4) & 7) + 3)
    d["rows"] = ((b[5] >> 3) & 31) + 12
    d["columns"] = (b[5] & 7) + 9
    d["device_width_bits"] = 1 << ((b[7] & 7) + 2)
    d["bus_width_bits"] = 8 << (b[8] & 7)
    d["bus_width_extension"] = b[8] & 24

    # основные тайминги
    taa = t(b[16], b[35])
    trcd = t(b[18], b[36])
    trp = t(b[20], b[37])
    tras = (((b[21] & 0x0F) << 8) + b[22]) * mtb_ns
    d["core_timings"] = _timings_str(ceil(taa / ctime), ctime, trcd, trp, tras)

    # CAS
    cas_sup = (b[15] << 8) | b[14]
    cas_list = [ii + 4 for ii in range(15) if cas_sup & (1 << ii)]
    d["cas_supported"] = sorted(set(cas_list), reverse=True)

    # тайминги на стандартных скоростях
    at_speed = {}
    for ct in STANDARD_SPEEDS:
        best = 0
        for ii in range(14, -1, -1):
            if not (cas_sup & (1 << ii)):
                continue
            if ceil(taa / ct) <= ii + 4:
                best = ii + 4
        if best and ct >= ctime:
            at_speed[f"DDR3-{int(2000 / ct)}"] = _timings_str(best, ct, trcd, trp, tras)
    d["timings_at_speeds"] = at_speed

    # полные параметры
    d["timings_ns"] = {
        "tCK": round(ctime, 3),
        "tAA": round(taa, 3),
        "tWR": round(b[17] * mtb_ns, 3),
        "tRCD": round(trcd, 3),
        "tRRD": round(b[19] * mtb_ns, 3),
        "tRP": round(trp, 3),
        "tRAS": round(tras, 3),
        "tRC": round(t(((b[21] & 0xF0) << 4) + b[23], b[38]), 3),
        "tRFC": round(((b[25] << 8) + b[24]) * mtb_ns, 3),
        "tWTR": round(b[26] * mtb_ns, 3),
        "tRTP": round(b[27] * mtb_ns, 3),
        "tFAW": round((((b[28] & 15) << 8) + b[29]) * mtb_ns, 3),
    }

    # напряжения
    volts = ["1.5 V"]
    if b[6] & 0x02:
        volts.append("1.35 V")
    if b[6] & 0x04:
        volts.append("1.28/1.25/1.2 V")
    d["operable_voltages"] = volts
    d["voltage_nominal_v"] = 1.35 if (b[6] & 0x02) else 1.5

    # прочее
    mac_tbl = ["Untested", "700 K", "600 K", "500 K", "400 K", "300 K",
               "200 K", None, "Unlimited"]
    mac = b[41] & 0x0F
    d["features"] = {
        "rzq6": bool(b[30] & 1), "rzq7": bool(b[30] & 2),
        "dll_off": bool(b[30] & 128),
        "temp_range_c": f"0-{95 if b[31] & 1 else 85}",
        "thermal_sensor": bool(b[32] & 128),
        "mac": mac_tbl[mac] if mac < len(mac_tbl) else None,
    }
    d["module_height_mm"] = (b[60] & 31) + 15
    d["module_ref_card"] = ref_card(b[62], b[60])

    # производитель (байты 117-149)
    if len(b) >= 150:
        d["module_manufacturer"] = jep106_name(b[117], b[118])
        if spd_written(b[148], b[149]):
            d["dram_manufacturer"] = jep106_name(b[148], b[149])
        loc = location_code(b[119])
        if loc:
            d["manufacturing_location"] = loc
        if spd_written(b[120], b[121]):
            d["manufacturing_date"] = manufacture_date(b[120], b[121])
        if spd_written(b[122], b[123], b[124], b[125]):
            d["serial"] = "0x%02X%02X%02X%02X" % (b[122], b[123], b[124], b[125])
        d["part_number"] = part_number(b[128:146])
        if spd_written(b[146], b[147]):
            d["revision"] = "0x%02X%02X" % (b[146], b[147])

    # XMP (байты 176-254)
    from .xmp3 import decode_xmp
    xmp = decode_xmp(b)
    if xmp:
        d["xmp"] = xmp

    return d


def _timings_str(cl, ctime, trcd, trp, tras):
    return f"{cl}-{ceil(trcd / ctime)}-{ceil(trp / ctime)}-{ceil(tras / ctime)}"
