"""Decoder for AcuRite 592TXR tower sensors (temperature + humidity).

The 592TXR (model 00592TXR / 00592TXRA2) sends on 433.92 MHz every ~16 s:
three copies of a 56-bit message, each led by four sync pulses. Bits are
pulse-width coded on the high time, with a matching low so every bit lasts
about 600 us:

    sync   ~600 us high, ~600 us low (x4)
    short  ~200 us high, ~400 us low
    long   ~400 us high, ~200 us low

Message (7 bytes), as decoded by rtl_433's Acurite-Tower decoder:

    byte 0  CCII IIII   C: channel (11 = A, 10 = B, 00 = C), I: id high bits
    byte 1  IIII IIII   id low bits (14-bit id, changes on battery swap)
    byte 2  PBMM MMMM   P: parity, B: battery ok, M: message type 0x04
    byte 3  PHHH HHHH   humidity %
    byte 4  P--- TTTT   temperature high bits
    byte 5  PTTT TTTT   temperature low bits; (T - 1000) / 10 = degC
    byte 6  checksum    sum of bytes 0-5, modulo 256

Bytes 2-5 carry even parity in bit 7. Which pulse width means 1 is tried
both ways; only a message whose checksum and parity hold is accepted, so a
wrong guess can never produce a reading.

Same interface as tx2_decode.Tx2Decoder: feed (level, duration_us) pairs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

MESSAGE_BITS = 56

SHORT_MIN_US = 100
SHORT_MAX_US = 310
LONG_MIN_US = 310
LONG_MAX_US = 500
SYNC_MIN_US = 500
# Before the first data bit, anything this long still belongs to the preamble.
PREAMBLE_MIN_US = 460
SYNC_MAX_US = 900
# Any low longer than this ends the message (bit lows are <= ~650 us).
RESET_LOW_US = 1000

# Copies within one burst are reported once.
BURST_WINDOW_S = 3.0

CHANNELS = {3: 'A', 2: 'B', 0: 'C'}


@dataclass(frozen=True)
class AcuriteReading:
    sensor_id: int
    channel: str
    temp_c: float
    humidity: Optional[int]
    battery_ok: bool
    raw: str


def _even_parity(byte: int) -> bool:
    return bin(byte & 0xFF).count('1') % 2 == 0


def _bytes_from_bits(bits: List[int]) -> List[int]:
    out = []
    for i in range(0, MESSAGE_BITS, 8):
        value = 0
        for bit in bits[i:i + 8]:
            value = (value << 1) | bit
        out.append(value)
    return out


def message_to_reading(message: List[int]) -> Optional[AcuriteReading]:
    """Validate 7 bytes and turn them into a reading, or None."""
    if len(message) != 7:
        return None
    if sum(message[:6]) & 0xFF != message[6]:
        return None
    if not all(_even_parity(b) for b in message[2:6]):
        return None
    if message[2] & 0x3F != 0x04:
        return None
    channel = CHANNELS.get((message[0] >> 6) & 0x3)
    if channel is None:
        return None
    humidity = message[3] & 0x7F
    temp_raw = ((message[4] & 0x0F) << 7) | (message[5] & 0x7F)
    temp_c = round((temp_raw - 1000) / 10.0, 1)
    if not -40.0 <= temp_c <= 70.0 or humidity > 100:
        return None
    return AcuriteReading(
        sensor_id=((message[0] & 0x3F) << 8) | message[1],
        channel=channel,
        temp_c=temp_c,
        humidity=humidity if humidity > 0 else None,
        battery_ok=bool(message[2] & 0x40),
        raw=''.join('%02x' % b for b in message),
    )


def bits_to_reading(bits: List[int]) -> Optional[AcuriteReading]:
    """Try the bits as sent, then inverted."""
    if len(bits) < MESSAGE_BITS:
        return None
    bits = bits[:MESSAGE_BITS]
    for candidate in (bits, [1 - b for b in bits]):
        reading = message_to_reading(_bytes_from_bits(candidate))
        if reading is not None:
            return reading
    return None


class AcuriteTowerDecoder:
    """Streaming pulse-width decoder for the 592TXR."""

    def __init__(self, on_reading: Callable[[AcuriteReading], None],
                 on_frame: Optional[Callable[[str], None]] = None) -> None:
        self._on_reading = on_reading
        self._on_frame = on_frame
        self._bits: List[int] = []
        self._synced = False
        self._last_raw = ''
        self._last_time = -1e9

    def feed(self, level: int, duration_us: float, now_s: float) -> None:
        if level:
            in_preamble = self._synced and not self._bits and duration_us >= PREAMBLE_MIN_US
            if in_preamble or SYNC_MIN_US <= duration_us <= SYNC_MAX_US:
                # A sync pulse closes any message in progress and opens the next.
                self._finish(now_s)
                self._synced = True
                return
            if not self._synced:
                return
            if SHORT_MIN_US <= duration_us < SHORT_MAX_US:
                self._bits.append(0)
            elif LONG_MIN_US <= duration_us < LONG_MAX_US:
                self._bits.append(1)
            else:
                self._reset()
                return
            if len(self._bits) == MESSAGE_BITS:
                self._finish(now_s)
                self._synced = False
            return
        if duration_us > RESET_LOW_US:
            self._finish(now_s)
            self._synced = False

    def _reset(self) -> None:
        self._bits = []
        self._synced = False

    def _finish(self, now_s: float) -> None:
        bits = self._bits
        self._bits = []
        if len(bits) < MESSAGE_BITS:
            return
        # A stray bit at either end shifts the message; try both alignments.
        reading = bits_to_reading(bits[:MESSAGE_BITS]) or bits_to_reading(bits[-MESSAGE_BITS:])
        if reading is None:
            return
        if self._on_frame is not None:
            self._on_frame(reading.raw)
        if reading.raw == self._last_raw and now_s - self._last_time < BURST_WINDOW_S:
            self._last_time = now_s
            return
        self._last_raw = reading.raw
        self._last_time = now_s
        self._on_reading(reading)
