"""Weather sensors through an RTL-SDR dongle (RTL2832U + R820T2) and rtl_433.

At 433.92 MHz (the default) rtl_433 decodes the AcuRite 592TXR tower
(protocol 40) and the ThermoPro TX-2 (protocol 162) far more reliably than
the RXB6, and a streaming dongle deafens a nearby RXB6 anyway, so this is the
preferred receiver when a dongle is plugged in.

At 915 MHz it hears La Crosse sensors: IT+ (TX29-IT, TX35DTH-IT, TX31U-IT)
and the La Crosse View line (LTV-TH, LTV-WR1, LTV-R1/W1, Breeze Pro).

One dongle hears one band at a time. Given several bands, this module takes
turns itself by restarting rtl_433 on each band: rtl_433's own hopping (-H)
stopped decoding after the first retune on the station's R820T dongle, while
a freshly started single-band rtl_433 decodes reliably.

Each round listens on every band in turn, moving on as soon as every sensor
heard on that band last time has reported again (at most hop_seconds, 90 s by
default; the ThermoPro sends every ~50 s, the AcuRite every ~16 s, La Crosse
every ~30 s). Then the dongle rests (rest_seconds, 60 s by default): rtl_433
is stopped, the tuner goes to standby and runs cool, and the receiver lets the
RXB6 listen meanwhile. That keeps a cheap dongle that locks up when hot
working for less of the time.

rtl_433 runs as a child process; its JSON lines become readings for the
receiver service. Install on the Pi with: sudo apt install rtl-433
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, List, Optional, Set, Union

PROTOCOLS_433 = ['40', '162']   # Acurite-Tower, Thermopro-TX2 (not 3: Prologue repeats TX-2 frames)
# LaCrosse TX35DTH-IT, TX29IT, LTV Breeze Pro, LTV-WR1, LTV-TH, LTV-R1/W1, TX31U-IT
PROTOCOLS_915 = ['75', '76', '166', '170', '171', '175', '240']
DEFAULT_HOP_S = 90       # longest listen on one band per round
DEFAULT_REST_S = 60      # dongle off between rounds
RESTART_DELAY_S = 15
# Pause between closing the dongle on one band and opening it on the next, so
# USB and the tuner settle; reopening at once can leave a cheap dongle stalled.
SWITCH_PAUSE_S = 2


@dataclass(frozen=True)
class SensorReading:
    source: str          # 'acurite' | 'thermopro' | 'lacrosse'
    channel: str         # 'A'-'C', '1'-'3', or the La Crosse id
    sensor_id: int
    temp_c: Optional[float]   # None only for a wind-only sensor
    humidity: Optional[int]
    battery_ok: Optional[bool]
    model: str = ''
    wind_avg_kmh: Optional[float] = None
    wind_max_kmh: Optional[float] = None
    wind_dir_deg: Optional[int] = None
    rain_mm: Optional[float] = None   # running total; the receiver turns it into rain today


def _number(value, low: float, high: float) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if low <= value <= high else None


def _wind_kmh(data: dict, key: str) -> Optional[float]:
    """rtl_433 reports wind as *_km_h or *_m_s depending on the decoder."""
    kmh = _number(data.get(key + '_km_h'), 0, 400)
    if kmh is None:
        ms = _number(data.get(key + '_m_s'), 0, 111)
        kmh = ms * 3.6 if ms is not None else None
    return round(kmh, 1) if kmh is not None else None


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
    if not isinstance(sensor_id, int) or not 0 <= sensor_id <= 0xFFFFFFF:
        return None
    wind_avg = _wind_kmh(data, 'wind_avg')
    wind_max = _wind_kmh(data, 'wind_max')
    direction = _number(data.get('wind_dir_deg'), 0, 360)
    rain = _number(data.get('rain_mm'), 0, 1000000)
    if rain is None:
        rain_in = _number(data.get('rain_in'), 0, 40000)
        rain = rain_in * 25.4 if rain_in is not None else None
    has_temp = _number(temp_c, -40.0, 70.0) is not None
    # A La Crosse wind sensor or rain gauge (LTV-R1/R3) has no thermometer but
    # is still worth showing.
    if not has_temp and not (model.startswith('LaCrosse-')
                             and (wind_avg is not None or wind_max is not None or rain is not None)):
        return None
    if model == 'Acurite-Tower':
        source, channel = 'acurite', str(data.get('channel', '')).upper()
        if channel not in ('A', 'B', 'C'):
            return None
    elif model == 'Thermopro-TX2':
        source, channel = 'thermopro', str(data.get('channel', ''))
        if channel not in ('1', '2', '3'):
            return None
    elif model.startswith('LaCrosse-'):
        # Any La Crosse model with a temperature, wind or rain: IT+ and La Crosse
        # View (LTV-TH, Breeze Pro, LTV-R3 rain gauge, ...) alike. No channel
        # switch, so the id names them.
        source, channel = 'lacrosse', str(sensor_id)
    else:
        return None
    battery = data.get('battery_ok')
    return SensorReading(
        source=source,
        channel=channel,
        sensor_id=sensor_id,
        temp_c=round(float(temp_c), 1) if has_temp else None,
        humidity=_humidity(data.get('humidity')),
        battery_ok=bool(battery) if battery is not None else None,
        model=model,
        wind_avg_kmh=wind_avg,
        wind_max_kmh=wind_max,
        wind_dir_deg=int(direction) % 360 if direction is not None else None,
        rain_mm=round(rain, 2) if rain is not None else None,
    )


def band_protocols(frequency: str) -> List[str]:
    try:
        megahertz = float(frequency.rstrip('MmHhZz'))
    except ValueError:
        megahertz = 433.92
    return PROTOCOLS_915 if megahertz >= 800 else PROTOCOLS_433


def available_protocols(binary: str = 'rtl_433') -> Optional[Set[str]]:
    """Protocol numbers this rtl_433 build knows, so an older build is not
    handed a number it rejects. None when it cannot be asked."""
    try:
        result = subprocess.run([binary, '-R', 'help'], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    found = set(re.findall(r'^\s*\[(\d+)\]', result.stdout + result.stderr, re.MULTILINE))
    return {str(int(n)) for n in found} or None


def rtl433_command(frequency: str, known: Optional[Set[str]] = None,
                   extra: Optional[List[str]] = None) -> List[str]:
    """rtl_433 on one band, at its default sample rate, with that band's decoders."""
    # -F log puts rtl_433's own messages (e.g. "Async read stalled") on stdout
    # next to the JSON so they reach the journal.
    command = ['rtl_433', '-f', frequency, '-F', 'json', '-F', 'log']
    for protocol in band_protocols(frequency):
        if known is None or protocol in known:
            command += ['-R', protocol]
    return command + list(extra or [])


