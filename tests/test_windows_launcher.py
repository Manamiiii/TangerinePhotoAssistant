from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class WindowsLauncherTests(unittest.TestCase):
    def test_launcher_entries_use_one_controller(self) -> None:
        controller = ROOT / "scripts" / "windows_launcher.ps1"
        silent_entry = (ROOT / "TangerinePhotoAssistant.vbs").read_text(encoding="utf-8")
        command_entry = (ROOT / "start-photo-assistant.cmd").read_text(encoding="utf-8")
        installer = (ROOT / "install-windows-launcher.cmd").read_text(encoding="utf-8")
        self.assertTrue(controller.is_file())
        self.assertIn("windows_launcher.ps1", silent_entry)
        self.assertIn("windows_launcher.ps1", command_entry)
        self.assertIn("-Mode Install", installer)
        self.assertNotIn("config.example.toml", command_entry)
        controller_text = controller.read_text(encoding="utf-8")
        icon = ROOT / "assets" / "tangerine-photo-assistant.ico"
        self.assertTrue(icon.is_file())
        self.assertGreater(icon.stat().st_size, 1_024)
        with Image.open(icon) as image:
            self.assertEqual(image.format, "ICO")
            self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(image.info["sizes"]))
        self.assertIn("assets\\tangerine-photo-assistant.ico", controller_text)
        self.assertIn('$shortcut.IconLocation = "$IconFile,0"', controller_text)
        self.assertIn("Get-TrackedTangerineProcess", controller_text)
        self.assertIn("$attempt -lt 900", controller_text)
        self.assertIn("System.Threading.Mutex", controller_text)

    @unittest.skipUnless(os.name == "nt", "PowerShell launcher validation is Windows-only")
    def test_current_checkout_passes_launcher_validation(self) -> None:
        result = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(ROOT / "scripts" / "windows_launcher.ps1"),
                "-Mode", "Validate", "-Console",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prerequisites are ready", result.stdout)


if __name__ == "__main__":
    unittest.main()
