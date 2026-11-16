/*
 * conf1smn — SMN-порт через классический порт конфигурации 0xCF8/0xCFD
 * (conf1), а не ECAM: вдруг BIOS блокирует только ECAM-путь к RC.
 * Только чтение (кроме записи индекса — это сам порт).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/io.h>

static uint32_t cfg_r(uint8_t bus, uint8_t dev, uint8_t fn, int reg)
{
    outl(0x80000000u | ((uint32_t)bus << 16) | ((uint32_t)dev << 11) |
         ((uint32_t)fn << 8) | ((uint32_t)reg & 0xfcu), 0xcf8);
    return inl(0xcfc);
}

static void cfg_w(uint8_t bus, uint8_t dev, uint8_t fn, int reg, uint32_t v)
{
    outl(0x80000000u | ((uint32_t)bus << 16) | ((uint32_t)dev << 11) |
         ((uint32_t)fn << 8) | ((uint32_t)reg & 0xfcu), 0xcf8);
    outl(v, 0xcfc);
}

int main(int argc, char **argv)
{
    if (iopl(3)) {
        perror("iopl (root?)");
        return 1;
    }
    uint8_t bus = argc > 3 ? (uint8_t)strtol(argv[3], NULL, 0) : 0;
    printf("vendor:dev RC bus%02x: %08x\n", bus, cfg_r(bus, 0, 0, 0));
    printf("конфиг 0x60: %08x  0x64: %08x\n", cfg_r(bus, 0, 0, 0x60),
           cfg_r(bus, 0, 0, 0x64));
    cfg_w(bus, 0, 0, 0x60, 0x12345678u);
    printf("после записи паттерна 0x60: %08x  0x64: %08x\n",
           cfg_r(bus, 0, 0, 0x60), cfg_r(bus, 0, 0, 0x64));
    const uint32_t probe[] = {0x0u, 0x05990060u, 0x05a30060u};
    for (unsigned i = 0; i < 3; i++) {
        cfg_w(bus, 0, 0, 0x60, probe[i]);
        printf("SMN %08x -> %08x\n", probe[i], cfg_r(bus, 0, 0, 0x64));
    }
    return 0;
}
