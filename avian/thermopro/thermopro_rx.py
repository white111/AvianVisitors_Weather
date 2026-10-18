#!/usr/bin/env python3
"""Read ThermoPro TX-2 sensors (TP-60S) from an RXB6 433 MHz receiver on GPIO.

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
from tx2_decode import Reading, Tx2Decoder  # noqa: E402

DEFAULT_OUT = '/var/lib/avian-thermopro/latest.json'
# Ignore edges shorter than this; RXB6 noise is mostly sub-100 us glitches.
GLITCH_US = 120


def parse_labels(items):
    labels = {}
    for item in items or []:
        channel, sep, name = item.partition('=')
        if not sep or channel.strip() not in ('1', '2', '3') or not name.strip():
            raise SystemExit('--label must look like 1=Outside (channel 1-3)')
        labels[int(channel)] = name.strip().replace('_', ' ')[:24]
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


def open_gpio(gpio: int, chip: int):
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
                        help='name a channel, e.g. --label 1=Outside (use _ for spaces)')
    parser.add_argument('--units', choices=('F', 'C'), default='F', help='units shown on the collage')
    parser.add_argument('--out', default=DEFAULT_OUT, help='JSON file for the web badge')
    parser.add_argument('--no-write', action='store_true', help='do not write the JSON file')
    parser.add_argument('--print', dest='echo', action='store_true', help='print each reading')
    parser.add_argument('--raw', action='store_true', help='also print every raw 36-bit frame')
    parser.add_argument('--once', action='store_true', help='exit after the first reading')
    args = parser.parse_args()

    labels = parse_labels(args.label)
    sensors: Dict[int, dict] = {}
    lock = threading.Lock()
    changed = threading.Event()
    stop = threading.Event()

    def on_reading(reading: Reading) -> None:
        entry = {
            'channel': reading.channel,
            'label': labels.get(reading.channel, 'Channel %d' % reading.channel),
            'id': reading.sensor_id,
            'temp_c': reading.temp_c,
            'humidity': reading.humidity,
            'battery_flag': reading.battery_flag,
            'seen': int(time.time()),
        }
        with lock:
            sensors[reading.channel] = entry
        if args.echo:
            temp_f = reading.temp_c * 9 / 5 + 32
            hum = '--' if reading.humidity is None else '%d%%' % reading.humidity
            print('%s  ch%d %-10s id=%3d  %5.1f C  %5.1f F  %s' % (
                time.strftime('%H:%M:%S'), reading.channel, entry['label'],
                reading.sensor_id, reading.temp_c, temp_f, hum), flush=True)
        changed.set()
        if args.once:
            stop.set()

    def on_frame(raw: str) -> None:
        if args.raw:
            print('frame %s' % raw, flush=True)

    decoder = Tx2Decoder(on_reading, on_frame if args.raw else None)
    lgpio, handle = open_gpio(args.gpio, args.chip)
    last = {'tick': None}

    def on_edge(_chip, _gpio, level, tick_ns):
        if level not in (0, 1):  # 2 = watchdog timeout
            return
        if last['tick'] is not None:
            # The time since the previous edge belongs to the previous level.
            decoder.feed(1 - level, (tick_ns - last['tick']) / 1000.0, tick_ns / 1e9)
        last['tick'] = tick_ns

    callback = lgpio.callback(handle, args.gpio, lgpio.BOTH_EDGES, on_edge)

    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if args.echo:
        print('Listening on GPIO%d for ThermoPro TX-2 sensors (they send every ~50 s)...' % args.gpio,
              flush=True)

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
        callback.cancel()
        lgpio.gpiochip_close(handle)
    return 0


if __name__ == '__main__':
    sys.exit(main())
