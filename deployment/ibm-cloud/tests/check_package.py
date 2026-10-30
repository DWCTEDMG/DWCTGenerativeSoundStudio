from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[3]


class PackageTests(unittest.TestCase):
    def test_manifest_paths(self):
        manifest = json.loads((ROOT / 'ibm_catalog.json').read_text())
        self.assertEqual(manifest, json.loads((ROOT / 'deployment/ibm-cloud/ibm_catalog.json').read_text()))
        for product in manifest['products']:
            for flavor in product['flavors']:
                self.assertTrue((ROOT / flavor['working_directory'] / 'main.tf').is_file())

    def test_network_and_auth_boundary(self):
        bootstrap = (ROOT / 'deployment/ibm-cloud/scripts/cloud-init.yaml.tftpl').read_text()
        self.assertIn('127.0.0.1:7863:7863', bootstrap)
        self.assertIn('EDMG_BACKEND_AUTH_MODE=required', bootstrap)
        self.assertIn('openssl rand -hex 32', bootstrap)


if __name__ == '__main__':
    unittest.main()
