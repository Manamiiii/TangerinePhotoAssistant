import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.package_notices import proxy_notices


class ProxyLicenseTests(unittest.TestCase):
    def test_reviewed_license_bytes_are_preserved_in_checkout(self):
        root = Path(__file__).resolve().parents[1] / 'assets/licenses'
        evidence = json.loads((root / 'proxy-tools-0.1.0-provenance.json').read_text())
        self.assertEqual(hashlib.sha256((root / evidence['license_file']).read_bytes()).hexdigest(),
                         evidence['license_sha256'])

    def test_changed_package_or_license_cannot_reuse_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            licenses = root / 'assets/licenses'
            licenses.mkdir(parents=True)
            (root / 'docs').mkdir()
            (root / 'docs/PROXY_TOOLS_LICENSE.md').write_text('Evidence')
            (licenses / 'Werkzeug-0.9.6-LICENSE.txt').write_text('Supplement')
            source = root / 'module.py'
            source.write_bytes(b'# reviewed source')
            license_text = b'Copyright fixture\nRedistribution permitted\n'
            (licenses / 'LICENSE.txt').write_bytes(license_text)
            evidence = {'version': '0.1.0', 'source_path': 'module.py', 'license_file': 'LICENSE.txt',
                        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'license_sha256': hashlib.sha256(license_text).hexdigest()}
            (licenses / 'proxy-tools-0.1.0-provenance.json').write_text(json.dumps(evidence))
            target = root / 'output'
            target.mkdir()
            dist = SimpleNamespace(version='0.1.0', metadata='License: MIT', locate_file=lambda _: source)
            proxy_notices(dist, target, root)
            self.assertEqual((target / 'LICENSE.txt').read_bytes(), license_text)
            dist.version = '0.2.0'
            with self.assertRaises(ValueError):
                proxy_notices(dist, target, root)
            dist.version = '0.1.0'
            source.write_bytes(b'# changed source')
            with self.assertRaises(ValueError):
                proxy_notices(dist, target, root)
            source.write_bytes(b'# reviewed source')
            (licenses / 'LICENSE.txt').write_bytes(b'changed license')
            with self.assertRaises(ValueError):
                proxy_notices(dist, target, root)
