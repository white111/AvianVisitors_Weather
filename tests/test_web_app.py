"""The collage installs as a web app: manifest, home-screen tags, webroot link."""

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'avian' / 'frontend'


class WebAppTest(unittest.TestCase):
    def test_manifest(self):
        manifest = json.loads((FRONTEND / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['display'], 'standalone')
        self.assertEqual((manifest['start_url'], manifest['scope']), ('./', './'))
        self.assertTrue(manifest['name'] and manifest['short_name'])
        icon = manifest['icons'][0]
        self.assertEqual(icon['src'].split('?')[0], 'favicon.png')
        self.assertTrue((ROOT / 'avian' / 'assets' / 'favicon.png').exists())

    def test_index_links_manifest_and_home_screen_tags(self):
        html = (FRONTEND / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<link rel="manifest" href="./manifest.json', html)
        self.assertIn('<meta name="apple-mobile-web-app-capable" content="yes">', html)
        self.assertIn('<link rel="apple-touch-icon"', html)

    def test_manifest_is_published(self):
        script = (ROOT / 'scripts' / 'link_webroot.sh').read_text(encoding='utf-8')
        self.assertIn('"${frontend_dir}/manifest.json"', script)
        self.assertIn('    "manifest.json"', script)


if __name__ == '__main__':
    unittest.main()
