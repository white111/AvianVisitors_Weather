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
                                         'lacrosse-42': 'La Crosse 42'})

    def test_name_overrides_and_blank_restores(self):
        self.post({'action': 'name', 'key': 'acurite-A', 'name': '  Back   porch '})
        self.assertEqual(self.labels()['acurite-A'], 'Back porch')
        self.post({'action': 'name', 'key': 'acurite-A', 'name': ''})
        self.assertEqual(self.labels()['acurite-A'], 'AcuRite A')

    def test_hide_and_show(self):
        self.post({'action': 'hide', 'key': 'thermopro-2', 'hidden': True})
        self.assertNotIn('thermopro-2', self.labels())
        self.post({'action': 'hide', 'key': 'thermopro-2', 'hidden': False})
        self.assertIn('thermopro-2', self.labels())

    def test_config_lists_heard_and_named_sensors(self):
        self.post({'action': 'name', 'key': 'acurite-C', 'name': 'Garage'})
        view = self.call('config')
        rows = {s['key']: s for s in view['sensors']}
        self.assertEqual(sorted(rows), ['acurite-A', 'acurite-C', 'lacrosse-42', 'thermopro-1', 'thermopro-2'])
        self.assertEqual(rows['lacrosse-42']['model'], 'La Crosse IT+')
        self.assertTrue(rows['acurite-A']['heard'])
        self.assertEqual(rows['acurite-A']['model'], 'AcuRite 592TXR')
        self.assertFalse(rows['acurite-C']['heard'])
        self.assertEqual(rows['acurite-C']['name'], 'Garage')
        self.assertTrue(view['storage_ok'])

    def test_forget(self):
        self.post({'action': 'name', 'key': 'acurite-C', 'name': 'Garage'})
        view = self.post({'action': 'forget', 'key': 'acurite-C'})
        self.assertNotIn('acurite-C', [s['key'] for s in view['sensors']])

    def test_rejects_bad_input(self):
        self.assertFalse(self.post({'action': 'name', 'key': 'acurite-Z', 'name': 'x'})['ok'])
        self.assertFalse(self.post({'action': 'name', 'key': '../etc', 'name': 'x'})['ok'])
        self.assertFalse(self.post({'action': 'name', 'key': 'lacrosse-1234', 'name': 'x'})['ok'])
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
