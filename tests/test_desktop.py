import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from tangerine_photo_assistant.app_paths import config_identity
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.desktop import DesktopError, ServiceClient, validate_desktop
from tangerine_photo_assistant.desktop_lock import FileLease, LeaseBusy
from tangerine_photo_assistant.desktop_window import DesktopWindow
from tangerine_photo_assistant.service_runtime import APP_ID, CONTROL_HEADER, ServiceControl
from tangerine_photo_assistant.settings import Settings, write_safe_config
from tangerine_photo_assistant.webapp import ScanTaskManager, create_app


def configuration(root):
    photos = root / "photos"
    photos.mkdir()
    config = root / "config.toml"
    write_safe_config(config, photos, root / "workspace", root / "cache")
    return config


class DesktopTests(unittest.TestCase):
    def test_validation_only_does_not_create_database(self):
        with TemporaryDirectory() as temporary:
            config = configuration(Path(temporary))
            resources = Path(temporary) / "resources"
            for relative in ("web/dist/index.html", "equipment/profile.toml", "assets/tangerine-photo-assistant.ico"):
                target = resources / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            with patch("tangerine_photo_assistant.desktop.resource_root", return_value=resources):
                self.assertEqual(validate_desktop(config)["status"], "ok")
                (resources / "web/dist/index.html").unlink()
                with self.assertRaises(DesktopError):
                    validate_desktop(config)
            self.assertFalse(Settings.load(config).database_path.exists())

    def test_lease_rejects_duplicate_and_is_released(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "service.lock"
            with FileLease(path), self.assertRaises(LeaseBusy), FileLease(path):
                self.fail("second owner")
            with FileLease(path):
                pass

    def test_service_identity_is_checked_and_secret_is_not_public(self):
        with TemporaryDirectory() as temporary:
            config = configuration(Path(temporary))
            control = ServiceControl(config, 18876)
            client = ServiceClient(config, 18876)
            health = {"status": "ok", "mode": "local-only", **control.public_identity()}
            with patch.object(client, "request", return_value=health):
                self.assertEqual(client.health()["app_id"], APP_ID)
            self.assertNotIn(control.token, json.dumps(health))
            self.assertNotIn(control.token, repr(control))
            with patch.object(client, "request", return_value=health | {"config_identity": "other"}), \
                    self.assertRaises(DesktopError):
                client.health()

    def test_shutdown_requires_both_tokens_and_stops_new_writes(self):
        with TemporaryDirectory() as temporary:
            config = configuration(Path(temporary))
            control = ServiceControl(config, 18876, shutdown=Mock())
            with TestClient(create_app(config, service_control=control), base_url="http://127.0.0.1") as client:
                session = client.get("/api/session").json()
                headers = {session["header"]: session["token"]}
                endpoint = "/api/system/desktop/shutdown"
                self.assertEqual(client.post(endpoint).status_code, 403)
                self.assertEqual(client.post(endpoint, headers=headers).status_code, 403)
                headers[CONTROL_HEADER] = control.token
                wrong_origin = headers | {"Origin": "https://untrusted.example"}
                self.assertEqual(client.post(endpoint, headers=wrong_origin).status_code, 403)
                self.assertFalse(control.draining)
                self.assertEqual(client.post(endpoint, headers=headers).status_code, 200)
                control.shutdown.assert_called_once()
                self.assertTrue(client.get("/api/health").json()["draining"])
                self.assertEqual(client.post("/api/scan", json={"album_id": 1}, headers=headers).status_code, 503)

    def test_running_paused_and_persistent_tasks_refuse_shutdown(self):
        with TemporaryDirectory() as temporary:
            config = configuration(Path(temporary))
            control = ServiceControl(config, 18876, shutdown=Mock())
            with TestClient(create_app(config, service_control=control), base_url="http://127.0.0.1") as client:
                session = client.get("/api/session").json()
                headers = {session["header"]: session["token"], CONTROL_HEADER: control.token}
                for status in ("running", "paused", "queued", "cancel_requested"):
                    with patch.object(ScanTaskManager, "snapshot", return_value={"status": status}):
                        self.assertEqual(client.post("/api/system/desktop/shutdown", headers=headers).status_code, 409)
                connection = connect(Settings.load(config).database_path)
                try:
                    connection.execute("""INSERT INTO ai_runs(mode,model_id,prompt_version,status,
                        requested_count,started_at) VALUES ('benchmark','test','test','paused',1,'now')""")
                    connection.commit()
                    self.assertEqual(client.post("/api/system/desktop/shutdown", headers=headers).status_code, 409)
                finally:
                    connection.close()
                control.shutdown.assert_not_called()
                self.assertFalse(control.draining)

    def test_shutdown_serializes_with_inflight_writes(self):
        with TemporaryDirectory() as temporary:
            config = configuration(Path(temporary))
            control = ServiceControl(config, 18876, shutdown=Mock())
            app = create_app(config, service_control=control)
            entered, release = Event(), Event()

            @app.post("/api/test-write")
            def slow_write():
                entered.set()
                self.assertTrue(release.wait(3))
                return {"saved": True}

            with TestClient(app, base_url="http://127.0.0.1") as client, ThreadPoolExecutor(2) as pool:
                session = client.get("/api/session").json()
                headers = {session["header"]: session["token"], CONTROL_HEADER: control.token}
                write = pool.submit(client.post, "/api/test-write", headers=headers)
                try:
                    self.assertTrue(entered.wait(2))
                    shutdown = pool.submit(client.post, "/api/system/desktop/shutdown", headers=headers)
                    self.assertFalse(control.draining)
                finally:
                    release.set()
                self.assertEqual(write.result().status_code, 200)
                self.assertEqual(shutdown.result().status_code, 200)

    def test_busy_legacy_or_stale_client_never_posts_shutdown(self):
        with TemporaryDirectory() as temporary:
            config = configuration(Path(temporary))
            client = ServiceClient(config, 18876)
            client.runtime = Path(temporary) / "runtime"
            health = {"desktop_control": True, "instance_id": "current"}
            with patch.object(client, "health", return_value=health), \
                    patch.object(client, "request", return_value={"status": "paused"}) as request:
                with self.assertRaises(DesktopError):
                    client.restart(Mock())
                self.assertEqual(request.call_count, 1)
            with patch.object(client, "health", return_value={"status": "ok"}), \
                    patch.object(client, "request") as request:
                with self.assertRaises(DesktopError):
                    client.restart(Mock())
                request.assert_not_called()
            client.runtime.mkdir()
            (client.runtime / "service.json").write_text(json.dumps({"instance_id": "stale", "token": "fake"}))
            with patch.object(client, "health", return_value=health), \
                    patch.object(client, "request", return_value={"status": "idle"}) as request:
                with self.assertRaises(DesktopError):
                    client.restart(Mock())
                self.assertEqual(request.call_count, 1)

    def test_existing_service_reuses_without_spawning_and_window_close_does_not_stop(self):
        with TemporaryDirectory() as temporary:
            config = configuration(Path(temporary))
            client = ServiceClient(config, 18876)
            client.runtime = Path(temporary) / "runtime"
            with patch.object(client, "health", return_value={"status": "ok"}), \
                    patch("tangerine_photo_assistant.desktop.subprocess.Popen") as spawn:
                self.assertEqual(client.ensure_running(Mock())["status"], "ok")
                spawn.assert_not_called()
            window = DesktopWindow(client)
            window.window = Mock()
            with patch.object(client, "restart") as restart:
                window.close()
                window.window.destroy.assert_called_once()
                restart.assert_not_called()
            self.assertNotIn("<script>", window.splash("<script>alert(1)</script>"))
            self.assertEqual(config_identity(config), config_identity(config.resolve()))


if __name__ == "__main__":
    unittest.main()
