"""Weather sensors through an RTL-SDR dongle (RTL2832U + R820T2) and rtl_433.

At 433.92 MHz (the default) rtl_433 decodes the AcuRite 592TXR tower
(protocol 40) and the ThermoPro TX-2 (protocol 162) far more reliably than
the RXB6, and a streaming dongle deafens a nearby RXB6 anyway, so this is the
preferred receiver when a dongle is plugged in.

At 915 MHz it listens for La Crosse IT+ TX29-IT / TX35DTH-IT (protocols 76
and 75) instead; one dongle hears one band at a time.

rtl_433 runs as a child process; its JSON lines become readings for the
receiver service. Install on the Pi with: sudo apt install rtl-433
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional

PROTOCOLS_433 = ['40', '162']   # Acurite-Tower, Thermopro-TX2 (not 3: Prologue repeats TX-2 frames)
PROTOCOLS_915 = ['75', '76']    # LaCrosse TX35DTH-IT, TX29IT
RESTART_DELAY_S = 15


@dataclass(frozen=True)
class SensorReading:
    source: str          # 'acurite' | 'thermopro' | 'lacrosse'
    channel: str         # 'A'-'C', '1'-'3', or the La Crosse id
    sensor_id: int
    temp_c: float
    humidity: Optional[int]
    battery_ok: Optional[bool]


def _humidity(value) -> Optional[int]:
    if isinstance(value, (int, float)) and 0 <= value <= 100:
        return int(value)
    return None  # absent, or a "no hygrometer" marker such as TX29's 106


def parse_rtl433_line(line: str) -> Optional[SensorReading]:
    """Turn one rtl_433 JSON line into a reading, or None for anything else."""
    try:
        data = json.loads(line)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    model = str(data.get('model', ''))
    sensor_id = data.get('id')
    temp_c = data.get('temperature_C')
    if not isinstance(sensor_id, int) or not 0 <= sensor_id <= 0xFFFF:
        return None
    if not isinstance(temp_c, (int, float)) or not -40.0 <= temp_c <= 70.0:
        return None
    if model == 'Acurite-Tower':
        source, channel = 'acurite', str(data.get('channel', '')).upper()
        if channel not in ('A', 'B', 'C'):
            return None
    elif model == 'Thermopro-TX2':
        source, channel = 'thermopro', str(data.get('channel', ''))
        if channel not in ('1', '2', '3'):
            return None
    elif model.startswith(('LaCrosse-TX29', 'LaCrosse-TX35')):
        if sensor_id > 999:
            return None
        source, channel = 'lacrosse', str(sensor_id)
    else:
        return None
    battery = data.get('battery_ok')
    return SensorReading(
        source=source,
        channel=channel,
        sensor_id=sensor_id,
        temp_c=round(float(temp_c), 1),
        humidity=_humidity(data.get('humidity')),
        battery_ok=bool(battery) if battery is not None else None,
    )


def rtl433_command(frequency: str, extra: Optional[List[str]] = None) -> List[str]:
    """rtl_433 at its default sample rate, with the decoders for that band."""
    try:
        megahertz = float(frequency.rstrip('MmHhZz'))
    except ValueError:
        megahertz = 433.92
    protocols = PROTOCOLS_915 if megahertz >= 800 else PROTOCOLS_433
    command = ['rtl_433', '-f', frequency, '-F', 'json']
    for protocol in protocols:
        command += ['-R', protocol]
    return command + list(extra or [])


class Rtl433Source:
    """Runs rtl_433 in a thread, restarting it if it exits."""

    def __init__(self, command: List[str], on_reading: Callable[[SensorReading], None],
                 log: Callable[[str], None]) -> None:
        self._command = command
        self._on_reading = on_reading
        self._log = log
        self._stop = threading.Event()
        self._process: Optional[subprocess.Popen] = None
        self._thread = threading.Thread(target=self._run, name='rtl_433', daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._process = subprocess.Popen(self._command, stdout=subprocess.PIPE, text=True, bufsize=1)
            except FileNotFoundError:
                self._log('rtl_433 is not installed (sudo apt install rtl-433); the RTL-SDR receiver is off')
                return
            self._log('rtl_433 started: ' + ' '.join(self._command))
            assert self._process.stdout is not None
            for line in self._process.stdout:
                reading = parse_rtl433_line(line)
                if reading is not None:
                    self._on_reading(reading)
                if self._stop.is_set():
                    break
            self._process.stdout.close()
            code = self._process.wait()
            if self._stop.is_set():
                return
            self._log('rtl_433 exited with code %s (is the dongle plugged in?); retrying in %d s'
                      % (code, RESTART_DELAY_S))
            self._stop.wait(RESTART_DELAY_S)
