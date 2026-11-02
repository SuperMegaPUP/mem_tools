"""Общие утилиты декодирования SPD (порт хелперов decode-dimms)."""
import math

from .jep106 import JEP106

MODULE_TYPES_DDR3 = [
    "Undefined", "RDIMM", "UDIMM", "SO-DIMM", "Micro-DIMM", "Mini-RDIMM",
    "Mini-UDIMM", "Mini-CDIMM", "72b-SO-UDIMM", "72b-SO-RDIMM",
    "72b-SO-CDIMM", "LRDIMM", "16b-SO-DIMM", "32b-SO-DIMM",
]

MODULE_TYPES_DDR4 = [
    "Extended type", "RDIMM", "UDIMM", "SO-DIMM", "LRDIMM", "Mini-RDIMM",
    "Mini-UDIMM", "Reserved", "72b-SO-RDIMM", "72b-SO-UDIMM", "Reserved",
    "Reserved", "16b-SO-DIMM", "32b-SO-DIMM", "Reserved", "No base memory",
]


def ceil(x):
    return int(math.ceil(x - 1e-12)) if abs(x - round(x)) > 1e-9 else int(round(x))


def parity(n):
    return bin(n).count("1") & 1


def spd_written(*bs):
    """byte-поле считается записанным, если оно не all-00 и не all-FF."""
    all00 = all(b == 0x00 for b in bs)
    allff = all(b == 0xFF for b in bs)
    return not (all00 or allff)


def jep106_name(count_byte, code_byte):
    """JEP106: count_byte — число ведущих 0x7F (включая бит чётности),
    code_byte — код производителя с битом чётности."""
    if count_byte == 0xFF and code_byte == 0xFF:
        return "Undefined"
    count = count_byte & 0x7F
    code = code_byte & 0x7F
    if parity(code_byte) != 1 or code == 0:
        return "Invalid"
    if count >= len(JEP106) or code - 1 >= len(JEP106[count]):
        return "Unknown"
    name = JEP106[count][code - 1]
    name = name.split(" (former")[0]
    if parity(count_byte) != 1:
        name += "? (Invalid parity)"
    return name


def manufacture_date(year, week):
    if (year & 0xF0) <= 0x90 and (year & 0x0F) <= 0x09 \
       and (week & 0xF0) <= 0x90 and (week & 0x0F) <= 0x09:
        return "%d%02X-W%02X" % (19 if year >= 0x80 else 20, year, week)
    if year <= 99 and 1 <= week <= 53:
        return "%d%02d-W%02d" % (19 if year >= 80 else 20, year, week)
    return "0x%02X%02X" % (year, week)


def part_number(bs):
    s = ""
    for b in bs:
        if 32 <= b < 127:
            s += chr(b)
        else:
            break
    return s.rstrip() or "Undefined"


def location_code(code):
    letter = chr(code)
    if not spd_written(code):
        return None
    return letter if letter.isalnum() else "0x%02X" % code


def ref_card(rrc, ext):
    """DDR3/DDR4 reference card (порт ddr3_reference_card)."""
    alphabet = "ABCDEFGHJKLMNPRTUVWY"
    ref = rrc & 0x1F
    revision = ext >> 5
    if ref == 0x1F:
        return "ZZ"
    if rrc & 0x80:
        ref += 0x1F
    if revision == 0:
        revision = (rrc >> 5) & 0x03
    if ref < len(alphabet):
        card = alphabet[ref]
    else:
        ref1 = ref // len(alphabet)
        ref -= len(alphabet) * ref1
        card = alphabet[ref1] + alphabet[ref]
    return f"{card} revision {revision}"


def crc16_ccitt(data):
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0), как в decode-dimms."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def adjust_ctime(ctime, ftb_ns):
    """Округление tCK к стандартным значениям (порт ddr3_adjust_ctime)."""
    for ii in range(7, 15):
        step = 7.5 / ii
        if step - ftb_ns < ctime < step + ftb_ns:
            return step
    return ctime


def cas_string(cas_list):
    return ", ".join(f"{c}T" for c in sorted(set(cas_list), reverse=True)) or "None"
