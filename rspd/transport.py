"""Транспортный слой: SMBus/I2C через ioctl к /dev/i2c-N, без python-smbus.

Реализованы ровно те операции, которые нужны для чтения SPD EEPROM:
  * SMBus Read Byte / Read Byte Data / Send Byte (ioctl I2C_SMBUS)
  * комбинированную I2C-транзакцию write+read (ioctl I2C_RDWR) — для
    24c512 (DDR3, старшая половина) и SPD5118 (DDR5) с 2-байтным адресом.

Числа ioctl и структуры соответствуют linux/i2c.h и linux/i2c-dev.h
(только little-endian x86_64/arm64 — как и весь инструмент).
"""
import ctypes
import errno
import fcntl
import os

I2C_SLAVE = 0x0703
I2C_SMBUS = 0x0720
I2C_RDWR = 0x0707

I2C_SMBUS_WRITE = 0
I2C_SMBUS_READ = 1

I2C_SMBUS_QUICK = 0
I2C_SMBUS_BYTE = 1          # send/receive byte (без регистра)
I2C_SMBUS_BYTE_DATA = 2     # write/read byte data (1-байтный адрес)
I2C_SMBUS_BLOCK_DATA = 4
I2C_SMBUS_I2C_BLOCK_DATA = 8

I2C_M_RD = 0x0001


class SmbusError(OSError):
    """Ошибка шины/NACK."""


class NackError(SmbusError):
    """Устройство не ответило (нет DIMM по адресу / нет стр.)."""


class _SmbusData(ctypes.Union):
    _fields_ = [
        ("b8", ctypes.c_uint8 * 34),
        ("b16", ctypes.c_uint16 * 17),
        ("q", ctypes.c_uint64),
    ]


class _SmbusIoctlData(ctypes.Structure):
    _fields_ = [
        ("rw", ctypes.c_uint8),
        ("cmd", ctypes.c_uint8),
        ("size", ctypes.c_uint32),
        ("data", ctypes.POINTER(_SmbusData)),
    ]


class _I2cMsg(ctypes.Structure):
    _fields_ = [
        ("addr", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("len", ctypes.c_uint16),
        ("buf", ctypes.POINTER(ctypes.c_uint8)),
    ]


class _I2cRdwrData(ctypes.Structure):
    _fields_ = [
        ("msgs", ctypes.POINTER(_I2cMsg)),
        ("nmsgs", ctypes.c_uint32),
    ]


class SmbusBus:
    """Одна i2c-шина (/dev/i2c-N). Потокобезопасность не нужна — читаем
    последовательно; все операции только чтение (кроме page-select для DDR4,
    который по спецификации не изменяет содержимое EEPROM)."""

    def __init__(self, nr):
        self.nr = nr
        self.path = f"/dev/i2c-{nr}"
        self.fd = os.open(self.path, os.O_RDWR)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- низкоуровневая обвязка -------------------------------------------
    def _set_slave(self, addr):
        fcntl.ioctl(self.fd, I2C_SLAVE, addr)

    def _smbus(self, addr, rw, cmd, size, data=None):
        self._set_slave(addr)
        d = _SmbusData()
        if data is not None:
            d.b8[0] = len(data) + 1
            for i, b in enumerate(data):
                d.b8[1 + i] = b
        args = _SmbusIoctlData(rw, cmd, size, ctypes.pointer(d))
        try:
            fcntl.ioctl(self.fd, I2C_SMBUS, args)
        except OSError as e:
            if e.errno in (errno.ENXIO, errno.ENODEV):
                raise NackError(f"NACK от 0x{addr:02x}", e.errno) from None
            if e.errno in (errno.ETIMEDOUT, errno.EAGAIN):
                # i801 block-read: таймаут = "блок короче запрошенного"
                raise
            raise SmbusError(f"Ошибка SMBus 0x{addr:02x}: {os.strerror(e.errno)}",
                             e.errno) from None
        return d

    # -- публичные операции -------------------------------------------------
    def read_byte(self, addr):
        """SMBus Receive Byte. None при NACK."""
        try:
            d = self._smbus(addr, I2C_SMBUS_READ, 0, I2C_SMBUS_BYTE)
        except NackError:
            return None
        return d.b8[0]

    def read_byte_data(self, addr, cmd):
        """SMBus Read Byte Data (1-байтный адрес/смещение). None при NACK."""
        try:
            d = self._smbus(addr, I2C_SMBUS_READ, cmd, I2C_SMBUS_BYTE_DATA)
        except NackError:
            return None
        return d.b8[0]

    def write_byte(self, addr, value):
        """SMBus Send Byte. True если ACK. Используется только для
        DDR4 page-select (адреса 0x36/0x37, содержимое EEPROM не меняется)."""
        try:
            self._smbus(addr, I2C_SMBUS_WRITE, value, I2C_SMBUS_BYTE)
        except NackError:
            return False
        return True

    def rdwr(self, addr, wbuf, rlen):
        """Одна транзакция I2C_RDWR: запись wbuf, затем чтение rlen байт.
        Нужно для устройств с 2-байтным адресом (24c512, SPD5118).
        None если адаптер/устройство не поддерживает."""
        wbuf = bytes(wbuf)
        warr = (ctypes.c_uint8 * len(wbuf)).from_buffer_copy(wbuf)
        rarr = (ctypes.c_uint8 * rlen)()
        msgs = (_I2cMsg * 2)(
            _I2cMsg(addr, 0, len(wbuf), ctypes.cast(warr, ctypes.POINTER(ctypes.c_uint8))),
            _I2cMsg(addr, I2C_M_RD, rlen, ctypes.cast(rarr, ctypes.POINTER(ctypes.c_uint8))),
        )
        args = _I2cRdwrData(ctypes.cast(msgs, ctypes.POINTER(_I2cMsg)), 2)
        try:
            fcntl.ioctl(self.fd, I2C_RDWR, args)
        except OSError:
            return None
        return bytes(rarr)