def rtl433_commands(frequencies: Union[str, List[str]], known: Optional[Set[str]] = None) -> List[List[str]]:
    """One rtl_433 command per band, for Rtl433Source to take turns with."""
    if isinstance(frequencies, str):
        frequencies = [frequencies]
    frequencies = list(dict.fromkeys(frequencies)) or ['433.92M']
    return [rtl433_command(frequency, known) for frequency in frequencies]


class Rtl433Source:
    """Runs rtl_433 in a thread, a round at a time: each band in turn until its
    sensors have all reported (at most hop_seconds), then rest_seconds with the
    dongle off. A band whose rtl_433 exits on its own is retried.

    on_idle(True) is called whenever the dongle is not listening (resting,
    missing or failing) and on_idle(False) just before it listens again, so
    the receiver can use the RXB6 in between."""

    def __init__(self, commands, on_reading: Callable[[SensorReading], None],
                 log: Callable[[str], None], hop_seconds: int = DEFAULT_HOP_S,
                 rest_seconds: int = 0, on_idle: Optional[Callable[[bool], None]] = None) -> None:
        if commands and isinstance(commands[0], str):
            commands = [commands]
        self._commands: List[List[str]] = [list(c) for c in commands]
        self._on_reading = on_reading
        self._log = log
        self._hop_seconds = max(10, int(hop_seconds))
        self._rest_seconds = max(0, int(rest_seconds))
        self._on_idle = on_idle
        self._idle: Optional[bool] = None
        # Sensors heard on each band in its last two windows: once they have
        # all reported again, that band's window ends early.
        self._recent: List[List[Set[str]]] = [[] for _ in self._commands]
        self._stop = threading.Event()
        self._window_over = threading.Event()
        self._process: Optional[subprocess.Popen] = None
        self._announced: Set[int] = set()
        self._thread = threading.Thread(target=self._run, name='rtl_433', daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._terminate()

    def _terminate(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def _relay(self, message: str) -> None:
        """Pass rtl_433's own messages on, skipping its routine start-up chatter."""
        routine = ('Use "-F log"', 'New defaults active', 'Found ', 'Exact sample rate', 'Allocating',
                   'Detached kernel', 'Reattached kernel', 'rtl_433 version', 'Tuned to', 'Sample rate set',
                   'Bit detection level', 'Tuner gain set', 'Frequency correction', 'Registered', 'Consider',
                   '[SDR] Using device')
        if not any(token in message for token in routine):
            self._log('rtl_433: ' + message[:200])

    def _end_window(self) -> None:
        self._window_over.set()
        self._terminate()

    def _set_idle(self, idle: bool) -> None:
        if idle != self._idle:
            self._idle = idle
            if self._on_idle:
                self._on_idle(idle)

    def _expected(self, band: int) -> Set[str]:
        expected: Set[str] = set()
        for heard in self._recent[band]:
            expected |= heard
        return expected

    def _remember(self, band: int, heard: Set[str]) -> None:
        self._recent[band] = (self._recent[band] + [set(heard)])[-2:]

    def _run(self) -> None:
        index = 0
        count = len(self._commands)
        turns = count > 1 or self._rest_seconds > 0
        while not self._stop.is_set():
            band = index % count
            command = self._commands[band]
            self._window_over.clear()
            self._set_idle(False)
            try:
                self._process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, bufsize=1)
            except FileNotFoundError:
                self._log('rtl_433 is not installed (sudo apt install rtl-433); the RTL-SDR receiver is off')
                self._set_idle(True)
                return
            if band not in self._announced:
                self._announced.add(band)
                plan = ''
                if turns:
                    plan = ' (up to %d s, moving on once its sensors have reported' % self._hop_seconds
                    plan += ('; then the dongle rests %d s)' % self._rest_seconds) if self._rest_seconds else ')'
                self._log('rtl_433 started: ' + ' '.join(command) + plan)
            timer = threading.Timer(self._hop_seconds, self._end_window) if turns else None
            if timer:
                timer.daemon = True
                timer.start()
            expected = self._expected(band)
            heard: Set[str] = set()
            assert self._process.stdout is not None
            for line in self._process.stdout:
                reading = parse_rtl433_line(line)
                if reading is not None:
                    self._on_reading(reading)
                    heard.add(reading.source + '-' + reading.channel)
                    if turns and expected and expected <= heard and not self._window_over.is_set():
                        self._end_window()      # everyone on this band has reported
                elif not line.lstrip().startswith('{') and line.strip():
                    self._relay(line.strip())
                if self._stop.is_set():
                    break
            if timer:
                timer.cancel()
            self._process.stdout.close()
            code = self._process.wait()
            if self._stop.is_set():
                return
            if self._window_over.is_set():
                self._remember(band, heard)
                index += 1          # this band's turn is over; next band
                if index % count == 0 and self._rest_seconds:
                    self._set_idle(True)
                    self._stop.wait(self._rest_seconds)
                elif count > 1:
                    self._stop.wait(SWITCH_PAUSE_S)
                continue
            self._log('rtl_433 exited with code %s (is the dongle plugged in?); retrying in %d s'
                      % (code, RESTART_DELAY_S))
            self._set_idle(True)
            self._stop.wait(RESTART_DELAY_S)
            index += 1
