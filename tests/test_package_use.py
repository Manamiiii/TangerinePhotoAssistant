import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tangerine_photo_assistant.package_use import installed_program_use


@unittest.skipUnless(sys.platform == 'win32', 'Windows sharing semantics')
class InstalledUseTests(unittest.TestCase):
    def test_shared_program_lifetimes_block_exclusive_maintenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.tangerine-install.json').write_text('{}')
            (root / '.app-use.lock').touch()
            with patch.object(sys, 'frozen', True, create=True), patch.object(
                    sys, 'executable', str(root / 'release/fixture.exe')):
                with installed_program_use(), installed_program_use():
                    command = "$s=[IO.File]::Open($env:TANGERINE_TEST_LOCK,'Open','ReadWrite','None');$s.Dispose()"
                    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                            env={**os.environ, 'TANGERINE_TEST_LOCK': str(root / '.app-use.lock')},
                                            capture_output=True, check=False, timeout=30,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertNotEqual(result.returncode, 0)
                with installed_program_use():
                    pass
