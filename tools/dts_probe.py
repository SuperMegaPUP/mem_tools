#!/usr/bin/env python3
"""Временный зонд: живые температуры DIMM из Thermal Control регистров."""
import struct

names = {"ff:14.0": "MC0-Ch0", "ff:14.1": "MC0-Ch1",
         "ff:17.0": "MC1-Ch0", "ff:17.1": "MC1-Ch1"}
for slot, nm in names.items():
    c = open(f"/sys/bus/pci/devices/0000:{slot}/config", "rb").read()
    v150, v154 = struct.unpack_from("<II", c, 0x150)
    print(f"{slot} {nm}: 0x150[7:0]={v150 & 0xff}°  "
          f"0x154[7:0]={v154 & 0xff}°  (полные: {v150:#x} {v154:#x})")
