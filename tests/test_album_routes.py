import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_webapp import settings_for

from tangerine_photo_assistant.album_routes import create_album_router
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.webapp import ScanTaskManager


class AlbumRouteTests(unittest.TestCase):
    def test_library_switch_routes_reads_and_writes_to_current_settings(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            libraries = []
            for name in ("first", "second"):
                (root / name).mkdir()
                settings = settings_for(root / name)
                connect(settings.database_path).close()
                libraries.append(settings)
            active = libraries[0]
            app = FastAPI()
            app.include_router(create_album_router(lambda: active, Mock()))
            with TestClient(app) as client:
                first = client.post("/api/albums", json={"name": "First", "category": "纪念"})
                self.assertEqual(first.status_code, 201)
                active = libraries[1]
                second = client.post("/api/albums", json={"name": "Second", "category": "纪念"})
                self.assertEqual(second.status_code, 201)
                self.assertEqual(
                    [a["proposed_name"] for a in client.get("/api/albums").json()["items"]],
                    ["Second"],
                )
                active = libraries[0]
                self.assertEqual(
                    [a["proposed_name"] for a in client.get("/api/albums").json()["items"]],
                    ["First"],
                )

    def test_archive_plan_for_another_album_never_starts_task(self):
        manager = Mock()
        app = FastAPI()
        app.include_router(create_album_router(lambda: Mock(), manager))
        with (
            TestClient(app) as client,
            patch(
                "tangerine_photo_assistant.album_routes.album_archive.load",
                return_value={"album_id": 2},
            ),
        ):
            response = client.post(
                "/api/albums/1/archive/execute",
                json={
                    "plan_id": "a" * 32,
                    "confirmation": "confirm",
                },
            )
        self.assertEqual(response.status_code, 409)
        manager.start_album_archive.assert_not_called()

    def test_preview_checks_task_state_before_reading_or_creating_plan(self):
        with TemporaryDirectory() as directory:
            settings = settings_for(Path(directory))
            connect(settings.database_path).close()
            manager = ScanTaskManager(settings)
            app = FastAPI()
            app.include_router(create_album_router(lambda: settings, manager))
            with (
                TestClient(app) as client,
                patch(
                    "tangerine_photo_assistant.webapp.album_archive.preview",
                    return_value={"album_id": 1},
                ) as preview,
            ):
                for status in ("running", "paused"):
                    manager._state.status = status
                    manager._state.stage = "scan"
                    self.assertEqual(client.post("/api/albums/1/archive/preview").status_code, 409)
                preview.assert_not_called()
                manager._state.stage = "album-archive"
                self.assertEqual(client.post("/api/albums/1/archive/preview").status_code, 200)
                preview.assert_called_once()
