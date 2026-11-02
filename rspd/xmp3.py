"""Декодер Intel XMP профилей в SPD DDR3 (байты 176-254).

Layout сверен по двум независимым реализациям: mikebdp2/ddr3spd (C)
и rigred/spd_tool (MIT), а также Intel XMP Spec Rev 1.1.
"""


def _bits(v, hi, lo):
    return (v >> lo) & ((1 << (hi - lo + 1)) - 1)


def decode_xmp(data):
    if len(data) < 220 or data[176] != 0x0C or data[177] != 0x4A:
        return None

    b178, b179 = data[178], data[179]
    hdr = {
        "version": f"{_bits(b179, 7, 4)}.{_bits(b179, 3, 0)}",
        "p1_enabled": bool(b178 & 0x01),
        "p2_enabled": bool(b178 & 0x02),
        "p1_dimms_per_channel": _bits(b178, 3, 2) + 1,
        "p2_dimms_per_channel": _bits(b178, 5, 4) + 1,
    }

    def mtb_ns(dd_off, dv_off):
        dd, dv = data[dd_off], data[dv_off]
        if dv == 0:
            return (data[10] or 1) / (data[11] or 1)    # базовый MTB, ns
        return dd / dv                                  # ns

    def voltage(vb):
        units = _bits(vb, 6, 5)
        tenths = _bits(vb, 4, 1)
        twentieth = _bits(vb, 0, 0)
        return round(units + tenths / 10.0 + (0.05 if twentieth else 0.0), 3)

    def cas_bitmap(b0, b1):
        out = [4 + i for i in range(8) if b0 & (1 << i)]
        out += [12 + i for i in range(7) if b1 & (1 << i)]
        return out

    def profile(base, mtb, idx):
        tck = data[base + 1] * mtb
        if data[base + 1] == 0 or tck <= 0:
            return None
        ns = lambda v: v * mtb
        upper = data[base + 9]
        tAA = ns(data[base + 2])
        tRP = ns(data[base + 6])
        tRCD = ns(data[base + 7])
        tRAS = ns(((upper & 0x0F) << 8) | data[base + 10])
        tRC = ns(((upper >> 4) << 8) | data[base + 11])
        tRFC = ns((data[base + 14] | (data[base + 15] << 8)) & 0xFFFF)
        tRRD = ns(data[base + 17])
        tRTP = ns(data[base + 16])
        tFAW = ns(((_bits(data[base + 18], 3, 0)) << 8) | data[base + 19])
        tWR = ns(data[base + 8])
        tWTR = ns(data[base + 20])
        import math
        cl = lambda v: int(math.ceil(v / tck - 1e-9))
        mts = int(2000.0 / tck)
        return {
            "profile": idx,
            "voltage_v": voltage(data[base]),
            "speed_mts": mts,
            "tCK_ns": round(tck, 4),
            "timings": f"{cl(tAA)}-{cl(tRCD)}-{cl(tRP)}-{cl(tRAS)}",
            "cas_supported": cas_bitmap(data[base + 3], data[base + 4]),
            "timings_ns": {
                "tAA": round(tAA, 3), "tRCD": round(tRCD, 3),
                "tRP": round(tRP, 3), "tRAS": round(tRAS, 3),
                "tRC": round(tRC, 3), "tRFC": round(tRFC, 3),
                "tRRD": round(tRRD, 3), "tRTP": round(tRTP, 3),
                "tWR": round(tWR, 3), "tWTR": round(tWTR, 3),
                "tFAW": round(tFAW, 3),
            },
        }

    out = {"header": hdr, "profiles": []}
    if hdr["p1_enabled"]:
        p = profile(185, mtb_ns(180, 181), 1)
        if p:
            out["profiles"].append(p)
    if hdr["p2_enabled"]:
        p = profile(220, mtb_ns(182, 183), 2)
        if p:
            out["profiles"].append(p)
    return out
