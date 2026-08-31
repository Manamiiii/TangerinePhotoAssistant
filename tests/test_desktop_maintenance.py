import hashlib
import json
import logging
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from tangerine_photo_assistant.build_info import version_summary
from tangerine_photo_assistant.desktop_logs import LogStream, bounded_handler
from tangerine_photo_assistant.desktop_window import DesktopWindow

ROOT = Path(__file__).resolve().parents[1]


class DesktopMaintenanceTests(unittest.TestCase):
    def test_stop_requires_confirmation_and_never_restarts(self):
        client = Mock()
        controller = DesktopWindow(client)
        controller.window = Mock()
        controller.window.create_confirmation_dialog.return_value = False
        controller.stop()
        client.stop.assert_not_called()
        controller.window.create_confirmation_dialog.return_value = True
        controller.stop()
        client.stop.assert_called_once()
        client.restart.assert_not_called()

    def test_package_inspection_is_read_only_and_handles_malformed_manifest(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package-manifest.json").write_text("[]")
            client = Mock()
            controller = DesktopWindow(client)
            controller.window = Mock()
            controller.window.create_file_dialog.return_value = [temporary]
            controller.information = Mock()
            with patch.dict("sys.modules", {"webview": Mock()}):
                controller.inspect_package()
            self.assertIn("未找到", controller.information.call_args.args[1])
            self.assertEqual((root / "package-manifest.json").read_text(), "[]")
            client.restart.assert_not_called()

    def test_linked_log_does_not_overwrite_external_file(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "personal.txt"
            target.write_text("preserve me")
            logs = root / "logs"
            logs.mkdir()
            os.link(target, logs / "service.log")
            with self.assertRaises(ValueError):
                bounded_handler(logs)
            self.assertEqual(target.read_text(), "preserve me")

    def test_versions_distinguish_legacy_and_different_builds(self):
        local = {"version": "0.1.0", "revision": "abc", "dirty": False}
        self.assertIn("无法比较", version_summary(local, None))
        self.assertNotIn("构建不同", version_summary(local, {"build": local}))
        self.assertIn("构建不同", version_summary(local, {"build": local | {"revision": "def"}}))

    def test_logs_are_bounded_and_do_not_persist_private_content(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "service.json").write_text("secret credential", encoding="utf-8")
            (directory / "other.log").write_text("unrelated", encoding="utf-8")
            handler = bounded_handler(directory, max_bytes=256, backups=2)
            try:
                stream = LogStream(handler)
                for _ in range(100):
                    stream.write("private path GPS search query")
                    handler.handle(logging.LogRecord("uvicorn.error", logging.ERROR, "private.py", 1,
                                                      "secret token", (), (ValueError, ValueError("private"), None)))
            finally:
                handler.close()
            logs = list(directory.glob("service.log*"))
            self.assertLessEqual(len(logs), 3)
            for path in logs:
                self.assertLessEqual(path.stat().st_size, 256)
                self.assertNotIn("private", path.read_text(encoding="utf-8"))
                self.assertNotIn("secret", path.read_text(encoding="utf-8"))
            self.assertEqual((directory / "service.json").read_text(), "secret credential")
            self.assertEqual((directory / "other.log").read_text(), "unrelated")


@unittest.skipUnless(os.name == "nt", "Windows installer uses native PowerShell and shortcuts")
class WindowsPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="tangerine-package-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.install = self.root / "program"
        self.config = self.root / "user-config.toml"
        self.config.write_text("user configuration", encoding="utf-8")
        for name in ("install_windows_app.ps1", "manage_windows_app.ps1", "windows_package_common.ps1"):
            shutil.copyfile(ROOT / "scripts" / name, self.bundle / name)
        (self.bundle / "TangerinePhotoAssistant.exe").write_bytes(b"isolated fake executable - never executed")
        (self.bundle / "readme.txt").write_text("program content", encoding="utf-8")
        self.manifest = {"app_id": "tangerine-photo-assistant", "format": 1, "version": "test", "schema_version": 32,
                         "files": [{"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                   for p in self.bundle.iterdir()]}
        self.write_manifest()

    def write_manifest(self):
        (self.bundle / "package-manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def run_ps(self, script, *args, success=True):
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(self.bundle / script), "-InstallRoot", str(self.install), *map(str, args)],
                                capture_output=True, timeout=30, check=False)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def state(self):
        return json.loads((self.install / ".tangerine-install.json").read_text(encoding="utf-8-sig"))

    def install_package(self, *args):
        self.run_ps("install_windows_app.ps1", "-NoShortcuts", *args)
        return self.state()["active"]

    def test_install_upgrade_preview_rollback_uninstall_preserves_user_files(self):
        first = self.install_package("-ConfigFile", self.config)
        second = self.install_package()
        self.assertEqual(self.state()["config"], str(self.config))
        release = self.install / first
        (release / "readme.txt").write_text("user changed", encoding="utf-8")
        (release / "user-photo.jpg").write_bytes(b"synthetic user data")
        self.run_ps("manage_windows_app.ps1", "-Action", "Uninstall", "-Release", first)
        self.assertTrue((release / "TangerinePhotoAssistant.exe").exists())
        # Modified program file prevents activating a damaged release.
        self.run_ps("manage_windows_app.ps1", "-Action", "Activate", "-Release", first, "-Apply", success=False)
        (release / "readme.txt").write_text("program content", encoding="utf-8")
        self.run_ps("manage_windows_app.ps1", "-Action", "Activate", "-Release", first, "-Apply")
        self.assertEqual(self.state()["active"], first)
        (release / "readme.txt").write_text("user changed", encoding="utf-8")
        self.run_ps("manage_windows_app.ps1", "-Action", "Uninstall", "-Release", first, "-Apply")
        self.assertFalse((release / "TangerinePhotoAssistant.exe").exists())
        self.assertEqual((release / "readme.txt").read_text(), "user changed")
        self.assertEqual((release / "user-photo.jpg").read_bytes(), b"synthetic user data")
        self.assertEqual(self.config.read_text(), "user configuration")
        self.assertEqual(self.state()["releases"], [second])
        self.assertEqual(self.state()["active"], "")

    def test_corrupt_package_and_traversal_are_rejected(self):
        (self.bundle / "readme.txt").write_text("tampered", encoding="utf-8")
        self.run_ps("install_windows_app.ps1", "-NoShortcuts", success=False)
        self.assertFalse(self.install.exists())
        self.manifest["files"][0]["path"] = "../user-config.toml"
        self.write_manifest()
        self.run_ps("install_windows_app.ps1", "-NoShortcuts", success=False)
        self.assertEqual(self.config.read_text(), "user configuration")

    def test_schema_downgrade_and_foreign_release_are_rejected(self):
        first = self.install_package()
        self.manifest["schema_version"] = 33
        self.write_manifest()
        second = self.install_package()
        self.run_ps("manage_windows_app.ps1", "-Action", "Activate", "-Release", first, "-Apply", success=False)
        self.run_ps("manage_windows_app.ps1", "-Action", "Uninstall", "-Release", "../elsewhere", "-Apply", success=False)
        self.assertEqual(self.state()["active"], second)

    def test_unmanaged_directory_is_not_claimed(self):
        self.install.mkdir()
        (self.install / "catalog.sqlite3").write_bytes(b"synthetic database")
        self.run_ps("install_windows_app.ps1", "-NoShortcuts", success=False)
        self.assertEqual((self.install / "catalog.sqlite3").read_bytes(), b"synthetic database")

    def test_running_program_blocks_removal(self):
        release = self.install_package()
        # Substitute process discovery only; use the real removal entry and guards.
        command = "function Get-CimInstance { [pscustomobject]@{Name='TangerinePhotoAssistant.exe';ExecutablePath='" + str(self.install / release / "TangerinePhotoAssistant.exe").replace("'", "''") + "'} }; & '" + str(self.bundle / "manage_windows_app.ps1").replace("'", "''") + "' -InstallRoot '" + str(self.install).replace("'", "''") + "' -Action Uninstall -Release '" + release + "' -Apply"
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], capture_output=True, timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.install / release / "TangerinePhotoAssistant.exe").exists())


if __name__ == "__main__":
    unittest.main()
