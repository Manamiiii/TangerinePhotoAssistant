import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tangerine_photo_assistant.app_paths import (
    DataLocationError,
    config_identity,
    legacy_app_directory,
    service_logs_directory,
    service_runtime_directory,
    user_app_directory,
    webview_directory,
)
from tangerine_photo_assistant.desktop import prepare_default_config
from tangerine_photo_assistant.desktop_lock import FileLease, LeaseBusy
from tangerine_photo_assistant.service_runtime import run_service
from tangerine_photo_assistant.settings import Settings, write_safe_config


class AppPathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.profile = Path(self.temporary.name)
        environment = patch.dict(os.environ, LOCALAPPDATA=str(self.profile))
        environment.start()
        self.addCleanup(environment.stop)

    def old_config(self):
        root = legacy_app_directory()
        root.mkdir(parents=True)
        (root / 'PhotoInbox').mkdir()
        config = root / 'config.toml'
        write_safe_config(config, root / 'PhotoInbox', root / 'Workspace', root / 'Cache')
        return config

    def test_new_default_is_central_and_repeatable_without_database_creation(self):
        config = prepare_default_config()
        root = self.profile / 'Tangerine/Data/TangerinePhotoAssistant'
        self.assertEqual(config, root / 'Config/config.toml')
        settings = Settings.load(config)
        self.assertEqual(settings.workspace, (root / 'Storage/Workspace').resolve())
        self.assertEqual(settings.originals, (root / 'Storage/PhotoInbox').resolve())
        self.assertEqual(settings.cache_root, (root / 'Cache').resolve())
        before = config.read_bytes()
        self.assertEqual(prepare_default_config(), config)
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse(settings.database_path.exists())
        self.assertEqual(service_logs_directory(config, 8765).parent, root / 'Logs')
        self.assertEqual(webview_directory(config, 8765).parent, root / 'Storage/WebView2')

    def test_legacy_configuration_is_used_in_place_with_identity_and_bytes_preserved(self):
        config = self.old_config()
        before = config.read_bytes()
        identity = config_identity(config)
        self.assertEqual(prepare_default_config(), config)
        self.assertEqual(config_identity(prepare_default_config()), identity)
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse(user_app_directory().exists())

    def test_two_default_configs_and_orphan_data_fail_without_changes(self):
        current = prepare_default_config()
        legacy = self.old_config()
        before = (current.read_bytes(), legacy.read_bytes())
        with self.assertRaises(DataLocationError):
            prepare_default_config()
        self.assertEqual((current.read_bytes(), legacy.read_bytes()), before)
        legacy.unlink()
        with self.assertRaises(DataLocationError):
            prepare_default_config()

    def test_corrupt_config_and_interrupted_creation_are_not_overwritten(self):
        config = self.old_config()
        config.write_bytes(b'invalid toml')
        with self.assertRaises(ValueError):
            prepare_default_config()
        self.assertEqual(config.read_bytes(), b'invalid toml')
        self.assertFalse(user_app_directory().exists())

    def test_missing_config_with_new_workspace_refuses_empty_replacement(self):
        sentinel = user_app_directory() / 'Storage/Workspace/catalog.sqlite3'
        sentinel.parent.mkdir(parents=True)
        sentinel.write_bytes(b'synthetic data to preserve')
        with self.assertRaises(DataLocationError):
            prepare_default_config()
        self.assertEqual(sentinel.read_bytes(), b'synthetic data to preserve')
        self.assertFalse((user_app_directory() / 'Config/config.toml').exists())

    def test_creation_failure_can_retry_without_overwriting_and_creation_is_locked(self):
        with patch('tangerine_photo_assistant.desktop.write_safe_config', side_effect=OSError('synthetic failure')), \
                self.assertRaises(OSError):
            prepare_default_config()
        with FileLease(user_app_directory() / 'Runtime/default-config.lock'), self.assertRaises(LeaseBusy):
            prepare_default_config()
        self.assertTrue(prepare_default_config().is_file())

    def test_legacy_runtime_keeps_profile_and_lease_then_rejects_two_copies(self):
        config = self.profile / 'external/config.toml'
        key = f'{config_identity(config)}-8765'
        old = legacy_app_directory() / 'Runtime' / key
        profile = old / 'WebView2/synthetic-profile'
        profile.parent.mkdir(parents=True)
        profile.write_bytes(b'preferences')
        self.assertEqual(service_runtime_directory(config, 8765), old)
        self.assertEqual(webview_directory(config, 8765), old / 'WebView2')
        self.assertEqual(service_logs_directory(config, 8765), old)
        (user_app_directory() / 'Runtime' / key).mkdir(parents=True)
        with self.assertRaises(DataLocationError):
            service_runtime_directory(config, 8765)
        self.assertEqual(profile.read_bytes(), b'preferences')

    def test_new_backend_locks_both_generations_and_does_not_start_if_old_active(self):
        config = self.profile / 'external/config.toml'
        runtime = service_runtime_directory(config, 18765)
        old_lock = legacy_app_directory() / 'Runtime' / runtime.name / 'backend.lock'

        def backend(*args):
            self.assertEqual(service_runtime_directory(config, 18765), runtime)
            for lock in (old_lock, runtime / 'backend.lock'):
                with self.assertRaises(LeaseBusy), FileLease(lock):
                    self.fail('duplicate backend accepted')
            return 0

        with patch('tangerine_photo_assistant.service_runtime._run_service', side_effect=backend) as run:
            with FileLease(old_lock), self.assertRaises(LeaseBusy):
                run_service(config, '127.0.0.1', 18765)
            run.assert_not_called()
            self.assertEqual(run_service(config, '127.0.0.1', 18765), 0)
        self.assertEqual(service_runtime_directory(config, 18765), runtime)
        self.assertNotEqual(runtime, service_runtime_directory(config, 18766))
        self.assertNotEqual(runtime, service_runtime_directory(self.profile / 'other.toml', 18765))
