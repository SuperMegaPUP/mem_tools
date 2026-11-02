/* cf8peek — сырое чтение конфигурационного пространства PCI через CF8/CFC.
 * Нужен root и lockdown=[none]; только ЧТЕНИЕ (ни одной записи).
 *
 * usage:
 *   cf8peek scan <bus>              — все устройства шины (vendor:device class)
 *   cf8peek read <bus> <dev> <fn> <off>   — dword по адресу
 *   cf8peek dump <bus> <dev> <fn>   — 256 байт hex-дампа
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/io.h>

static unsigned cf8_read(unsigned bus, unsigned dev, unsigned fn, unsigned off)
{
	unsigned addr = 0x80000000u | ((bus & 0xff) << 16) |
			((dev & 31) << 11) | ((fn & 7) << 8) | (off & 0xfc);
	outl(addr, 0xcf8);
	return inl(0xcfc);
}

int main(int argc, char **argv)
{
	if (iopl(3)) {
		perror("iopl(3)");
		return 1;
	}
	if (argc >= 3 && !strcmp(argv[1], "scan")) {
		unsigned bus = strtoul(argv[2], NULL, 0);
		for (unsigned d = 0; d < 32; d++)
			for (unsigned f = 0; f < 8; f++) {
				unsigned v = cf8_read(bus, d, f, 0);
				if ((v & 0xffff) == 0xffff || v == 0)
					continue;
				unsigned c = cf8_read(bus, d, f, 0x08);
				printf("%02x:%02x.%u %04x:%04x class=%06x\n",
				       bus, d, f, v >> 16, (v >> 0) & 0xffff,
				       c >> 8);
			}
		return 0;
	}
	if (argc >= 6 && !strcmp(argv[1], "read")) {
		unsigned b = strtoul(argv[2], NULL, 0);
		unsigned d = strtoul(argv[3], NULL, 0);
		unsigned f = strtoul(argv[4], NULL, 0);
		unsigned o = strtoul(argv[5], NULL, 0);
		printf("%08x\n", cf8_read(b, d, f, o));
		return 0;
	}
	if (argc >= 5 && !strcmp(argv[1], "dump")) {
		unsigned b = strtoul(argv[2], NULL, 0);
		unsigned d = strtoul(argv[3], NULL, 0);
		unsigned f = strtoul(argv[4], NULL, 0);
		for (unsigned o = 0; o < 256; o += 16) {
			printf("%02x: ", o);
			for (unsigned i = 0; i < 16; i += 4)
				printf("%08x ", cf8_read(b, d, f, o + i));
			printf("\n");
		}
		return 0;
	}
	fprintf(stderr,
		"usage: cf8peek scan <bus> | read <b> <d> <f> <off> | dump <b> <d> <f>\n");
	return 2;
}
