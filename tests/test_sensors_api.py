"""Behaviour tests for avian/api/thermopro.php (sensor readings + names).

Runs through the PHP CLI with a stubbed admin gate and temporary state.
Skipped when php is not installed.
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PHP = shutil.which('php')

RUNNER = r"""<?php
putenv('AV_SENSORS_LIB=1');
require __DIR__ . '/api/thermopro.php';
$mode = $argv[1];
if ($mode === 'public') sensors_public();
if ($mode === 'config') sensors_respond(200, sensors_admin_view());
if ($mode === 'post') sensors_admin_post(json_decode($argv[2], true));
"""

STUB_AUTH = """<?php
function avian_require_admin(): void {}
function avian_require_json_action(): void {}
"""


@unittest.skipUnless(PHP, 'php is not installed')
class SensorsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / 'api').mkdir()
        shutil.copy(ROOT / 'avian' / 'api' / 'thermopro.php', self.tmp / 'api' / 'thermopro.php')
        (self.tmp / 'api' / 'admin-auth.php').write_text(STUB_AUTH)
        (self.tmp / 'run.php').write_text(RUNNER)
        self.settings = self.tmp / 'settings'
        self.settings.mkdir()
        now = int(time.time())
        self.readings = self.tmp / 'latest.json'
        self.readings.write_text(json.dumps({'units': 'F', 'sensors': [
            {'source': 'thermopro', 'channel': '1', 'label': 'Outside', 'temp_c': 23.1, 'humidity': 14, 'seen': now - 30},
            {'source': 'acurite', 'channel': 'A', 'label': 'AcuRite A', 'temp_c': 18.4, 'humidity': 62, 'seen': now - 5},
            {'channel': 2, 'label': 'Old', 'temp_c': 20, 'seen': now - 100},
            {'source': 'acurite', 'channel': 'Z', 'temp_c': 1, 'seen': now},
            {'source': 'lacrosse', 'channel': '42', 'temp_c': 16.2, 'humidity': None, 'seen': now - 2},
            {'source': 'lacrosse', 'channel': '2989076', 'temp_c': 19.4, 'humidity': 58, 'seen': now - 1},
            {'source': 'lacrosse', 'channel': '8994842', 'model': 'LaCrosse-BreezePro', 'temp_c': 24.5, 'humidity': 44,
             'wind_avg_kmh': 9.7, 'wind_dir_deg': 315, 'seen': now - 3},
            {'source': 'lacrosse', 'channel': '17', 'model': 'LaCrosse-WindSensor', 'temp_c': None,
             'wind_avg_kmh': 9.0, 'wind_max_kmh': 14.4, 'seen': now - 3},
            {'source': 'lacrosse', 'channel': '18', 'temp_c': None, 'seen': now},
        ]}))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, *args, settings=None):
        env = dict(os.environ, AV_THERMOPRO_FILE=str(self.readings), AV_FORECAST_DIR=str(settings or self.settings))
        out = subprocess.run([PHP, str(self.tmp / 'run.php')] + list(args), env=env,
                             capture_output=True, text=True, check=False)
        return json.loads(out.stdout)

    def post(self, body, **kw):
        return self.call('post', json.dumps(body), **kw)

    def labels(self):
        return {s['key']: s['label'] for s in self.call('public')['sensors']}

    def test_public_uses_receiver_labels_and_drops_bad_channels(self):
        self.assertEqual(self.labels(), {'thermopro-1': 'Outside', 'acurite-A': 'AcuRite A', 'thermopro-2': 'Old',
                                         'lacrosse-42': 'La Crosse 42', 'lacrosse-2989076': 'La Crosse 2989076',
                                         'lacrosse-8994842': 'La Crosse 8994842', 'lacrosse-17': 'La Crosse 17'})

    def test_name_overrides_and_blank_restores(self):
        self.post({'action': 'name', 'key': 'acurite-A', 'name': '  Back   porch '})
        self.assertEqual(self.labels()['acurite-A'], 'Back porch')
        self.post({'action': 'name', 'key': 'acurite-A', 'name': ''})
        self.assertEqual(self.labels()['acurite-A'], 'AcuRite A')

    def test_wind_is_passed_through(self):
        rows = {s['key']: s for s in self.call('public')['sensors']}
        breeze = rows['lacrosse-8994842']
        self.assertEqual((breeze['temp_c'], breeze['wind_avg_kmh'], breeze['wind_dir_deg']), (24.5, 9.7, 315))
        self.assertNotIn('wind_max_kmh', breeze)
        wind_only = rows['lacrosse-17']
        self.assertEqual((wind_only['temp_c'], wind_only['wind_max_kmh']), (None, 14.4))
        self.assertNotIn('wind_avg_kmh', rows['thermopro-1'])

    def test_hide_and_show(self):
        self.post({'action': 'hide', 'key': 'thermopro-2', 'hidden': True})
        self.assertNotIn('thermopro-2', self.labels())
        self.post({'action': 'hide', 'key': 'thermopro-2', 'hidden': False})
        self.assertIn('thermopro-2', self.labels())

    def test_config_lists_heard_and_named_sensors(self):
        self.post({'action': 'name', 'key': 'acurite-C', 'name': 'Garage'})
        view = self.call('config')
        rows = {s['key']: s for s in view['sensors']}
        self.assertEqual(sorted(rows), ['acurite-A', 'acurite-C', 'lacrosse-17', 'lacrosse-2989076', 'lacrosse-42',
                                        'lacrosse-8994842', 'thermopro-1', 'thermopro-2'])
        self.assertEqual(rows['lacrosse-42']['model'], 'La Crosse IT+')
        self.assertEqual(rows['lacrosse-8994842']['model'], 'La Crosse BreezePro')
        self.assertEqual(rows['acurite-A']['model'], 'AcuRite 592TXR')
        self.assertTrue(rows['acurite-A']['heard'])
        self.assertEqual(rows['acurite-A']['model'], 'AcuRite 592TXR')
        self.assertFalse(rows['acurite-C']['heard'])
        self.assertEqual(rows['acurite-C']['name'], 'Garage')
        self.assertTrue(view['storage_ok'])

    def test_forget(self):
        self.post({'action': 'name', 'key': 'acurite-C', 'name': 'Garage'})
        view = self.post({'action': 'forget', 'key': 'acurite-C'})
        self.assertNotIn('acurite-C', [s['key'] for s in view['sensors']])

    def test_rain_gauge_without_temperature(self):
        data = json.loads(self.readings.read_text())
        data['sensors'].append({'source': 'lacrosse', 'channel': '3803948', 'model': 'LaCrosse-R3', 'temp_c': None,
                                'rain_today_mm': 2.5, 'rain_total_mm': 128.27, 'seen': int(time.time())})
        self.readings.write_text(json.dumps(data))
        row = {s['key']: s for s in self.call('public')['sensors']}['lacrosse-3803948']
        self.assertEqual((row['temp_c'], row['rain_today_mm']), (None, 2.5))
        self.assertNotIn('rain_total_mm', row)
        config = {s['key']: s for s in self.call('config')['sensors']}['lacrosse-3803948']
        self.assertEqual(config['model_name'], 'La Crosse R3')

    def test_rejects_bad_input(self):
        self.assertFalse(self.post({'action': 'name', 'key': 'acurite-Z', 'name': 'x'})['ok'])
        self.assertFalse(self.post({'action': 'name', 'key': '../etc', 'name': 'x'})['ok'])
        self.assertFalse(self.post({'action': 'name', 'key': 'lacrosse-1234567890', 'name': 'x'})['ok'])
        self.assertFalse(self.post({'action': 'name', 'key': 'acurite-A', 'name': 5})['ok'])
        self.assertFalse(self.post({'action': 'hide', 'key': 'acurite-A', 'hidden': 'yes'})['ok'])
        self.assertFalse(self.post({'action': 'bogus', 'key': 'acurite-A'})['ok'])

    def test_long_names_are_trimmed(self):
        self.post({'action': 'name', 'key': 'thermopro-1', 'name': 'x' * 80})
        self.assertEqual(len(self.labels()['thermopro-1']), 24)

    def test_missing_storage_is_reported(self):
        result = self.post({'action': 'name', 'key': 'thermopro-1', 'name': 'x'}, settings=self.tmp / 'missing')
        self.assertFalse(result['ok'])
        self.assertIn('install.sh', result['hint'])

    def test_no_receiver_file_yet(self):
        self.readings.unlink()
        self.assertEqual(self.call('public')['sensors'], [])
        self.assertFalse(self.call('config')['receiver'])


if __name__ == '__main__':
    unittest.main()
