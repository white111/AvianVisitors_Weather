"""Tests for the RTL-SDR (rtl_433) sensor source."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'avian', 'thermopro'))

from rtl433_source import (Rtl433Source, available_protocols, parse_rtl433_line, rtl433_command,  # noqa: E402
                           rtl433_commands)

# Shapes as printed by rtl_433 25.02 on the station.
ACURITE = {'time': '2026-10-18 16:10:01', 'model': 'Acurite-Tower', 'id': 666, 'channel': 'A',
           'battery_ok': 1, 'temperature_C': 24.7, 'humidity': 51, 'mic': 'CHECKSUM'}
THERMOPRO = {'time': '2026-10-18 16:10:30', 'model': 'Thermopro-TX2', 'subtype': 9, 'id': 229,
             'channel': 1, 'battery_ok': 0, 'temperature_C': 26.6, 'humidity': 12, 'button': 0}
PROLOGUE = dict(THERMOPRO, model='Prologue-TH', battery_ok=1)
TX29 = {'model': 'LaCrosse-TX29IT', 'id': 42, 'battery_ok': 1, 'newbattery': 0, 'temperature_C': 16.2}
TX35 = {'model': 'LaCrosse-TX35DTHIT', 'id': 7, 'battery_ok': 0, 'temperature_C': -3.45, 'humidity': 81}
LTV_TH = {'model': 'LaCrosse-TH3', 'id': 0x2D9C14, 'seq': 1, 'battery_ok': 1, 'temperature_C': 19.4, 'humidity': 58}
LTV_WIND = {'model': 'LaCrosse-BreezePro', 'id': 0x89401A, 'seq': 3, 'flags': 0, 'temperature_C': 24.5,
            'humidity': 44, 'wind_avg_km_h': 9.7, 'wind_dir_deg': 315, 'mic': 'CRC'}
WIND_ONLY = {'model': 'LaCrosse-WindSensor', 'id': 0x11, 'wind_avg_m_s': 2.5, 'wind_max_m_s': 4.0}
LTV_R3 = {'model': 'LaCrosse-R3', 'id': 0x3A0B2C, 'battery_ok': 1, 'seq': 5, 'rain_mm': 128.27, 'rain2_mm': 0.0,
          'mic': 'CRC'}


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

    def test_lacrosse_view_sensor_by_id(self):
        r = parse_rtl433_line(json.dumps(LTV_TH))
        self.assertEqual((r.source, r.channel, r.temp_c, r.humidity), ('lacrosse', str(0x2D9C14), 19.4, 58))

    def test_breeze_pro_wind_temperature_humidity(self):
        r = parse_rtl433_line(json.dumps(LTV_WIND))
        self.assertEqual((r.source, r.channel, r.model, r.temp_c, r.humidity, r.wind_avg_kmh, r.wind_dir_deg),
                         ('lacrosse', '8994842', 'LaCrosse-BreezePro', 24.5, 44, 9.7, 315))

    def test_ltv_r3_rain_gauge(self):
        r = parse_rtl433_line(json.dumps(LTV_R3))
        self.assertEqual((r.source, r.channel, r.model, r.temp_c, r.rain_mm, r.battery_ok),
                         ('lacrosse', str(0x3A0B2C), 'LaCrosse-R3', None, 128.27, True))

    def test_wind_only_sensor_in_m_s(self):
        r = parse_rtl433_line(json.dumps(WIND_ONLY))
        self.assertEqual((r.temp_c, r.wind_avg_kmh, r.wind_max_kmh), (None, 9.0, 14.4))
        # ...but a non-La Crosse device with neither is still ignored
        self.assertIsNone(parse_rtl433_line(json.dumps({'model': 'Meter', 'id': 1, 'wind_avg_km_h': 3})))

    def test_ignores_other_lines(self):
        for line in ('', 'not json', '[]',
                     json.dumps(dict(ACURITE, channel='D')),
                     json.dumps(dict(THERMOPRO, channel=4)),
                     json.dumps(dict(ACURITE, temperature_C=150)),
                     json.dumps(dict(ACURITE, id='x')),
                     json.dumps({'model': 'Some-Meter', 'id': 1, 'temperature_C': 20})):
            self.assertIsNone(parse_rtl433_line(line), line)

    def test_command_picks_decoders_by_band(self):
        self.assertEqual(rtl433_command('433.92M'),
                         ['rtl_433', '-f', '433.92M', '-F', 'json', '-F', 'log', '-R', '40', '-R', '162'])
        cmd = rtl433_command('915M')
        self.assertNotIn('-H', cmd)
        for protocol in ('75', '76', '171', '240'):
            self.assertIn(protocol, cmd)

    def test_one_single_band_command_per_band(self):
        cmds = rtl433_commands(['433.92M', '915M', '433.92M'])
        self.assertEqual([c[2] for c in cmds], ['433.92M', '915M'])
        self.assertTrue(all('-H' not in c for c in cmds))
        self.assertIn('162', cmds[0])
        self.assertIn('171', cmds[1])

    def test_commands_skip_protocols_the_build_lacks(self):
        cmds = rtl433_commands(['433.92M', '915M'], known={'40', '75', '76', '162', '171'})
        self.assertNotIn('240', cmds[1])
        self.assertIn('171', cmds[1])

    def test_available_protocols_parses_help(self):
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fake:
            fake.write('import sys\nprint("  [40]  Acurite 592TXR\\n  [162]* ThermoPro-TX2\\n[240]  LaCrosse TX31U-IT", file=sys.stderr)\n')
        try:
            os.chmod(fake.name, 0o755)
            wrapper = fake.name + '.sh'
            with open(wrapper, 'w') as handle:
                handle.write('#!/bin/sh\nexec %s %s "$@"\n' % (sys.executable, fake.name))
            os.chmod(wrapper, 0o755)
            self.assertEqual(available_protocols(wrapper), {'40', '162', '240'})
            self.assertIsNone(available_protocols('/nonexistent/rtl_433'))
        finally:
            os.unlink(fake.name)
            os.unlink(wrapper)


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

    def test_takes_turns_between_bands(self):
        scripts = []
        for frame in (ACURITE, TX29):
            with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fake:
                # Report once, then stay up like rtl_433 until the band's turn ends.
                fake.write('import json, time\nprint(json.dumps(%r), flush=True)\ntime.sleep(60)\n' % frame)
                scripts.append(fake.name)
        try:
            got, done = [], threading.Event()

            def on_reading(reading):
                got.append(reading.source)
                if got.count('acurite') >= 2 and 'lacrosse' in got:
                    done.set()

            source = Rtl433Source([[sys.executable, scripts[0]], [sys.executable, scripts[1]]],
                                  on_reading, lambda message: None, hop_seconds=10)
            source._hop_seconds = 1  # keep the test quick
            source.start()
            self.assertTrue(done.wait(15))
            source.stop()
            self.assertEqual(got[:3], ['acurite', 'lacrosse', 'acurite'])
        finally:
            for name in scripts:
                os.unlink(name)

    def test_moves_on_once_band_sensors_report_then_rests(self):
        scripts = []
        for frame in (ACURITE, TX29):
            with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fake:
                fake.write('import json, time\nprint(json.dumps(%r), flush=True)\ntime.sleep(60)\n' % frame)
                scripts.append(fake.name)
        try:
            events, done = [], threading.Event()
            start = time.monotonic()

            def on_reading(reading):
                events.append((round(time.monotonic() - start, 1), reading.source))
                if sum(1 for _, source in events if source == 'lacrosse') >= 2:
                    done.set()

            idle = []
            source = Rtl433Source([[sys.executable, scripts[0]], [sys.executable, scripts[1]]],
                                  on_reading, lambda message: None, hop_seconds=10,
                                  rest_seconds=1, on_idle=idle.append)
            source._hop_seconds = 3  # keep the test quick
            source.start()
            self.assertTrue(done.wait(30))
            source.stop()
            # Round 1 knows no sensors yet, so each band gets its full 3 s;
            # round 2 moves on as soon as the AcuRite and La Crosse report.
            first_round = events[1][0] - events[0][0]
            second_round = events[3][0] - events[2][0]
            self.assertGreaterEqual(first_round, 4.5)   # 3 s window + 2 s switch pause
            self.assertLess(second_round, 3.5)          # switch pause only
            # The dongle went idle for the rest between rounds and came back.
            self.assertEqual(idle[:3], [False, True, False])
        finally:
            for name in scripts:
                os.unlink(name)

    def test_rtl433_errors_reach_the_log(self):
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as fake:
            fake.write('print("Found Rafael Micro R820T tuner")\nprint("Async read stalled, exiting!")\n'
                       'import sys\nsys.exit(3)\n')
        try:
            logs = []
            source = Rtl433Source([sys.executable, fake.name], lambda r: None, logs.append)
            source.start()
            for _ in range(50):
                if any('exited with code 3' in m for m in logs):
                    break
                threading.Event().wait(0.1)
            source.stop()
            self.assertIn('rtl_433: Async read stalled, exiting!', logs)
            self.assertFalse(any('Rafael' in m for m in logs))
        finally:
            os.unlink(fake.name)

    def test_missing_binary(self):
        logs = []
        missing = Rtl433Source(['/nonexistent/rtl_433'], lambda r: None, logs.append)
        missing.start()
        missing._thread.join(5)
        self.assertIn('not installed', logs[-1])


if __name__ == '__main__':
    unittest.main()
