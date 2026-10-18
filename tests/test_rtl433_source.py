"""Tests for the RTL-SDR (rtl_433) sensor source."""

import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'avian', 'thermopro'))

from rtl433_source import Rtl433Source, parse_rtl433_line, rtl433_command  # noqa: E402

# Shapes as printed by rtl_433 25.02 on the station.
ACURITE = {'time': '2026-10-18 16:10:01', 'model': 'Acurite-Tower', 'id': 666, 'channel': 'A',
           'battery_ok': 1, 'temperature_C': 24.7, 'humidity': 51, 'mic': 'CHECKSUM'}
THERMOPRO = {'time': '2026-10-18 16:10:30', 'model': 'Thermopro-TX2', 'subtype': 9, 'id': 229,
             'channel': 1, 'battery_ok': 0, 'temperature_C': 26.6, 'humidity': 12, 'button': 0}
PROLOGUE = dict(THERMOPRO, model='Prologue-TH', battery_ok=1)
TX29 = {'model': 'LaCrosse-TX29IT', 'id': 42, 'battery_ok': 1, 'newbattery': 0, 'temperature_C': 16.2}
TX35 = {'model': 'LaCrosse-TX35DTHIT', 'id': 7, 'battery_ok': 0, 'temperature_C': -3.45, 'humidity': 81}


class ParseTest(unittest.TestCase):
    def test_acurite_tower(self):
        r = parse_rtl433_line(json.dumps(ACURITE))
        self.assertEqual((r.source, r.channel, r.sensor_id, r.temp_c, r.humidity, r.battery_ok),
                         ('acurite', 'A', 666, 24.7, 51, True))

    def test_thermopro_tx2(self):
        r = parse_rtl433_line(json.dumps(THERMOPRO))
        self.assertEqual((r.source, r.channel, r.sensor_id, r.temp_c, r.humidity),
                         ('thermopro', '1', 229, 26.6, 12))

    def test_prologue_duplicate_is_ignored(self):
        self.assertIsNone(parse_rtl433_line(json.dumps(PROLOGUE)))

    def test_lacrosse(self):
        r = parse_rtl433_line(json.dumps(TX29))
        self.assertEqual((r.source, r.channel, r.temp_c, r.humidity), ('lacrosse', '42', 16.2, None))
        r = parse_rtl433_line(json.dumps(TX35))
        self.assertEqual((r.channel, r.temp_c, r.humidity, r.battery_ok), ('7', -3.5, 81, False))
        self.assertIsNone(parse_rtl433_line(json.dumps(dict(TX29, humidity=106))).humidity)

    def test_ignores_other_lines(self):
        for line in ('', 'not json', '[]',
                     json.dumps(dict(ACURITE, channel='D')),
                     json.dumps(dict(THERMOPRO, channel=4)),
                     json.dumps(dict(ACURITE, temperature_C=150)),
                     json.dumps(dict(ACURITE, id='x')),
                     json.dumps({'model': 'Some-Meter', 'id': 1, 'temperature_C': 20})):
            self.assertIsNone(parse_rtl433_line(line), line)

    def test_command_picks_decoders_by_band(self):
        self.assertEqual(rtl433_command('433.92M'), ['rtl_433', '-f', '433.92M', '-F', 'json', '-R', '40', '-R', '162'])
        self.assertEqual(rtl433_command('915M')[-4:], ['-R', '75', '-R', '76'])


class SourceTest(unittest.TestCase):
    def test_reads_fake_rtl433_and_reports_missing_binary(self):
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fake:
            fake.write('import json\nprint("rtl_433 banner")\n')
            for frame in (ACURITE, PROLOGUE, THERMOPRO):
                fake.write('print(json.dumps(%r))\n' % frame)
        try:
            got, logs, done = [], [], threading.Event()

            def on_reading(reading):
                got.append((reading.source, reading.channel))
                if len(got) == 2:
                    done.set()

            source = Rtl433Source([sys.executable, fake.name], on_reading, logs.append)
            source.start()
            self.assertTrue(done.wait(10))
            source.stop()
            self.assertEqual(got, [('acurite', 'A'), ('thermopro', '1')])
        finally:
            os.unlink(fake.name)

        logs = []
        missing = Rtl433Source(['/nonexistent/rtl_433'], lambda r: None, logs.append)
        missing.start()
        missing._thread.join(5)
        self.assertIn('not installed', logs[-1])


if __name__ == '__main__':
    unittest.main()
