"""Декодер SPD DDR4 (JESD400-1). Формулы — порт decode-dimms 4.4."""
from .common import (MODULE_TYPES_DDR4, cas_string, ceil, crc16_ccitt,
                     jep106_name, location_code, manufacture_date,
                     adjust_ctime, part_number, ref_card, spd_written)

STANDARD_SPEEDS = (15 / 24, 15 / 22, 15 / 20, 15 / 18, 15 / 16, 15 / 14, 15 / 12)

MTB = 0.125   # ns
FTB = 0.001   # ns


def _mtb_ftb(b1, b2):
    if b2 & 0x80:
        b2 -= 0x100
    return (b1 * 125 + b2) / 1000.0     # ps -> ns


def decode(b):
    if len(b) < 128:
        return {"error": "мало данных SPD для DDR4 (нужно >= 128 байт)"}
    d = {}
    d["spd_revision"] = f"{b[1] >> 4}.{b[1] & 0xF}"
    d["module_type"] = MODULE_TYPES_DDR4[b[3] & 0x0F]

    if len(b) >= 256:
        crc_calc = crc16_ccitt(b[128:254])
        crc_stored = (b[255] << 8) | b[254]
        d["crc"] = {"cover": "128-253", "stored": f"0x{crc_stored:04X}",
                    "calc": f"0x{crc_calc:04X}", "ok": crc_stored == crc_calc}

    if (b[17] & 0x03) != 0x00 or (b[17] & 0xC0) != 0x00:
        d["error"] = "неизвестные временные базы"
        return d

    ctime = adjust_ctime(_mtb_ftb(b[18], b[125]), FTB)
    ctime_max = _mtb_ftb(b[19], b[124])
    ddrclk = int(2 * 1000 / ctime)
    tbits = 8 << (b[13] & 7)
    pcclk = int(ddrclk * tbits / 8)
    pcclk -= pcclk % 100
    d["speed_mts"] = ddrclk
    d["pcn_rating"] = f"PC4-{pcclk}"

    width = 4 << (b[12] & 0x07)
    ranks = ((b[12] >> 3) & 0x07) + 1
    loading = b[6] & 0x03
    dies = ((b[6] >> 4) & 0x07) + 1
    cap = (256 << (b[4] & 0x0F)) // 8
    cap *= (8 << (b[13] & 0x07)) // width
    cap *= ranks
    if loading == 0x02:
        cap *= dies
    d["size_mb"] = cap
    d["ranks"] = ranks
    d["banks"] = (1 << (b[4] >> 6)) * (4 << ((b[4] >> 4) & 0x03))
    d["rows"] = ((b[5] >> 3) & 7) + 12
    d["columns"] = (b[5] & 7) + 9
    d["device_width_bits"] = width
    d["bus_width_bits"] = 8 << (b[13] & 7)
    d["bus_width_extension"] = b[13] & 0x18

    taa = _mtb_ftb(b[24], b[123])
    trcd = _mtb_ftb(b[25], b[122])
    trp = _mtb_ftb(b[26], b[121])
    tras = (((b[27] & 0x0F) << 8) + b[28]) * MTB
    d["core_timings"] = (f"{ceil(taa / ctime - 0.025)}-"
                         f"{ceil(trcd / ctime - 0.025)}-"
                         f"{ceil(trp / ctime - 0.025)}-"
                         f"{ceil(tras / ctime - 0.025)}")

    cas_sup = int.from_bytes(b[20:24], "little")
    base_cas = 23 if b[23] & 0x80 else 7
    cas = [base_cas + ii for ii in range(30) if cas_sup & (1 << ii)]
    d["cas_supported"] = sorted(set(cas), reverse=True)

    at_speed = {}
    for ct in STANDARD_SPEEDS:
        best = 0
        for ii in range(29, -1, -1):
            if not (cas_sup & (1 << ii)):
                continue
            if ceil(taa / ct - 0.025) <= base_cas + ii:
                best = base_cas + ii
        if best and ctime <= ct <= ctime_max:
            at_speed[f"DDR4-{int(2000 / ct)}"] = (
                f"{best}-{ceil(trcd / ct - 0.025)}-"
                f"{ceil(trp / ct - 0.025)}-{ceil(tras / ct - 0.025)}")
    d["timings_at_speeds"] = at_speed

    def mt(v):
        return round(v * MTB, 3)

    d["timings_ns"] = {
        "tCK": round(ctime, 3),
        "tAA": round(taa, 3),
        "tRCD": round(trcd, 3),
        "tRP": round(trp, 3),
        "tRAS": round(tras, 3),
        "tRC": round(_mtb_ftb(((b[27] & 0xF0) << 4) + b[29], b[120]), 3),
        "tRFC1": mt((b[31] << 8) + b[30]),
        "tRFC2": mt((b[33] << 8) + b[32]),
        "tRFC4": mt((b[35] << 8) + b[34]),
        "tFAW": mt(((b[36] & 0x0F) << 8) + b[37]),
        "tRRD_S": round(_mtb_ftb(b[38], b[119]), 3),
        "tRRD_L": round(_mtb_ftb(b[39], b[118]), 3),
        "tCCD_L": round(_mtb_ftb(b[40], b[117]), 3),
    }
    twr = ((b[41] & 0x0F) << 8) + b[42]
    if twr:
        d["timings_ns"]["tWR"] = mt(twr)
    twtrs = ((b[43] & 0x0F) << 8) + b[44]
    if twtrs:
        d["timings_ns"]["tWTR_S"] = mt(twtrs)
    twtrl = ((b[43] & 0xF0) << 4) + b[45]
    if twtrl:
        d["timings_ns"]["tWTR_L"] = mt(twtrl)

    # напряжение: byte 11 (как decode-dimms; байты 132-135 не декодируем —
    # единицы измерения не верифицированы эталонным декодером)
    volts = []
    if b[11] & 0x01:
        volts.append("1.2 V")
    elif b[11] & 0x02:
        volts.append("1.2 V (endurant)")
    d["operable_voltages"] = volts or ["Unknown"]

    mac_tbl = ["Untested", "700 K", "600 K", "500 K", "400 K", "300 K",
               "200 K", None, "Unlimited"]
    mac = b[7] & 0x0F
    pkg = "Monolithic" if (b[6] & 0x80) == 0 else \
        {1: "Multi-load stack", 2: "3DS"}.get(loading, "Unknown")
    if dies >= 2:
        pkg += f" ({dies} dies)"
    d["features"] = {
        "package": pkg,
        "mac": mac_tbl[mac] if mac < len(mac_tbl) else None,
        "ppr": {0: "Not supported", 1: "One row per bank group"}.get(b[9] >> 6, "Unknown"),
        "thermal_sensor": "TSE2004" if b[14] & 0x80 else "No",
    }
    if len(b) >= 131:
        d["module_ref_card"] = ref_card(b[130], b[128])

    if len(b) >= 352:
        d["module_manufacturer"] = jep106_name(b[320], b[321])
        if spd_written(b[350], b[351]):
            d["dram_manufacturer"] = jep106_name(b[350], b[351])
        loc = location_code(b[322])
        if loc:
            d["manufacturing_location"] = loc
        if spd_written(b[323], b[324]):
            d["manufacturing_date"] = manufacture_date(b[323], b[324])
        if spd_written(b[325], b[326], b[327], b[328]):
            d["serial"] = "0x%02X%02X%02X%02X" % (b[325], b[326], b[327], b[328])
        d["part_number"] = part_number(b[329:349])
        if spd_written(b[349]):
            d["revision"] = "0x%02X" % b[349]
    return d
