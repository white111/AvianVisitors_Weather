"""Behaviour tests for avian/api/forecast.php, run through the PHP CLI.

Open-Meteo / zippopotam.us responses are replayed from fixtures, and the
admin gate is replaced by a stub, so no network or station state is used.
Skipped when php is not installed.
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import urlencode

ROOT = pathlib.Path(__file__).resolve().parents[1]
PHP = shutil.which('php')
GEO = 'https://geocoding-api.open-meteo.com/v1/search?'

RUNNER = r"""<?php
putenv('AV_FORECAST_LIB=1');
require __DIR__ . '/api/forecast.php';
$mode = $argv[1];
if ($mode === 'public') forecast_public();
if ($mode === 'post') forecast_admin_post(json_decode($argv[2], true));
"""

STUB_AUTH = """<?php
function avian_require_admin(): void {}
function avian_require_json_action(): void {}
"""


def forecast_url(lat, lon, unit):
    return 'https://api.open-meteo.com/v1/forecast?' + urlencode([
        ('latitude', lat), ('longitude', lon), ('current', 'temperature_2m,weather_code,is_day'),
        ('daily', 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'),
        ('temperature_unit', unit), ('timezone', 'auto'), ('forecast_days', 5),
    ])


def geo_url(name, country=None):
    params = [('name', name), ('count', 10), ('language', 'en'), ('format', 'json')]
    if country:
        params.append(('countryCode', country))
    return GEO + urlencode(params)


@unittest.skipUnless(PHP, 'php is not installed')
class ForecastApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        (self.tmp / 'api').mkdir()
        shutil.copy(ROOT / 'avian' / 'api' / 'forecast.php', self.tmp / 'api' / 'forecast.php')
        (self.tmp / 'api' / 'admin-auth.php').write_text(STUB_AUTH)
        (self.tmp / 'run.php').write_text(RUNNER)
        self.state = self.tmp / 'state'
        self.state.mkdir()
        self.fixtures = self.tmp / 'fx'
        self.fixtures.mkdir()
        self.put(geo_url('San Jose'), {'results': [
            {'name': 'San Jose', 'admin1': 'California', 'country': 'United States', 'country_code': 'US',
             'latitude': 37.33939, 'longitude': -121.89496},
            {'name': 'San José', 'admin1': 'San José', 'country': 'Costa Rica', 'country_code': 'CR',
             'latitude': 9.93333, 'longitude': -84.08333},
        ]})
        self.put(geo_url('Springfield'), {'results': [
            {'name': 'Springfield', 'admin1': 'Missouri', 'country_code': 'US', 'latitude': 37.215, 'longitude': -93.298},
            {'name': 'Springfield', 'admin1': 'Illinois', 'country_code': 'US', 'latitude': 39.801, 'longitude': -89.644},
        ]})
        self.put(geo_url('95120', 'US'), {'generationtime_ms': 0.3})
        self.put('https://api.zippopotam.us/us/95120', {'places': [
            {'place name': 'San Jose', 'state': 'California', 'latitude': '37.2147', 'longitude': '-121.8572'}]})
        self.put(forecast_url(37.2147, -121.8572, 'fahrenheit'), {
            'current': {'temperature_2m': 71.6, 'weather_code': 1, 'is_day': 1},
            'daily': {'time': ['2026-10-18', '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22'],
                      'weather_code': [1, 3, 61, 0, 2],
                      'temperature_2m_max': [78.4, 74.1, 66.0, 70.2, 72.9],
                      'temperature_2m_min': [54.2, 55.0, 52.8, 50.1, 51.5],
                      'precipitation_probability_max': [0, 10, 70, None, 5]},
        })

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, url, data):
        name = hashlib.sha1(url.encode()).hexdigest() + '.json'
        (self.fixtures / name).write_text(json.dumps(data))

    def call(self, *args, state=None):
        env = dict(os.environ, AV_FORECAST_DIR=str(state or self.state), AV_FORECAST_FIXTURES=str(self.fixtures),
                   AV_BIRDNET_CONF=str(self.tmp / 'birdnet.conf'))
        out = subprocess.run([PHP, str(self.tmp / 'run.php')] + list(args), env=env,
                             capture_output=True, text=True, check=False)
        return json.loads(out.stdout)

    def post(self, body, **kw):
        return self.call('post', json.dumps(body), **kw)

    def test_disabled_until_configured(self):
        self.assertEqual(self.call('public'), {'ok': True, 'enabled': False, 'units': 'F', 'sky': None})

    def test_sky_uses_station_location_until_a_place_is_set(self):
        (self.tmp / 'birdnet.conf').write_text('SITE_NAME="pibird"\nLATITUDE=37.212345\nLONGITUDE="-121.856789"\n')
        self.assertEqual(self.call('public')['sky'], {'lat': 37.21, 'lon': -121.86})
        self.post({'action': 'set', 'query': 'San Jose, CA'})
        self.assertEqual(self.call('public')['sky'], {'lat': 37.34, 'lon': -121.9})

    def test_unset_station_location_gives_no_sky(self):
        (self.tmp / 'birdnet.conf').write_text('LATITUDE=0\nLONGITUDE=0\n')
        self.assertIsNone(self.call('public')['sky'])

    def test_zip_falls_back_to_zippopotam_and_serves_forecast(self):
        saved = self.post({'action': 'set', 'query': '95120'})
        self.assertEqual(saved['place']['label'], 'San Jose, California 95120')
        data = self.call('public')
        self.assertTrue(data['enabled'])
        self.assertEqual(data['current'], {'temp': 72, 'code': 1, 'is_day': True})
        self.assertEqual([(d['hi'], d['lo']) for d in data['days']][:2], [(78, 54), (74, 55)])
        self.assertIsNone(data['days'][3]['pop'])
        self.assertTrue((self.state / 'cache.json').exists())

    def test_state_abbreviation_filters_matches(self):
        saved = self.post({'action': 'set', 'query': 'San Jose, CA'})
        self.assertEqual(saved['place']['label'], 'San Jose, California')
        self.assertEqual(len(saved['matches']), 1)

    def test_ambiguous_name_offers_matches_and_pick(self):
        saved = self.post({'action': 'set', 'query': 'Springfield'})
        self.assertEqual([m['label'] for m in saved['matches']], ['Springfield, Missouri', 'Springfield, Illinois'])
        picked = self.post({'action': 'pick', 'label': 'Springfield, Illinois', 'lat': 39.801, 'lon': -89.644})
        self.assertEqual((picked['place']['label'], picked['query']), ('Springfield, Illinois', 'Springfield, Illinois'))

    def test_rejects_bad_input(self):
        self.assertFalse(self.post({'action': 'set', 'query': '<script>'})['ok'])
        self.assertFalse(self.post({'action': 'set', 'query': 'Nowhereville'})['ok'])
        self.assertFalse(self.post({'action': 'pick', 'label': 'x', 'lat': 200, 'lon': 0})['ok'])
        self.assertFalse(self.post({'action': 'enabled', 'enabled': 'yes'})['ok'])
        self.assertFalse(self.post({'action': 'enabled', 'enabled': True})['ok'])
        self.assertFalse(self.post({'action': 'bogus'})['ok'])

    def test_disable_and_clear(self):
        self.post({'action': 'set', 'query': '95120'})
        self.post({'action': 'enabled', 'enabled': False})
        self.assertFalse(self.call('public')['enabled'])
        cleared = self.post({'action': 'clear'})
        self.assertIsNone(cleared['place'])

    def test_missing_storage_is_reported(self):
        result = self.post({'action': 'set', 'query': '95120'}, state=self.tmp / 'missing')
        self.assertFalse(result['ok'])
        self.assertIn('install.sh', result['hint'])


class ForecastWiringTest(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding='utf-8')

    def test_admin_gate_on_writes(self):
        source = self.read('avian/api/forecast.php')
        self.assertIn("require_once __DIR__ . '/admin-auth.php';", source)
        self.assertIn('avian_require_admin();', source)
        self.assertIn('avian_require_json_action();', source)

    def test_published_and_deployed(self):
        self.assertIn('/avian/api/forecast.php', self.read('scripts/update_caddyfile.sh'))
        self.assertIn('/avian/api/thermopro.php', self.read('scripts/update_caddyfile.sh'))
        manifest = self.read('scripts/link_webroot.sh')
        self.assertIn('"thermopro.js"', manifest)
        self.assertIn('"thermopro.css"', manifest)
        self.assertIn('/var/lib/avian-forecast', self.read('scripts/install_services.sh'))
        self.assertIn('/var/lib/avian-forecast', self.read('avian/thermopro/install.sh'))


if __name__ == '__main__':
    unittest.main()
