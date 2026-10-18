"""La Crosse IT+ sensors through an RTL-SDR dongle (RTL2832U + R820T2) and rtl_433.

The TX29U / TX29-IT (temperature) and TX35DTH-IT (temperature + humidity)
send 915 MHz FSK about every 4 s, which the 433 MHz RXB6 cannot hear.
rtl_433 decodes them (protocols 76 and 75); this module runs it, reads its
JSON lines and hands each reading to the receiver service.

Install on the Pi with: sudo apt install rtl-433
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

RTL433_PROTOCOLS = ['75', '76']
RESTART_DELAY_S = 15


@dataclass(frozen=True)
class LaCrosseReading:
    sensor_id: int
    model: str
    temp_c: float
    humidity: Optional[int]
    battery_ok: Optional[bool]
    new_battery: bool


def parse_rtl433_line(line: str) -> Optional[LaCrosseReading]:
    """Turn one rtl_433 JSON line into a reading, or None for anything else."""
    try:
        data = json.loads(line)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    model = str(data.get('model', ''))
    if not model.startswith(('LaCrosse-TX29', 'LaCrosse-TX35')):
        return None
    sensor_id = data.get('id')
    temp_c = data.get('temperature_C')
    if not isinstance(sensor_id, int) or not 0 <= sensor_id <= 999:
        return None
    if not isinstance(temp_c, (int, float)) or not -40.0 <= temp_c <= 70.0:
        return None
    humidity = data.get('humidity')
    if not isinstance(humidity, (int, float)) or not 0 <= humidity <= 100:
        humidity = None  # TX29 has no hygrometer; rtl_433 may omit it or send 106
    battery = data.get('battery_ok')
    return LaCrosseReading(
        sensor_id=sensor_id,
        model=model,
        temp_c=round(float(temp_c), 1),
        humidity=int(humidity) if humidity is not None else None,
        battery_ok=bool(battery) if battery is not None else None,
        new_battery=bool(data.get('newbattery')),
    )


def rtl433_command(frequency: str, extra: Optional[List[str]] = None) -> List[str]:
    command = ['rtl_433', '-f', frequency, '-F', 'json']
    for protocol in RTL433_PROTOCOLS:
        command += ['-R', protocol]
    return command + list(extra or [])


class Rtl433Source:
    """Runs rtl_433 in a thread, restarting it if it exits."""

    def __init__(self, command: List[str], on_reading: Callable[[LaCrosseReading], None],
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
                self._log('rtl_433 is not installed (sudo apt install rtl-433); La Crosse sensors are off')
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
