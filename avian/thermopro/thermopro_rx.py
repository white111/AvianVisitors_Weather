#!/usr/bin/env python3
"""Read weather sensors for the collage badge.

ThermoPro TX-2 (TP-60S base, channels 1-3) and AcuRite 592TXR towers
(channels A-C) on 433 MHz, from either:
  - an RTL-SDR dongle (RTL2832U + R820T2) running rtl_433 (--rtl433, preferred:
    far more sensitive; use --no-gpio with it, a streaming dongle deafens an
    RXB6 nearby), or
  - an RXB6 receiver on GPIO (the default without a dongle).
Add --rtl433-freq 915M (with 433.92M) to also hear La Crosse sensors at 915 MHz;
the dongle then takes turns between the bands.

Wiring (Raspberry Pi header):
    RXB6 VCC  -> pin 1 (3.3 V)   keep it on 3.3 V: a 5 V supply puts 5 V on DATA
    RXB6 GND  -> pin 6 (GND)
    RXB6 DATA -> pin 13 (GPIO27) or whatever --gpio says
    RXB6 ANT  -> 17.3 cm straight wire

Run by hand to see readings:
    python3 thermopro_rx.py --print
Run as the avian-thermopro service to feed the collage weather badge; the
latest readings are written to --out as JSON, read by avian/api/thermopro.php.

Needs the lgpio library (Raspberry Pi OS: sudo apt install python3-lgpio).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import tempfile
import threading
import time
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from acurite_decode import AcuriteReading, AcuriteTowerDecoder  # noqa: E402
from rtl433_source import DEFAULT_HOP_S, Rtl433Source, SensorReading, available_protocols, rtl433_commands  # noqa: E402
from tx2_decode import Reading, Tx2Decoder  # noqa: E402

DEFAULT_OUT = '/var/lib/avian-thermopro/latest.json'
# Ignore edges shorter than this; RXB6 noise is mostly sub-100 us glitches.
GLITCH_US = 100


def parse_labels(items):
    labels = {}
    for item in items or []:
        channel, sep, name = item.partition('=')
        channel = channel.strip().upper()
        if not sep or channel not in ('1', '2', '3', 'A', 'B', 'C') or not name.strip():
            raise SystemExit('--label must look like 1=Outside (ThermoPro 1-3) or A=Porch (AcuRite A-C)')
        labels[channel] = name.strip().replace('_', ' ')[:24]
    return labels


def write_json_atomic(path: str, payload: dict) -> None:
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.latest-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(payload, handle, separators=(',', ':'))
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def lgpio_workdir(out_path: str) -> str:
    """Pick a writable folder for lgpio's notification pipe.

    lgpio creates .lgd-nfy* pipes in LG_WD or the current directory; under
    systemd that is / and the import fails. Prefer LG_WD, then the output
    folder (the service's StateDirectory), then the temp folder.
    """
    candidates = [os.environ.get('LG_WD'), os.path.dirname(os.path.abspath(out_path)),
                  tempfile.gettempdir()]
    for path in candidates:
        if path and os.path.isdir(path) and os.access(path, os.W_OK | os.X_OK):
            return path
    raise SystemExit('No writable folder for lgpio (set LG_WD)')


def open_gpio(gpio: int, chip: int, workdir: str):
    os.environ['LG_WD'] = workdir
    os.chdir(workdir)
    import lgpio  # imported here so --help works without it

    chips = [chip] if chip >= 0 else [0, 4]
    last_error = None
    for number in chips:
        try:
            handle = lgpio.gpiochip_open(number)
        except lgpio.error as error:
            last_error = error
            continue
        try:
            lgpio.gpio_claim_alert(handle, gpio, lgpio.BOTH_EDGES)
            lgpio.gpio_set_debounce_micros(handle, gpio, GLITCH_US)
            return lgpio, handle
        except lgpio.error as error:
            last_error = error
            lgpio.gpiochip_close(handle)
    raise SystemExit('Could not claim GPIO%d: %s' % (gpio, last_error))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--gpio', type=int, default=27, help='BCM GPIO for RXB6 DATA (default 27)')
    parser.add_argument('--chip', type=int, default=-1, help='gpiochip number (default: try 0, then 4)')
    parser.add_argument('--label', action='append', metavar='CH=NAME',
                        help='name a channel: ThermoPro 1-3 or AcuRite A-C, e.g. --label 1=Outside'
                             ' --label A=Porch (use _ for spaces)')
    parser.add_argument('--units', choices=('F', 'C'), default='F', help='units shown on the collage')
    parser.add_argument('--out', default=DEFAULT_OUT, help='JSON file for the web badge')
    parser.add_argument('--no-write', action='store_true', help='do not write the JSON file')
    parser.add_argument('--print', dest='echo', action='store_true', help='print each reading')
    parser.add_argument('--raw', action='store_true', help='also print every raw frame')
    parser.add_argument('--once', action='store_true', help='exit after the first reading')
    parser.add_argument('--no-gpio', action='store_true', help='do not use the RXB6 (RTL-SDR only)')
    parser.add_argument('--rtl433', action='store_true',
                        help='run rtl_433 on an RTL-SDR dongle (preferred receiver; pair with --no-gpio)')
    parser.add_argument('--rtl433-freq', action='append', metavar='FREQ',
                        help='band(s) for the dongle, repeatable: 433.92M (default) for AcuRite + ThermoPro,'
                             ' 915M for La Crosse; two bands hop')
    parser.add_argument('--rtl433-hop', type=int, default=DEFAULT_HOP_S,
                        help='seconds on each band when hopping (default %d)' % DEFAULT_HOP_S)
    args = parser.parse_args()

    labels = parse_labels(args.label)
    sensors: Dict[str, dict] = {}
    last_printed: Dict[str, tuple] = {}
    lock = threading.Lock()
    changed = threading.Event()
    stop = threading.Event()

    def record(source: str, channel: str, sensor_id: int, temp_c, humidity, extra: dict) -> None:
        defaults = {'thermopro': 'Channel ', 'acurite': 'AcuRite ', 'lacrosse': 'La Crosse '}
        entry = {
            'source': source,
            'channel': channel,
            'label': labels.get(channel, defaults[source] + channel) if source != 'lacrosse'
            else defaults[source] + channel,
            'id': sensor_id,
            'temp_c': temp_c,
            'humidity': humidity,
            'seen': int(time.time()),
        }
        entry.update(extra)
        key = source + '-' + channel
        with lock:
            sensors[key] = entry
        if args.echo:
            # La Crosse sensors send every few seconds; print changes or once a minute.
            now = time.time()
            previous = last_printed.get(key)
            wind = extra.get('wind_avg_kmh')
            if previous is None or previous[1:] != (temp_c, humidity, wind) or now - previous[0] >= 60:
                last_printed[key] = (now, temp_c, humidity, wind)
                hum = '--' if humidity is None else '%d%%' % humidity
                temps = ('%5.1f C  %5.1f F' % (temp_c, temp_c * 9 / 5 + 32)) if temp_c is not None else '   -- C     -- F'
                wind_text = ''
                if wind is not None:
                    wind_text = '  wind %.1f km/h' % wind
                    if extra.get('wind_dir_deg') is not None:
                        wind_text += ' from %d deg' % extra['wind_dir_deg']
                print('%s  %-9s ch%s %-10s id=%5d  %s  %s%s' % (
                    time.strftime('%H:%M:%S'), source, channel, entry['label'], sensor_id,
                    temps, hum, wind_text), flush=True)
        changed.set()
        if args.once:
            stop.set()

    def on_reading(reading: Reading) -> None:
        record('thermopro', str(reading.channel), reading.sensor_id, reading.temp_c, reading.humidity,
               {'battery_flag': reading.battery_flag})

    def on_acurite(reading: AcuriteReading) -> None:
        record('acurite', reading.channel, reading.sensor_id, reading.temp_c, reading.humidity,
               {'battery_ok': reading.battery_ok})

    def on_sdr(reading: SensorReading) -> None:
        extra = {'receiver': 'rtl_433', 'model': reading.model}
        if reading.battery_ok is not None and reading.source != 'thermopro':
            extra['battery_ok'] = reading.battery_ok
        for field in ('wind_avg_kmh', 'wind_max_kmh', 'wind_dir_deg'):
            if getattr(reading, field) is not None:
                extra[field] = getattr(reading, field)
        record(reading.source, reading.channel, reading.sensor_id, reading.temp_c, reading.humidity, extra)

    def on_frame(raw: str) -> None:
        print('frame %s' % raw, flush=True)

    decoders = [
        Tx2Decoder(on_reading, on_frame if args.raw else None),
        AcuriteTowerDecoder(on_acurite, on_frame if args.raw else None),
    ]
    if args.no_gpio and not args.rtl433:
        raise SystemExit('--no-gpio needs --rtl433, otherwise there is nothing to listen to')
    lgpio = handle = None
    if not args.no_gpio:
        lgpio, handle = open_gpio(args.gpio, args.chip, lgpio_workdir(args.out))
    last = {'tick': None}

    def on_edge(_chip, _gpio, level, tick_ns):
        if level not in (0, 1):  # 2 = watchdog timeout
            return
        if last['tick'] is not None:
            # The time since the previous edge belongs to the previous level.
            duration_us = (tick_ns - last['tick']) / 1000.0
            for decoder in decoders:
                decoder.feed(1 - level, duration_us, tick_ns / 1e9)
        last['tick'] = tick_ns

    callback = lgpio.callback(handle, args.gpio, lgpio.BOTH_EDGES, on_edge) if lgpio else None
    sdr = None
    if args.rtl433:
        bands = args.rtl433_freq or ['433.92M']
        sdr = Rtl433Source(rtl433_commands(bands, available_protocols()), on_sdr,
                           lambda message: print(message, file=sys.stderr, flush=True), args.rtl433_hop)
        sdr.start()

    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if args.echo:
        if lgpio:
            print('Listening on GPIO%d for ThermoPro TX-2 (~50 s) and AcuRite 592TXR (~16 s) sensors...'
                  % args.gpio, flush=True)
        if sdr:
            print('Listening with the RTL-SDR at %s%s...' % (
                ' and '.join(bands), ' (taking turns, %d s each)' % args.rtl433_hop if len(bands) > 1 else ''), flush=True)

    try:
        while not stop.is_set():
            if changed.wait(1.0):
                changed.clear()
                if not args.no_write:
                    with lock:
                        payload = {
                            'updated': int(time.time()),
                            'units': args.units,
                            'sensors': [sensors[k] for k in sorted(sensors)],
                        }
                    try:
                        write_json_atomic(args.out, payload)
                    except OSError as error:
                        print('Could not write %s: %s' % (args.out, error), file=sys.stderr, flush=True)
    finally:
        if sdr:
            sdr.stop()
        if callback:
            callback.cancel()
        if lgpio:
            lgpio.gpiochip_close(handle)
    return 0


if __name__ == '__main__':
    sys.exit(main())
