"""Парсинг SMBIOS/DMI (dmidecode) — резервный источник данных о памяти.

На серверных и «серверных по дизайну» платах (X99 и т.п.) SPD EEPROM
физически подключена к SMLink/ME, невидимым из ОС; BIOS читает их в SMM и
пишет результат в SMBIOS. Это тот же путь, которым идёт CPU-Z, когда SPD
через SMBus недоступен.
"""
import re
import subprocess


def _run_dmidecode(types="16,17"):
    r = subprocess.run(["dmidecode", "-t", types], capture_output=True, text=True)
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError(f"dmidecode: {r.stderr.strip() or 'нужен root'}")
    return r.stdout


def _field(block, name):
    m = re.search(rf"^\s*{re.escape(name)}:\s*(.+)$", block, re.M)
    return m.group(1).strip() if m else None


def parse_dmi(types="16,17"):
    out = _run_dmidecode(types)
    result = {"arrays": [], "devices": []}
    for block in out.split("\n\n"):
        t = re.search(r"DMI type (\d+)", block)
        if not t:
            continue
        t = int(t.group(1))
        if t == 16:
            result["arrays"].append({
                "location": _field(block, "Location"),
                "use": _field(block, "Use"),
                "ecc": _field(block, "Error Correction Type"),
                "max_size_mb": _field(block, "Maximum Capacity"),
            })
        elif t == 17:
            size = _field(block, "Size")
            if not size or size.startswith("No Module"):
                continue
            def num(s):
                if not s:
                    return None
                m = re.match(r"(\d+(?:\.\d+)?)", s)
                return float(m.group(1)) if m else None
            rank = _field(block, "Rank")
            result["devices"].append({
                "locator": _field(block, "Locator"),
                "bank": _field(block, "Bank Locator"),
                "size_mb": num(size.replace(" MB", "")) if "MB" in (size or "") else
                          (num(size.replace(" GB", "")) * 1024 if "GB" in (size or "") else None),
                "form_factor": _field(block, "Form Factor"),
                "type": _field(block, "Type"),
                "speed_mts": num(_field(block, "Speed")),
                "configured_speed_mts": num(_field(block, "Configured Memory Speed")),
                "manufacturer": _field(block, "Manufacturer"),
                "serial": _field(block, "Serial Number"),
                "part_number": _field(block, "Part Number"),
                "asset_tag": _field(block, "Asset Tag"),
                "ranks": int(rank.split()[0]) if rank and rank[0].isdigit() else None,
                "data_width": _field(block, "Data Width"),
                "total_width": _field(block, "Total Width"),
                "voltage_min_v": num(_field(block, "Minimum Voltage")),
                "voltage_max_v": num(_field(block, "Maximum Voltage")),
                "voltage_configured_v": num(_field(block, "Configured Voltage")),
            })
    return result


# Небольшая база по серверным модулям: DMI таких плат часто не отдаёт
# напряжение (Unknown), а оно известно из даташита по партномеру.
PART_DB = [
    # (префикс партномера, тип, напряжение V, комментарий)
    ("M386B4G70DM0", "DDR3L RDIMM ECC 4Rx4", 1.35, "Samsung 8Gb die, 1.35V"),
    ("M393B4G70DM0", "DDR3L RDIMM ECC 4Rx4", 1.35, "Samsung, 1.35V"),
    ("M393B2G70QH0", "DDR3L RDIMM ECC 2Rx4", 1.35, "Samsung, 1.35V"),
    ("M393B1G70QH0", "DDR3L RDIMM ECC 2Rx4", 1.35, "Samsung, 1.35V"),
    ("HMA421U7AFP4N", "DDR4 RDIMM ECC 2Rx4", 1.20, "Hynix"),
    ("HMA82GR7AFR4N", "DDR4 RDIMM ECC 2Rx4", 1.20, "Hynix"),
    ("CT12872",      "DDR3 ECC UDIMM", 1.50, "Crucial"),
    ("MT36KSF2G72PZ", "DDR3 ECC UDIMM", 1.50, "Micron"),
    ("MT18KDF1G72PZ", "DDR4 ECC UDIMM", 1.20, "Micron"),
]


def lookup_part(part_number):
    if not part_number:
        return None
    pn = part_number.strip().upper()
    for prefix, kind, volts, note in PART_DB:
        if pn.startswith(prefix.upper()):
            return {"kind": kind, "voltage_v": volts, "note": note}
    return None
