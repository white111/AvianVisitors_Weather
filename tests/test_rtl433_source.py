"""Tests for the La Crosse IT+ (RTL-SDR + rtl_433) sensor source."""

import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'avian', 'thermopro'))

from rtl433_source import Rtl433Source, parse_rtl433_line, rtl433_command  # noqa: E402

TX29 = {'time': '2026-10-18 14:10:00', 'model': 'LaCrosse-TX29IT', 'id': 42, 'battery_ok': 1,
        'newbattery': 0, 'temperature_C': 16.2, 'mic': 'CRC'}
TX35 = {'time': '2026-10-18 14:10:02', 'model': 'LaCrosse-TX35DTHIT', 'id': 7, 'battery_ok': 0,
        'newbattery': 1, 'temperature_C': -3.45, 'humidity': 81, 'mic': 'CRC'}


class ParseTest(unittest.TestCase):
    def test_tx29(self):
        r = parse_rtl433_line(json.dumps(TX29))
        self.assertEqual((r.sensor_id, r.temp_c, r.humidity, r.battery_ok, r.new_battery),
                         (42, 16.2, None, True, False))

    def test_tx35_with_humidity(self):
        r = parse_rtl433_line(json.dumps(TX35))
        self.assertEqual((r.sensor_id, r.temp_c, r.humidity, r.battery_ok, r.new_battery),
                         (7, -3.5, 81, False, True))

    def test_tx29_no_hygrometer_marker(self):
        self.assertIsNone(parse_rtl433_line(json.dumps(dict(TX29, humidity=106))).humidity)

    def test_ignores_other_lines(self):
        for line in ('', 'not json', '[]', json.dumps({'model': 'Acurite-Tower', 'id': 1, 'temperature_C': 20}),
                     json.dumps(dict(TX29, temperature_C=150)), json.dumps(dict(TX29, id='x'))):
            self.assertIsNone(parse_rtl433_line(line), line)

    def test_command(self):
        cmd = rtl433_command('915M')
        self.assertEqual(cmd[:7], ['rtl_433', '-f', '915M', '-s', '250k', '-F', 'json'])
        self.assertIn('76', cmd)
        self.assertIn('75', cmd)


class SourceTest(unittest.TestCase):
    def test_reads_fake_rtl433_and_reports_missing_binary(self):
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fake:
            fake.write('import json\nprint("rtl_433 banner")\n')
            fake.write('print(json.dumps(%r))\nprint(json.dumps(%r))\n' % (TX29, TX35))
        try:
            got, logs, done = [], [], threading.Event()

            def on_reading(reading):
                got.append(reading.sensor_id)
                if len(got) == 2:
                    done.set()

            source = Rtl433Source([sys.executable, fake.name], on_reading, logs.append)
            source.start()
            self.assertTrue(done.wait(10))
            source.stop()
            self.assertEqual(got, [42, 7])
        finally:
            os.unlink(fake.name)

        logs = []
        missing = Rtl433Source(['/nonexistent/rtl_433'], lambda r: None, logs.append)
        missing.start()
        missing._thread.join(5)
        self.assertIn('not installed', logs[-1])


if __name__ == '__main__':
    unittest.main()
