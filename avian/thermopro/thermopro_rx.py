#!/usr/bin/env python3
"""Read 433 MHz weather sensors from an RXB6 receiver on GPIO.

Supported: ThermoPro TX-2 (TP-60S base, channels 1-3) and AcuRite 592TXR
tower sensors (channels A-C). Both are decoded from the same radio.

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
    args = parser.parse_args()

    labels = parse_labels(args.label)
    sensors: Dict[str, dict] = {}
    lock = threading.Lock()
    changed = threading.Event()
    stop = threading.Event()

    def record(source: str, channel: str, sensor_id: int, temp_c: float, humidity, extra: dict) -> None:
        entry = {
            'source': source,
            'channel': channel,
            'label': labels.get(channel, ('Channel ' if source == 'thermopro' else 'AcuRite ') + channel),
            'id': sensor_id,
            'temp_c': temp_c,
            'humidity': humidity,
            'seen': int(time.time()),
        }
        entry.update(extra)
        with lock:
            sensors[channel] = entry
        if args.echo:
            hum = '--' if humidity is None else '%d%%' % humidity
            print('%s  %-9s ch%s %-10s id=%5d  %5.1f C  %5.1f F  %s' % (
                time.strftime('%H:%M:%S'), source, channel, entry['label'], sensor_id,
                temp_c, temp_c * 9 / 5 + 32, hum), flush=True)
        changed.set()
        if args.once:
            stop.set()

    def on_reading(reading: Reading) -> None:
        record('thermopro', str(reading.channel), reading.sensor_id, reading.temp_c, reading.humidity,
               {'battery_flag': reading.battery_flag})

    def on_acurite(reading: AcuriteReading) -> None:
        record('acurite', reading.channel, reading.sensor_id, reading.temp_c, reading.humidity,
               {'battery_ok': reading.battery_ok})

    def on_frame(raw: str) -> None:
        print('frame %s' % raw, flush=True)

    decoders = [
        Tx2Decoder(on_reading, on_frame if args.raw else None),
        AcuriteTowerDecoder(on_acurite, on_frame if args.raw else None),
    ]
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

    callback = lgpio.callback(handle, args.gpio, lgpio.BOTH_EDGES, on_edge)

    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if args.echo:
        print('Listening on GPIO%d for ThermoPro TX-2 (~50 s) and AcuRite 592TXR (~16 s) sensors...' % args.gpio,
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
