import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

from PIL import Image
from pydantic import ValidationError

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.lightroom import build_lightroom_rows
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.settings import Settings, write_safe_config
from tangerine_photo_assistant.structure import rebuild_structure
from tangerine_photo_assistant.visual import (
    build_visual_fingerprints,
    rebuild_similarity_groups,
)
from tangerine_photo_assistant.webapp import (
    AiStartRequest,
    ScanStartRequest,
    ScanTaskManager,
    SimilarityGroupEditRequest,
    _assign_captures_to_album,
    _query_analysis_overview,
    _query_bursts,
    _query_duplicates,
    _query_events,
    _query_inbox,
    _query_library_captures,
    _query_library_filters,
    _query_overview,
    _runtime_capabilities,
    create_app,
    _query_quality,
    _query_similarity_groups,
)


def settings_for(root: Path) -> Settings:
    originals = root / "originals"
    originals.mkdir()
    return Settings(
        originals=originals,
        workspace=root / "workspace",
        cache_root=root / "cache",
        cache_max_size_gb=40,
        offline_only=True,
        read_only=True,
        allow_move=False,
        allow_delete=False,
        allow_original_metadata_write=False,
        raw_extensions=(".raf",),
        exiftool=None,
        metadata_batch_size=8,
        burst_time_gap_seconds=3.0,
    )


