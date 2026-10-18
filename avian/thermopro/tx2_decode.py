"""Decoder for ThermoPro TX-2 remote sensors (TP-60S / TP-62 / TP-65 bases).

The TX-2 sends the "Prologue" style 433.92 MHz OOK signal every ~50 s: a
burst of about seven identical 36-bit frames. Each bit is a short carrier
pulse (~500 us) followed by a gap whose length is the bit value:

    gap ~2000 us -> 0
    gap ~4000 us -> 1
    gap ~9000 us -> end of frame (sync)

Frame layout (MSB first), as decoded by rtl_433's prologue decoder:

    TTTT IIIIIIII BXCC SSSSSSSSSSSS HHHHHHHH
    T  4 bits  type nibble
    I  8 bits  sensor id (changes when the batteries are replaced)
    B  1 bit   battery flag
    X  1 bit   TX button (forced transmission)
    C  2 bits  channel switch, 0-2 -> channel 1-3
    S 12 bits  temperature, signed, 0.1 degC
    H  8 bits  relative humidity in %, 0xCC (204) when the sensor has none

This module has no hardware dependency so it can be tested anywhere. Feed it
(level, duration_us) pairs: level is the line state *during* the duration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

FRAME_BITS = 36

PULSE_MIN_US = 250
PULSE_MAX_US = 1100
ZERO_MIN_US = 1400
ZERO_MAX_US = 2800
ONE_MIN_US = 3200
ONE_MAX_US = 5000
SYNC_MIN_US = 7000
SYNC_MAX_US = 14000

# A burst repeats the same frame; requiring a repeat filters RF noise that
# happens to form 36 plausible bits.
CONFIRM_REPEATS = 2
BURST_WINDOW_S = 3.0


@dataclass(frozen=True)
class Reading:
    sensor_id: int
    channel: int
    temp_c: float
    humidity: Optional[int]
    battery_flag: bool
    button: bool
    type_nibble: int
    raw: str


def bits_to_reading(bits: List[int]) -> Optional[Reading]:
    """Turn 36 bits into a Reading, or None when the values are implausible."""
    if len(bits) < FRAME_BITS:
        return None
    value = 0
    for bit in bits[:FRAME_BITS]:
        value = (value << 1) | (bit & 1)

    type_nibble = (value >> 32) & 0xF
    sensor_id = (value >> 24) & 0xFF
    battery_flag = bool((value >> 23) & 1)
    button = bool((value >> 22) & 1)
    channel = ((value >> 20) & 0x3) + 1
    temp_raw = (value >> 8) & 0xFFF
    if temp_raw & 0x800:
        temp_raw -= 0x1000
    humidity_raw = value & 0xFF

    temp_c = temp_raw / 10.0
    if channel > 3 or not -40.0 <= temp_c <= 70.0:
        return None
    if humidity_raw == 0xCC:
        humidity = None
    elif humidity_raw <= 100:
        humidity = humidity_raw
    else:
        return None

    return Reading(
        sensor_id=sensor_id,
        channel=channel,
        temp_c=temp_c,
        humidity=humidity,
        battery_flag=battery_flag,
        button=button,
        type_nibble=type_nibble,
        raw='%09x' % value,
    )


class Tx2Decoder:
    """Streaming pulse-position decoder with repeat confirmation."""

    def __init__(self, on_reading: Callable[[Reading], None],
                 on_frame: Optional[Callable[[str], None]] = None) -> None:
        self._on_reading = on_reading
        self._on_frame = on_frame
        self._bits: List[int] = []
        self._pulse_ok = False
        self._last_raw = ''
        self._repeat = 0
        self._last_frame_time = -1e9
        self._reported_raw = ''

    def reset(self) -> None:
        self._bits = []
        self._pulse_ok = False

    def feed(self, level: int, duration_us: float, now_s: float) -> None:
        """Consume one line state and how long it lasted."""
        if level:
            self._pulse_ok = PULSE_MIN_US <= duration_us <= PULSE_MAX_US
            if not self._pulse_ok:
                self._bits = []
            return

        if not self._pulse_ok:
            self._bits = []
            return
        self._pulse_ok = False

        if ZERO_MIN_US <= duration_us <= ZERO_MAX_US:
            self._bits.append(0)
        elif ONE_MIN_US <= duration_us <= ONE_MAX_US:
            self._bits.append(1)
        elif duration_us >= SYNC_MIN_US:
            # The gap after the last pulse ends the frame.
            if len(self._bits) in (FRAME_BITS, FRAME_BITS + 1):
                self._frame(self._bits[:FRAME_BITS], now_s)
            self._bits = []
            return
        else:
            self._bits = []
            return

        if len(self._bits) > FRAME_BITS + 1:
            self._bits = []

    def _frame(self, bits: List[int], now_s: float) -> None:
        raw = ''.join(str(b) for b in bits)
        if self._on_frame is not None:
            self._on_frame(raw)
        if now_s - self._last_frame_time > BURST_WINDOW_S:
            self._repeat = 0
            self._reported_raw = ''
        self._last_frame_time = now_s
        if raw == self._last_raw:
            self._repeat += 1
        else:
            self._last_raw = raw
            self._repeat = 1
        if self._repeat >= CONFIRM_REPEATS and raw != self._reported_raw:
            reading = bits_to_reading(bits)
            if reading is not None:
                self._reported_raw = raw
                self._on_reading(reading)
