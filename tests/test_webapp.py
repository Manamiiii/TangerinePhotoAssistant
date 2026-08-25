import unittest
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from time import sleep
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from tangerine_photo_assistant.albums import assign_captures_to_album
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.lightroom import build_lightroom_rows
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.settings import Settings, write_safe_config
from tangerine_photo_assistant.structure import rebuild_structure
from tangerine_photo_assistant.tags import update_manual_tag_for_captures
from tangerine_photo_assistant.visual import (
    build_visual_fingerprints,
    rebuild_similarity_groups,
)
from tangerine_photo_assistant.webapp import (
    AiStartRequest,
    ScanStartRequest,
    ScanTaskManager,
    SimilarityGroupEditRequest,
    _open_file,
    _pick_directory,
    _query_analysis_overview,
    _query_bursts,
    _query_duplicates,
    _query_events,
    _query_inbox,
    _query_library_captures,
    _query_library_filters,
    _query_overview,
    _query_quality,
    _query_similarity_group,
    _query_similarity_groups,
    _reveal_file,
    _runtime_capabilities,
    create_app,
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
    def test_browser_writes_require_same_origin_session_token(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            config_path = root / "config.toml"
            write_safe_config(
                config_path, settings.originals, settings.workspace, settings.cache_root
            )
            with TestClient(create_app(config_path), base_url="http://localhost") as client:
                session_response = client.get("/api/session")
                self.assertEqual(session_response.headers["cache-control"], "no-store")
                session = session_response.json()
                self.assertEqual(
                    client.get("/api/system/ai-audit-backfill").json()["status"],
                    "complete",
                )
                self.assertEqual(
                    client.post(
                        "/api/system/ai-audit-backfill/retry",
                        headers={session["header"]: session["token"]},
                    ).status_code,
                    202,
                )
                self.assertEqual(
                    client.post("/api/tasks/current/cancel").status_code, 403
                )
                self.assertEqual(
                    client.post(
                        "/api/tasks/current/cancel",
                        headers={
                            session["header"]: session["token"],
                            "Origin": "https://attacker.example",
                        },
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    client.post(
                        "/api/tasks/current/cancel",
                        headers={
                            session["header"]: session["token"],
                            "Origin": "http://localhost",
                        },
                    ).status_code,
                    409,
                )
                self.assertEqual(
                    client.get("/api/health", headers={"Host": "attacker.example"}).status_code,
                    400,
                )

    def test_confirming_quality_work_item_removes_it_from_open_queue(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            config_path = root / "config.toml"
            write_safe_config(
                config_path, settings.originals, settings.workspace, settings.cache_root
            )
            with TestClient(create_app(config_path), base_url="http://localhost") as client:
                session = client.get("/api/session").json()
                connection = connect(settings.database_path)
                connection.execute(
                    "INSERT INTO scan_runs(id,started_at,root_path,status) VALUES (1,'now','TEST','complete')"
                )
                connection.execute(
                    """INSERT INTO files(
                           id,path,relative_path,parent_relative,file_name,stem,extension,
                           media_kind,size_bytes,modified_ns,first_seen_run_id,last_seen_run_id
                       ) VALUES (1,'TEST:a.jpg','a.jpg','','a.jpg','a','.jpg','jpeg',1,1,1,1)"""
                )
                connection.execute(
                    "INSERT INTO captures(id,capture_key,parent_relative,stem,pairing_status) VALUES (1,'a','','a','jpeg_only')"
                )
                connection.execute("INSERT INTO capture_files VALUES (1,1,'jpeg')")
                connection.execute(
                    """INSERT INTO quality_metrics(
                           capture_id,source_file_id,algorithm_version,technical_score,
                           issue_json,size_bytes,modified_ns,computed_at
                       ) VALUES (1,1,'v1',60,'[{"code":"blur","severity":"medium","message":"需复核"}]',1,1,'now')"""
                )
                connection.commit()
                connection.close()

                response = client.put(
                    "/api/work-items/quality/1",
                    headers={session["header"]: session["token"]},
                    json={"status": "confirmed"},
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], "confirmed")
                page = client.get(
                    "/api/quality?review_filter=problems&workflow_filter=open"
                ).json()
                self.assertEqual(page["count"], 0)

    def test_integrity_investigation_endpoint_converges_latest_difference(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            config_path = root / "config.toml"
            write_safe_config(
                config_path, settings.originals, settings.workspace, settings.cache_root
            )
            with TestClient(create_app(config_path), base_url="http://localhost") as client:
                session = client.get("/api/session").json()
                connection = connect(settings.database_path)
                connection.execute(
                    """INSERT INTO archive_baselines(
                           id,name,created_at,file_count,total_bytes,scope,root_path
                       ) VALUES (1,'test','2026-01-01T00:00:00+00:00',1,1,'active','TEST')"""
                )
                connection.execute(
                    """INSERT INTO archive_checks(
                           id,baseline_id,scan_run_id,checked_at,missing_count,
                           changed_count,new_count,healthy,sample_json
                       ) VALUES (1,1,NULL,'2026-01-02T00:00:00+00:00',1,0,0,0,'[]')"""
                )
                connection.execute(
                    "INSERT INTO archive_check_differences VALUES (1,'album/a.jpg','missing')"
                )
                connection.commit()
                connection.close()

                response = client.put(
                    "/api/integrity/investigations",
                    headers={session["header"]: session["token"]},
                    json={
                        "scope": "active",
                        "relative_path": "album/a.jpg",
                        "status": "confirmed",
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    client.get(
                        "/api/integrity/differences/active?workflow=open"
                    ).json()["count"],
                    0,
                )
                self.assertEqual(
                    client.get(
                        "/api/integrity/differences/active?workflow=confirmed"
                    ).json()["count"],
                    1,
                )

    def test_windows_file_actions_only_delegate_to_desktop_shell(self) -> None:
        source = Path(r"D:\Photos\sample.jpg")
        with patch("tangerine_photo_assistant.webapp.os.name", "nt"), patch(
            "tangerine_photo_assistant.webapp.os.startfile", create=True
        ) as startfile, patch("tangerine_photo_assistant.webapp.subprocess.Popen") as popen:
            _open_file(source)
            _reveal_file(source)
        startfile.assert_called_once_with(source)
        popen.assert_called_once_with(["explorer.exe", f"/select,{source}"])

    def test_directory_picker_returns_existing_selection_without_writing(self) -> None:
        with TemporaryDirectory() as directory:
            selected = Path(directory).resolve()
            with patch(
                "tangerine_photo_assistant.webapp._directory_picker_command",
                return_value=(["picker"], "zenity"),
            ), patch(
                "tangerine_photo_assistant.webapp.subprocess.run",
                return_value=CompletedProcess(["picker"], 0, f"{selected}\n", ""),
            ) as run:
                self.assertEqual(_pick_directory(str(selected), "选择照片目录"), selected)
            self.assertIn("--title", run.call_args.args[0])
            self.assertTrue(selected.is_dir())

    def test_empty_catalog_keeps_shared_collection_shapes(self) -> None:
        with TemporaryDirectory() as directory:
            settings = settings_for(Path(directory))
            connection = connect(settings.database_path)
            connection.close()

            library = _query_library_captures(settings, 20, 0)
            quality = _query_quality(settings, 20, 0)
            similarity = _query_similarity_groups(settings, 20, 0)
            albums = _query_events(settings, 20, 0)

            self.assertEqual(library["count"], 0)
            self.assertEqual(library["items"], [])
            self.assertEqual(quality["count"], 0)
            self.assertEqual(quality["items"], [])
            self.assertEqual(quality["albums"], [])
            self.assertEqual(similarity["count"], 0)
            self.assertEqual(similarity["items"], [])
            self.assertEqual(similarity["albums"], [])
            self.assertEqual(similarity["pending_count"], 0)
            self.assertEqual(albums["count"], 0)
            self.assertEqual(albums["items"], [])

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
            assigned = assign_captures_to_album(connection, album_id, [1])
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

            page = _query_library_captures(settings, 2, 1, sort="name")
            self.assertEqual(page["count"], 4)
            self.assertEqual(page["limit"], 2)
            self.assertEqual(page["offset"], 1)
            self.assertEqual(
                [item["stem"] for item in page["items"]],
                ["DSCF0002", "DSCF0003"],
            )
            self.assertEqual(
                _query_library_captures(
                    settings, 20, 0, album_id=album_id + 1000
                )["items"],
                [],
            )

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

            update_manual_tag_for_captures(
                connection, [low_id], dimension="subject", name="人像", action="add"
            )
            update_manual_tag_for_captures(
                connection, [high_id], dimension="subject", name="风景", action="add"
            )

            problems = _query_library_captures(settings, 20, 0, quality="problems")
            self.assertEqual([item["id"] for item in problems["items"]], [low_id])
            low = _query_library_captures(settings, 20, 0, quality="low")
            self.assertEqual([item["id"] for item in low["items"]], [low_id])
            high = _query_library_captures(settings, 20, 0, quality="high")
            self.assertEqual([item["id"] for item in high["items"]], [high_id])
            unanalyzed = _query_library_captures(settings, 20, 0, quality="unanalyzed")
            self.assertEqual(unanalyzed["count"], 1)
            portraits = _query_library_captures(
                settings, 20, 0, tag_subject="人像"
            )
            self.assertEqual([item["id"] for item in portraits["items"]], [low_id])
            connection.execute(
                """INSERT INTO capture_reviews(
                       capture_id, user_pick, user_reject, selection_reason_json, updated_at
                   ) VALUES (?, 1, 0, '["构图差异"]', CURRENT_TIMESTAMP)
                   ON CONFLICT(capture_id) DO UPDATE SET
                       user_pick=1, user_reject=0,
                       selection_reason_json=excluded.selection_reason_json""",
                (high_id,),
            )
            connection.commit()
            composition_pick = _query_library_captures(
                settings, 20, 0, selection_reason="构图差异"
            )
            self.assertEqual(
                [item["id"] for item in composition_pick["items"]], [high_id]
            )
            connection.execute("DELETE FROM capture_reviews WHERE capture_id=?", (high_id,))
            connection.commit()
            tag_filters = _query_library_filters(settings)["tags"]
            self.assertEqual(
                {(tag["dimension"], tag["name"], tag["capture_count"]) for tag in tag_filters},
                {("subject", "人像", 1), ("subject", "风景", 1)},
            )

            groups = _query_similarity_groups(settings, 20, 0)
            self.assertEqual(groups["pending_count"], 1)
            self.assertEqual(groups["items"][0]["review_status"], "pending")
            group_detail = _query_similarity_group(settings, groups["items"][0]["id"])
            self.assertEqual(group_detail["capture_count"], 3)
            self.assertEqual(len(group_detail["items"]), 3)
            scored_items = [
                item for item in group_detail["items"] if item["technical_score"] is not None
            ]
            recommended = max(scored_items, key=lambda item: item["technical_score"])
            self.assertIn("组内技术健康度最高", recommended["recommendation_reason"])
            self.assertEqual(recommended["recommendation_tier"], "best")
            self.assertTrue(all("recommendation_reason" in item for item in group_detail["items"]))
            self.assertTrue(all("balanced_rank" in item for item in group_detail["items"]))
            self.assertTrue(all("visual_difference" in item for item in group_detail["items"]))
            low_ranked = next(item for item in scored_items if item["capture_id"] == low_id)
            self.assertEqual(low_ranked["recommendation_tier"], "weak")
            self.assertTrue(all(
                item["thumbnail_url"].endswith("?size=640")
                for item in group_detail["items"]
            ))
            with self.assertRaisesRegex(ValueError, "相似组不存在"):
                _query_similarity_group(settings, groups["items"][0]["id"] + 1000)
            album_id = groups["items"][0]["event_id"]
            self.assertEqual(groups["albums"][0]["id"], album_id)
            self.assertEqual(groups["albums"][0]["pending_count"], 1)
            album_quality = _query_quality(settings, 20, 0, album_id=album_id)
            self.assertEqual(album_quality["count"], 2)
            self.assertEqual(album_quality["albums"][0]["id"], album_id)
            self.assertEqual(album_quality["albums"][0]["analyzed_count"], 2)
            self.assertEqual(album_quality["albums"][0]["problem_count"], 1)
            problem_page = _query_quality(
                settings, 1, 0, review_filter="problems", album_id=album_id
            )
            self.assertEqual(problem_page["count"], 1)
            self.assertEqual([item["capture_id"] for item in problem_page["items"]], [low_id])
            second_page = _query_quality(settings, 1, 1, album_id=album_id)
            self.assertEqual(second_page["count"], 2)
            self.assertEqual(second_page["limit"], 1)
            self.assertEqual(second_page["offset"], 1)
            self.assertEqual(len(second_page["items"]), 1)
            searched_quality = _query_quality(
                settings, 20, 0, search="DSCF0102", album_id=album_id
            )
            self.assertEqual(
                [item["capture_id"] for item in searched_quality["items"]], [high_id]
            )
            self.assertEqual(
                _query_quality(settings, 20, 0, album_id=album_id + 1000)["items"],
                [],
            )
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
            (source / "DSCF0201.RAF").write_bytes(b"raw-fixture")
            (source / "DSCF0201.xmp").write_text("<x:xmpmeta xmlns:x='adobe:ns:meta/'>", encoding="utf-8")
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
            update_manual_tag_for_captures(
                connection, [capture_ids[0]], dimension="subject", name="风景", action="add"
            )
            all_rows = build_lightroom_rows(connection, "all")
            self.assertEqual(len(all_rows), 2)
            raw_row = next(row for row in all_rows if row["raw_path"])
            self.assertEqual(raw_row["metadata_target"], "raw_xmp_sidecar")
            self.assertEqual(raw_row["xmp_exists"], 1)
            self.assertEqual(raw_row["requires_conflict_review"], 1)
            self.assertEqual(raw_row["write_xmp"], 0)
            self.assertIn("风景", raw_row["keywords"])
            self.assertEqual(len(build_lightroom_rows(connection, "picked")), 1)
            self.assertEqual(len(build_lightroom_rows(connection, "rated")), 1)
            self.assertEqual(len(build_lightroom_rows(connection, "album", album_id)), 2)
            connection.close()


if __name__ == "__main__":
    unittest.main()