class WebAppQueryTests(unittest.TestCase):
    def test_ai_batch_request_has_safe_bounds(self) -> None:
        request = AiStartRequest(mode="benchmark", limit=10)
        self.assertEqual(request.limit, 10)
        with self.assertRaises(ValidationError):
            AiStartRequest(mode="benchmark", limit=0)
        with self.assertRaises(ValidationError):
            AiStartRequest(mode="benchmark", limit=5001)
        with self.assertRaises(ValidationError):
            AiStartRequest(mode="unsupported", limit=10)
        with self.assertRaises(ValidationError):
            ScanStartRequest(album_id=0)
        request = SimilarityGroupEditRequest(
            source_group_id=1, groups=[], excluded_ids=[1, 2]
        )
        self.assertEqual(request.excluded_ids, [1, 2])

    def test_overview_and_inbox_use_real_catalog_data(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            event = settings.originals / "待整理" / "2026-08-06_测试"
            event.mkdir(parents=True)
            (event / "DSCF0001.JPG").write_bytes(b"jpeg")
            (event / "DSCF0001.RAF").write_bytes(b"raw")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            connection.close()

            overview = _query_overview(settings)
            inbox = _query_inbox(settings, 10)
            library = _query_library_captures(settings, 10, 0)
            filtered_library = _query_library_captures(
                settings, 10, 0, category="旅行", search="DSCF0001"
            )
            empty_library = _query_library_captures(
                settings, 10, 0, category="宠物"
            )
            unassigned_library = _query_library_captures(
                settings, 10, 0, unassigned_only=True
            )
            library_filters = _query_library_filters(settings)
            events = _query_events(settings, 10, 0)
            bursts = _query_bursts(settings, 10, 0)
            duplicates = _query_duplicates(settings, 10, 0)
            analysis = _query_analysis_overview(settings)
            quality = _query_quality(settings, 10, 0)

            self.assertEqual(overview["files"]["count"], 2)
            self.assertEqual(overview["capture_total"], 1)
            self.assertEqual(inbox["count"], 1)
            self.assertEqual(inbox["items"][0]["pairing_status"], "paired")
            self.assertEqual(library["count"], 1)
            self.assertEqual(library["items"][0]["thumbnail_url"], "/api/thumbnails/1?size=640")
            self.assertEqual(filtered_library["count"], 1)
            self.assertEqual(empty_library["count"], 0)
            self.assertEqual(unassigned_library["count"], 0)
            self.assertIn("旅行", {item["name"] for item in library_filters["album_types"]})
            self.assertEqual(library_filters["albums"][0]["capture_count"], 1)
            self.assertEqual(events["count"], 1)
            self.assertEqual(events["items"][0]["category"], "旅行")
            self.assertEqual(bursts["count"], 0)
            self.assertEqual(overview["visual"]["fingerprint_count"], 0)
            self.assertEqual(duplicates["count"], 0)
            self.assertEqual(analysis["quality"]["analyzed"], 0)
            self.assertFalse(analysis["runtime"]["ready"])
            self.assertEqual(quality["count"], 0)

            capabilities = _runtime_capabilities(settings)
            self.assertEqual(capabilities["metadata"]["level"], "basic")
            self.assertTrue(capabilities["safety"]["offline_only"])
            self.assertTrue(capabilities["safety"]["library_read_only"])
            self.assertFalse(capabilities["safety"]["allow_delete"])
            self.assertEqual(capabilities["library_root"], str(settings.originals))

    def test_capture_assignment_uses_album_as_the_working_dimension(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            source = settings.originals / "待整理" / "2026-08-10_测试"
            source.mkdir(parents=True)
            (source / "DSCF0001.JPG").write_bytes(b"jpeg")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            connection.execute(
                """INSERT INTO events(
                       event_key, proposed_name, category, capture_count, status,
                       confidence, reason_json, created_at, updated_at
                   ) VALUES ('manual:test', '测试相册', '日常', 0, 'confirmed',
                             1.0, '{}', '2026-08-10', '2026-08-10')"""
            )
            album_id = connection.execute(
                "SELECT id FROM events WHERE event_key='manual:test'"
            ).fetchone()[0]
            assigned = _assign_captures_to_album(connection, album_id, [1])
            membership = connection.execute(
                "SELECT event_id FROM event_captures WHERE capture_id=1"
            ).fetchone()[0]
            album_count = connection.execute(
                "SELECT capture_count FROM events WHERE id=?", (album_id,)
            ).fetchone()[0]
            connection.close()
            self.assertEqual(assigned, 1)
            self.assertEqual(membership, album_id)
            self.assertEqual(album_count, 1)

    def test_scan_assigns_only_new_photos_to_the_selected_album(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            source = settings.originals / "待整理"
            source.mkdir(parents=True)
            Image.new("RGB", (32, 24), "orange").save(source / "existing.JPG")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            connection.execute(
                """INSERT INTO events(
                       event_key, proposed_name, category, capture_count, status,
                       confidence, reason_json, created_at, updated_at
                   ) VALUES ('manual:scan-target', '本次相册', '日常', 0, 'confirmed',
                             1.0, '{}', '2026-08-10', '2026-08-10')"""
            )
            album_id = connection.execute(
                "SELECT id FROM events WHERE event_key='manual:scan-target'"
            ).fetchone()[0]
            connection.commit()
            connection.close()

            Image.new("RGB", (32, 24), "green").save(source / "new.JPG")
            manager = ScanTaskManager(settings)
            manager.start(album_id)
            for _ in range(200):
                state = manager.snapshot()
                if state["status"] != "running":
                    break
                sleep(0.02)
            self.assertEqual(state["status"], "complete", state)
            self.assertEqual(state["result"]["assigned_count"], 1)

            connection = connect(settings.database_path)
            members = connection.execute(
                """SELECT c.stem FROM event_captures ec
                   JOIN captures c ON c.id=ec.capture_id
                   WHERE ec.event_id=? ORDER BY c.stem""",
                (album_id,),
            ).fetchall()
            connection.close()
            self.assertEqual([row[0] for row in members], ["new"])

    def test_album_feed_collapses_similarity_groups_and_keeps_single_photos(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            source = settings.originals / "2026-08-11_折叠测试"
            source.mkdir(parents=True)
            for stem in ("DSCF0001", "DSCF0002", "DSCF0003", "DSCF0010"):
                Image.new("RGB", (48, 32), "orange").save(source / f"{stem}.JPG")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            for stem, second in (("DSCF0001", 1), ("DSCF0002", 2), ("DSCF0003", 3), ("DSCF0010", 10)):
                connection.execute(
                    "UPDATE files SET captured_at=? WHERE stem=?",
                    (f"2026-08-11T10:00:{second:02d}", stem),
                )
            connection.commit()
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            build_visual_fingerprints(connection)
            rebuild_similarity_groups(connection)
            album_id = connection.execute("SELECT id FROM events LIMIT 1").fetchone()[0]
            picked_id = connection.execute(
                "SELECT id FROM captures WHERE stem='DSCF0002'"
            ).fetchone()[0]
            single_id = connection.execute(
                "SELECT id FROM captures WHERE stem='DSCF0010'"
            ).fetchone()[0]
            connection.executemany(
                """INSERT INTO capture_reviews(
                       capture_id, user_pick, user_reject, updated_at
                   ) VALUES (?, 1, 0, 'now')""",
                ((picked_id,), (single_id,)),
            )
            connection.commit()
            connection.close()

            collapsed = _query_library_captures(
                settings, 20, 0, album_id=album_id, collapse_groups=True
            )
            self.assertTrue(collapsed["collapsed"])
            self.assertEqual(collapsed["count"], 2)
            group = next(item for item in collapsed["items"] if item["item_type"] == "group")
            single = next(item for item in collapsed["items"] if item["item_type"] == "photo")
            self.assertEqual(group["id"], picked_id)
            self.assertEqual(group["group_pick_count"], 1)
            self.assertEqual(len(group["selection_capture_ids"]), 3)
            self.assertIn(picked_id, group["selection_capture_ids"])
            self.assertGreater(group["size_bytes"], single["size_bytes"])
            self.assertEqual(single["id"], single_id)

            picked = _query_library_captures(
                settings, 20, 0, album_id=album_id,
                selection="picked", collapse_groups=True,
            )
            self.assertEqual(picked["count"], 2)

    def test_quality_filter_and_similarity_review_progress(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            source = settings.originals / "2026-08-12_质量筛选"
            source.mkdir(parents=True)
            for stem in ("DSCF0101", "DSCF0102", "DSCF0103"):
                Image.new("RGB", (48, 32), "orange").save(source / f"{stem}.JPG")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            for stem, second in (("DSCF0101", 1), ("DSCF0102", 2), ("DSCF0103", 3)):
                connection.execute(
                    "UPDATE files SET captured_at=? WHERE stem=?",
                    (f"2026-08-12T09:00:{second:02d}", stem),
                )
            connection.commit()
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            build_visual_fingerprints(connection)
            rebuild_similarity_groups(connection)
            low_id, high_id = (
                connection.execute(
                    "SELECT id FROM captures WHERE stem=?", (stem,)
                ).fetchone()[0]
                for stem in ("DSCF0101", "DSCF0102")
            )
            connection.executemany(
                """INSERT INTO quality_metrics(
                       capture_id, source_file_id, algorithm_version, technical_score,
                       issue_json, size_bytes, modified_ns, computed_at
                   ) VALUES (?, (SELECT file_id FROM capture_files WHERE capture_id=?),
                             'test', ?, ?, 1, 1, 'now')""",
                (
                    (low_id, low_id, 55.0, '[{"code": "soft_focus"}]'),
                    (high_id, high_id, 92.0, "[]"),
                ),
            )
            connection.commit()

            problems = _query_library_captures(settings, 20, 0, quality="problems")
            self.assertEqual([item["id"] for item in problems["items"]], [low_id])
            low = _query_library_captures(settings, 20, 0, quality="low")
            self.assertEqual([item["id"] for item in low["items"]], [low_id])
            high = _query_library_captures(settings, 20, 0, quality="high")
            self.assertEqual([item["id"] for item in high["items"]], [high_id])
            unanalyzed = _query_library_captures(settings, 20, 0, quality="unanalyzed")
            self.assertEqual(unanalyzed["count"], 1)

            groups = _query_similarity_groups(settings, 20, 0)
            self.assertEqual(groups["pending_count"], 1)
            self.assertEqual(groups["items"][0]["review_status"], "pending")
            album_id = groups["items"][0]["event_id"]
            self.assertEqual(groups["albums"][0]["id"], album_id)
            self.assertEqual(groups["albums"][0]["pending_count"], 1)
            album_groups = _query_similarity_groups(
                settings, 20, 0, album_id=album_id
            )
            self.assertEqual(album_groups["total_count"], 1)
            self.assertEqual(album_groups["items"][0]["event_id"], album_id)
            self.assertEqual(
                _query_similarity_groups(settings, 20, 0, album_id=album_id + 1000)[
                    "items"
                ],
                [],
            )
            connection.execute(
                """INSERT INTO capture_reviews(capture_id, user_pick, user_reject, updated_at)
                   VALUES (?, 0, 1, 'now')""",
                (low_id,),
            )
            connection.commit()
            partially_rejected = _query_similarity_groups(settings, 20, 0)
            self.assertEqual(partially_rejected["pending_count"], 1)
            self.assertEqual(partially_rejected["items"][0]["review_status"], "pending")
            connection.execute(
                """INSERT INTO capture_reviews(capture_id, user_pick, user_reject, updated_at)
                   VALUES (?, 1, 0, 'now')""",
                (high_id,),
            )
            connection.execute(
                """INSERT INTO similarity_group_overrides(
                       capture_id, action, created_at, updated_at
                   ) VALUES (?, 'exclude', 'now', 'now')""",
                (low_id,),
            )
            connection.commit()
            connection.close()
            groups = _query_similarity_groups(settings, 20, 0)
            self.assertEqual(groups["pending_count"], 0)
            self.assertEqual(groups["items"][0]["review_status"], "picked")
            self.assertEqual(groups["items"][0]["pick_count"], 1)
            pending_only = _query_similarity_groups(settings, 20, 0, review_filter="pending")
            self.assertEqual(pending_only["count"], 0)
            self.assertEqual(pending_only["items"], [])
            self.assertEqual(pending_only["total_count"], 1)
            completed_only = _query_similarity_groups(
                settings, 20, 0, review_filter="completed"
            )
            self.assertEqual(completed_only["count"], 1)
            self.assertEqual(completed_only["items"][0]["review_status"], "picked")
            adjusted_only = _query_similarity_groups(
                settings, 20, 0, review_filter="adjusted"
            )
            self.assertEqual(adjusted_only["count"], 1)
            config_path = root / "config.toml"
            write_safe_config(
                config_path, settings.originals, settings.workspace, settings.cache_root
            )
            operation = create_app(config_path).openapi()["paths"][
                "/api/similarity-groups"
            ]["get"]
            review_parameter = next(
                item for item in operation["parameters"] if item["name"] == "review_filter"
            )
            self.assertEqual(
                set(review_parameter["schema"]["enum"]),
                {"all", "pending", "completed", "adjusted"},
            )

    def test_lightroom_manifest_scope_is_explicit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            source = settings.originals / "2026-08-13_清单范围"
            source.mkdir(parents=True)
            for stem in ("DSCF0201", "DSCF0202"):
                Image.new("RGB", (48, 32), "orange").save(source / f"{stem}.JPG")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            connection.execute("UPDATE files SET captured_at='2026-08-13T10:00:00'")
            connection.commit()
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            capture_ids = [
                row[0] for row in connection.execute("SELECT id FROM captures ORDER BY id")
            ]
            connection.executemany(
                """INSERT INTO capture_reviews(
                       capture_id, user_rating, user_pick, user_reject, updated_at
                   ) VALUES (?, ?, ?, 0, 'now')""",
                ((capture_ids[0], None, 1), (capture_ids[1], 4, 0)),
            )
            connection.commit()
            album_id = connection.execute("SELECT id FROM events LIMIT 1").fetchone()[0]
            self.assertEqual(len(build_lightroom_rows(connection, "all")), 2)
            self.assertEqual(len(build_lightroom_rows(connection, "picked")), 1)
            self.assertEqual(len(build_lightroom_rows(connection, "rated")), 1)
            self.assertEqual(len(build_lightroom_rows(connection, "album", album_id)), 2)
            connection.close()


if __name__ == "__main__":
    unittest.main()
