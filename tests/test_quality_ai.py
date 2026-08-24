import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from tangerine_photo_assistant.ai_analysis import (
    PROMPT_VERSION,
    _balanced_benchmark_candidates,
    _format_exposure_seconds,
    ai_result_audit,
    ai_results_page,
    ai_summary,
    backfill_ai_audit_metadata,
    create_ai_failure_retry_run,
    create_ai_run,
    model_result_audit_metadata,
    parse_model_json,
    quality_summary,
    recover_interrupted_ai_runs,
    resume_ai_run,
    update_ai_review,
    validate_model_result,
    write_ai_run_report,
)
from tangerine_photo_assistant.ai_worker import _apply_control_request
from tangerine_photo_assistant.archive import (
    compare_archive_baseline,
    create_archive_baseline,
    integrity_differences,
    recorded_archive_status,
    run_integrity_check,
)
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.lightroom import (
    build_lightroom_rows,
    lightroom_status,
    write_lightroom_manifest,
)
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.quality import (
    analyze_quality,
    backfill_histograms,
    measure_image,
    measure_luminance_histogram,
)
from tangerine_photo_assistant.queries.library import (
    query_library_captures,
    query_library_filters,
)
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.statistics import build_statistics
from tangerine_photo_assistant.structure import rebuild_structure
from tangerine_photo_assistant.thumbnails import ThumbnailCache
from tangerine_photo_assistant.visual import build_visual_fingerprints, rebuild_similarity_groups
from tangerine_photo_assistant.webapp import (
    ScanTaskManager,
    _query_capture_detail,
    _query_similarity_group,
    _query_similarity_groups,
)


def settings_for(root: Path) -> Settings:
    originals = root / "originals"
    originals.mkdir()
    model = root / "model"
    model.mkdir()
    python = root / "python.exe"
    python.write_bytes(b"")
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
        ai_model_path=model,
        ai_python=python,
    )


def photo(path: Path, offset: int, brightness: int = 90) -> None:
    image = Image.new("RGB", (320, 240), (brightness, brightness, brightness))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40 + offset, 30, 190 + offset, 210), fill=(235, 215, 180))
    draw.line((0, 0, 319, 239), fill=(10, 10, 10), width=5)
    image.save(path, quality=95)


class QualityAndAiTests(unittest.TestCase):
    def test_task_manager_reattaches_running_ai_worker(self) -> None:
        with TemporaryDirectory() as directory:
            settings = settings_for(Path(directory))
            connection = connect(settings.database_path)
            cursor = connection.execute(
                """
                INSERT INTO ai_runs(
                    mode, model_id, prompt_version, status, requested_count,
                    completed_count, failed_count, started_at, worker_pid, heartbeat_at
                ) VALUES ('benchmark', 'model@int8', 'test', 'running', 3,
                          1, 0, ?, ?, ?)
                """,
                ("2026-08-10T00:00:00+00:00", os.getpid(), "2026-08-10T00:00:00+00:00"),
            )
            run_id = int(cursor.lastrowid)
            connection.commit()
            manager = ScanTaskManager(settings)
            manager.attach_ai_run(run_id)
            self.assertEqual(manager.snapshot()["status"], "running")
            connection.execute(
                "UPDATE ai_runs SET status='complete', completed_count=3, "
                "finished_at=?, worker_pid=NULL WHERE id=?",
                ("2026-08-10T00:01:00+00:00", run_id),
            )
            connection.commit()
            connection.close()
            deadline = time.monotonic() + 3
            while manager.snapshot()["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(manager.snapshot()["status"], "complete")

    def test_benchmark_selection_rotates_events_and_similarity_groups(self) -> None:
        rows = [
            {"category": "人像", "event_id": 1, "similarity_group_id": 10, "id": 1},
            {"category": "人像", "event_id": 1, "similarity_group_id": 10, "id": 2},
            {"category": "人像", "event_id": 2, "similarity_group_id": 20, "id": 3},
            {"category": "风景", "event_id": 3, "similarity_group_id": 30, "id": 4},
        ]
        selected = _balanced_benchmark_candidates(rows, 3)  # type: ignore[arg-type]
        self.assertEqual({row["event_id"] for row in selected}, {1, 2, 3})
        self.assertEqual(len({row["similarity_group_id"] for row in selected}), 3)

    def test_quality_metrics_and_group_pick_are_persisted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            event = settings.originals / "MyPhoto" / "宝贝" / "2026.8.6_测试"
            event.mkdir(parents=True)
            for index in range(3):
                photo(event / f"DSCF{index + 1:04d}.JPG", index)
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            for index in range(3):
                connection.execute(
                    "UPDATE files SET captured_at=?, exposure_time=?, iso=?, focal_length_35mm=?, camera_model=? "
                    "WHERE stem=?",
                    (f"2026-08-06T10:00:0{index}", 1 / 250, 400, 35, "X-Test", f"DSCF{index + 1:04d}"),
                )
            connection.commit()
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            build_visual_fingerprints(connection)
            rebuild_similarity_groups(connection, max_hamming=64, max_color_distance=765)

            result = analyze_quality(connection)
            summary = quality_summary(connection)
            self.assertEqual(result["quality_errors"], 0)
            self.assertEqual(result["quality_updated"], 3)
            self.assertEqual(summary["analyzed"], 3)
            self.assertGreaterEqual(summary["recommended_picks"], 1)
            self.assertTrue(all(0 <= row[0] <= 100 for row in connection.execute(
                "SELECT technical_score FROM quality_metrics"
            )))
            scores_before = connection.execute(
                "SELECT capture_id, technical_score FROM quality_metrics ORDER BY capture_id"
            ).fetchall()
            connection.execute("UPDATE quality_metrics SET histogram_json=NULL")
            histogram_result = backfill_histograms(connection)
            scores_after = connection.execute(
                "SELECT capture_id, technical_score FROM quality_metrics ORDER BY capture_id"
            ).fetchall()
            self.assertEqual(histogram_result["histograms_updated"], 3)
            self.assertEqual([tuple(row) for row in scores_before], [tuple(row) for row in scores_after])

            run = create_ai_run(
                connection, settings.ai_model_path, "benchmark", 2, "int8"
            )
            self.assertEqual(run["requested_count"], 2)
            self.assertEqual(connection.execute(
                "SELECT model_id FROM ai_runs WHERE id=?", (run["run_id"],)
            ).fetchone()[0], "model@int8")
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM ai_analyses WHERE run_id=?", (run["run_id"],)
            ).fetchone()[0], 2)
            analysis_ids = connection.execute(
                "SELECT id FROM ai_analyses WHERE run_id=? ORDER BY id", (run["run_id"],)
            ).fetchall()
            model_result = {
                "subject_type": "风景", "quality_summary": "测试结果",
                "visible_problems": [{
                    "name": "天空高光略亮", "evidence": "亮部接近上限",
                    "severity": "low", "confidence": 0.75,
                }],
                "shooting_advice": [{
                    "suggestion": "拍摄时减少三分之一档曝光补偿", "reason": "避免细节损失",
                    "exif_basis": "曝光补偿 0 EV",
                }],
                "lightroom_suggestions": [{
                    "adjustment": "高光", "direction": "降低",
                    "reason": "恢复天空层次",
                }], "photoshop_needed": False,
                "photoshop_reason": "不需要", "overall_confidence": 0.8,
            }
            low_confidence_result = {**model_result, "overall_confidence": 0.2}
            self.assertIn(
                "low_confidence",
                json.loads(model_result_audit_metadata(low_confidence_result)["flags_json"]),
            )
            connection.execute(
                "UPDATE ai_analyses SET status='complete', result_json=?, started_at=?, finished_at=? WHERE id=?",
                (
                    json.dumps(model_result, ensure_ascii=False),
                    "2026-08-08T10:00:00+00:00",
                    "2026-08-08T10:00:10+00:00",
                    analysis_ids[0][0],
                ),
            )
            connection.execute(
                "UPDATE ai_analyses SET status='failed', started_at=?, finished_at=? WHERE id=?",
                (
                    "2026-08-08T10:01:00+00:00",
                    "2026-08-08T10:01:20+00:00",
                    analysis_ids[1][0],
                ),
            )
            connection.execute(
                "UPDATE ai_runs SET status='failed', completed_count=1, failed_count=1 WHERE id=?",
                (run["run_id"],),
            )
            connection.commit()
            self.assertEqual(backfill_ai_audit_metadata(connection), 1)
            summary = ai_summary(connection, settings.ai_model_path, "int8")
            self.assertEqual(summary["analyzed_capture_count"], 1)
            self.assertAlmostEqual(
                summary["latest_run"]["average_seconds_per_photo"], 15.0, places=1
            )
            self.assertEqual(summary["latest_run"]["success_rate"], 50.0)
            self.assertEqual(len(summary["recent_results"]), 1)
            self.assertEqual(summary["recent_results"][0]["quality_summary"], "测试结果")
            self.assertEqual(summary["candidates"]["benchmark_available"], 2)
            result_page = ai_results_page(
                connection, prompt_version=PROMPT_VERSION, verdict="unreviewed"
            )
            self.assertEqual(result_page["count"], 1)
            expected_capture_id = connection.execute(
                "SELECT capture_id FROM ai_analyses WHERE id=?", (analysis_ids[0][0],)
            ).fetchone()[0]
            self.assertEqual(result_page["items"][0]["capture_id"], expected_capture_id)
            self.assertEqual(result_page["items"][0]["review_flags"], [])
            audit = ai_result_audit(connection)
            self.assertEqual(audit["latest"]["result_count"], 1)
            self.assertEqual(audit["latest"]["average_confidence"], 0.8)
            self.assertAlmostEqual(audit["latest"]["average_seconds_per_photo"], 10.0, places=1)
            self.assertEqual(audit["latest"]["schema_errors"], 0)
            self.assertEqual(audit["latest"]["unsafe_action_mentions"], 0)
            ai_report = write_ai_run_report(
                connection, settings.reports_path, run["run_id"]
            )
            self.assertEqual(ai_report["row_count"], 2)
            self.assertTrue(
                (settings.reports_path / ai_report["csv_name"]).is_file()
            )
            report_payload = json.loads(
                (settings.reports_path / ai_report["json_name"]).read_text(encoding="utf-8")
            )
            self.assertFalse(report_payload["photos_mutated"])
            self.assertEqual(report_payload["result_audit"]["latest"]["result_count"], 1)
            self.assertEqual(backfill_ai_audit_metadata(connection), 0)
            self.assertEqual(ai_results_page(connection, audit="risk")["count"], 0)
            retry = create_ai_failure_retry_run(
                connection, run["run_id"], settings.ai_model_path, "int8"
            )
            self.assertEqual(retry["requested_count"], 1)
            self.assertEqual(connection.execute(
                "SELECT prompt_version FROM ai_runs WHERE id=?", (retry["run_id"],)
            ).fetchone()[0], "photo-critique-v5")
            connection.execute("DELETE FROM ai_runs WHERE id=?", (retry["run_id"],))
            connection.commit()
            review = update_ai_review(
                connection, analysis_ids[0][0], "partial", "漏掉了背景干扰"
            )
            self.assertEqual(review["user_verdict"], "partial")
            self.assertIsNotNone(review["reviewed_at"])
            with self.assertRaises(ValueError):
                update_ai_review(connection, analysis_ids[1][0], "accurate", None)
            resumed = resume_ai_run(connection, run["run_id"])
            self.assertEqual(resumed["run_id"], run["run_id"])
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM ai_analyses WHERE run_id=? AND status='queued'",
                (run["run_id"],),
            ).fetchone()[0], 1)
            recovery = recover_interrupted_ai_runs(connection)
            self.assertEqual(recovery["recovered"], [run["run_id"]])
            self.assertEqual(connection.execute(
                "SELECT status FROM ai_runs WHERE id=?", (run["run_id"],)
            ).fetchone()[0], "failed")
            resume_ai_run(connection, run["run_id"])
            connection.execute(
                "UPDATE ai_runs SET status='pause_requested' WHERE id=?", (run["run_id"],)
            )
            connection.commit()
            self.assertEqual(
                _apply_control_request(connection, run["run_id"]), "paused"
            )
            resume_ai_run(connection, run["run_id"])
            connection.execute(
                "UPDATE ai_runs SET status='cancel_requested' WHERE id=?", (run["run_id"],)
            )
            connection.commit()
            self.assertEqual(
                _apply_control_request(connection, run["run_id"]), "cancelled"
            )
            connection.execute("UPDATE quality_metrics SET histogram_json=NULL")
            connection.commit()
            connection.close()

            groups = _query_similarity_groups(settings, 10, 0)
            self.assertGreaterEqual(groups["count"], 1)
            group = _query_similarity_group(settings, groups["items"][0]["id"])
            self.assertEqual(len(group["items"]), 3)
            capture = _query_capture_detail(settings, group["items"][0]["capture_id"])
            self.assertEqual(capture["pairing_status"], "jpeg_only")
            self.assertEqual(len(capture["histogram"]), 64)
            self.assertIn("observations", capture["shooting_review"])
            self.assertIn("technical_evidence", capture["shooting_review"])
            self.assertEqual(
                capture["shooting_review"]["has_model_result"],
                bool(capture["ai_analyses"]),
            )
            reviewed = [item for item in capture["ai_analyses"] if item["user_verdict"]]
            if reviewed:
                self.assertEqual(reviewed[0]["user_verdict"], "partial")

            source = event / "DSCF0001.JPG"
            before = (source.stat().st_size, source.stat().st_mtime_ns)
            thumbnail = ThumbnailCache(settings).get(capture["id"], 320)
            self.assertTrue(thumbnail.is_file())
            with Image.open(thumbnail) as generated:
                self.assertLessEqual(max(generated.size), 320)
            self.assertEqual(before, (source.stat().st_size, source.stat().st_mtime_ns))

            connection = connect(settings.database_path)
            statistics = build_statistics(connection)
            self.assertEqual(statistics["summary"]["capture_count"], 3)
            self.assertEqual(statistics["growth_summary"]["repeat_base_count"], 3)
            self.assertEqual(statistics["growth_summary"]["quality_count"], 3)
            self.assertIsNone(statistics["growth_summary"]["high_rating_rate"])
            self.assertEqual(len(statistics["growth_months"]), 1)
            self.assertEqual(statistics["growth_months"][0]["count"], 3)
            self.assertIn("repeat_capture_rate", statistics["growth_months"][0])
            self.assertIn("growth_subjects", statistics)
            self.assertEqual(statistics["selection_efficiency"]["completed_sessions"], 0)
            self.assertEqual(statistics["edit_feedback"]["reviewed_recipes"], 0)
            self.assertIn("reviewed_groups", statistics["selection_benchmark"])
            self.assertIn("selection_reasons", statistics)
            self.assertEqual(statistics["shooting_review_summary"]["reviewed_captures"], 1)
            self.assertEqual(statistics["shooting_review_summary"]["with_observations"], 1)
            self.assertEqual(statistics["shooting_review_problems"][0]["problem"], "天空高光略亮")
            self.assertEqual(statistics["shooting_review_problems"][0]["repairability"], "partial")
            model_problem_page = query_library_captures(
                settings.database_path, 20, 0, model_problem="天空高光略亮"
            )
            self.assertEqual(
                [item["id"] for item in model_problem_page["items"]],
                [expected_capture_id],
            )
            self.assertEqual(
                query_library_filters(settings.database_path)["model_problems"],
                [{"name": "天空高光略亮", "capture_count": 1}],
            )
            if statistics["selection_benchmark"]["top1_rate"] is not None:
                self.assertGreaterEqual(statistics["selection_benchmark"]["top1_rate"], 0)
                self.assertLessEqual(statistics["selection_benchmark"]["top1_rate"], 100)
            self.assertEqual(statistics["cameras"][0]["camera_model"], "X-Test")
            self.assertEqual(statistics["cameras"][0]["count"], 3)
            self.assertEqual(lightroom_status(connection)["capture_count"], 3)
            self.assertEqual(len(build_lightroom_rows(connection)), 3)
            manifest = write_lightroom_manifest(connection, settings.reports_path)
            self.assertEqual(manifest["capture_count"], 3)
            self.assertTrue((settings.reports_path / manifest["csv_name"]).is_file())
            payload = (settings.reports_path / manifest["json_name"]).read_text(encoding="utf-8")
            self.assertIn('"source_library_mutated": false', payload)
            baseline = create_archive_baseline(connection, "test-originals")
            connection.close()
            (event / "DSCF0003.JPG").unlink()
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            comparison = compare_archive_baseline(connection, baseline["id"])
            self.assertEqual(comparison["missing"], 1)
            self.assertFalse(comparison["healthy"])
            cached = recorded_archive_status(connection)
            self.assertEqual(cached["comparison"]["missing"], 0)
            recorded = run_integrity_check(connection, "archive")
            self.assertEqual(recorded["comparison"]["missing"], 1)
            differences = integrity_differences(connection, "archive", limit=1)
            self.assertEqual(differences["count"], 1)
            self.assertEqual(differences["items"][0]["status"], "missing")
            self.assertEqual(
                Path(differences["items"][0]["relative_path"]).parts,
                ("MyPhoto", "宝贝", "2026.8.6_测试", "DSCF0003.JPG"),
            )
            connection.close()

    def test_image_measurement_and_model_json_parser(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "image.jpg"
            photo(path, 0)
            metrics = measure_image(path)
            self.assertGreater(metrics.sharpness_score, 0)
            histogram = measure_luminance_histogram(path)
            self.assertEqual(len(histogram), 64)
            self.assertEqual(sum(histogram), 320 * 240)
            truncated = Path(directory) / "truncated.jpg"
            truncated.write_bytes(path.read_bytes()[:-64])
            recovered = measure_image(truncated)
            self.assertIsNotNone(recovered.decode_warning)
            parsed = parse_model_json('```json\n{"subject_type":"风景","overall_confidence":0.8}\n```')
            self.assertEqual(parsed["subject_type"], "风景")
            with self.assertRaises(ValueError):
                validate_model_result(parsed)
            complete = {
                "subject_type": "风景", "quality_summary": "测试",
                "visible_problems": [], "shooting_advice": [],
                "lightroom_suggestions": [], "photoshop_needed": False,
                "photoshop_reason": "不需要", "overall_confidence": 0.8,
            }
            self.assertEqual(validate_model_result(complete), complete)
            multi_subject = {
                **complete,
                "subject_tags": [
                    {"name": "风景", "confidence": 0.9},
                    {"name": "旅行", "confidence": 0.7},
                ],
            }
            self.assertEqual(len(validate_model_result(multi_subject)["subject_tags"]), 2)
            parameterized = validate_model_result({
                **complete,
                "edit_parameters": {"exposure_ev": 0.3, "highlights": -25},
            })
            self.assertEqual(parameterized["edit_parameters"]["exposure_ev"], 0.3)
            self.assertEqual(parameterized["edit_parameters"]["contrast"], 0)
            with self.assertRaises(ValueError):
                validate_model_result({**complete, "edit_parameters": {"contrast": 120}})
            with self.assertRaises(ValueError):
                validate_model_result({
                    **complete,
                    "subject_tags": [
                        {"name": "风景", "confidence": 0.9},
                        {"name": "风景", "confidence": 0.8},
                    ],
                })
            overconfident = {**complete, "photoshop_reason": "", "overall_confidence": 1.0}
            normalized = validate_model_result(overconfident)
            self.assertEqual(normalized["overall_confidence"], 0.95)
            self.assertEqual(normalized["photoshop_reason"], "不需要")
            invalid_nested = {**complete, "visible_problems": [{"name": "模糊"}]}
            with self.assertRaises(ValueError):
                validate_model_result(invalid_nested)
            with self.assertRaises(ValueError):
                validate_model_result({**complete, "subject_type": "未知类型"})
            with self.assertRaises(ValueError):
                validate_model_result({**complete, "quality_summary": "  "})
            contradictory = {
                **complete,
                "visible_problems": [{
                    "name": "高光过曝", "severity": "high",
                    "evidence": "天空近白", "confidence": 0.9,
                }],
                "shooting_advice": [{
                    "suggestion": "提高 ISO", "reason": "增加进光",
                    "exif_basis": "ISO 400",
                }],
            }
            with self.assertRaises(ValueError):
                validate_model_result(contradictory)
            warning_severity = {
                **complete,
                "visible_problems": [{
                    "name": "高 ISO", "severity": "warning",
                    "evidence": "ISO 10000", "confidence": 0.8,
                }],
            }
            self.assertEqual(
                validate_model_result(warning_severity)["visible_problems"][0]["severity"],
                "medium",
            )
            moving_subject_tripod = {
                **complete,
                "subject_type": "人像",
                "shooting_advice": [{
                    "suggestion": "使用三脚架降低 ISO", "reason": "减少噪点",
                    "exif_basis": "ISO 12800",
                }],
            }
            with self.assertRaises(ValueError):
                validate_model_result(moving_subject_tripod)
            noisy_higher_iso = {
                **complete,
                "visible_problems": [{
                    "name": "高 ISO 噪点", "severity": "medium",
                    "evidence": "ISO 10000", "confidence": 0.8,
                }],
                "shooting_advice": [{
                    "suggestion": "提高 ISO 至 20000", "reason": "改善暗部",
                    "exif_basis": "ISO 10000",
                }],
            }
            with self.assertRaises(ValueError):
                validate_model_result(noisy_higher_iso)
            already_stopped_down = {
                **complete,
                "shooting_advice": [{
                    "suggestion": "缩小光圈控制高光", "reason": "减少进光",
                    "exif_basis": "aperture 22.0",
                }],
            }
            with self.assertRaises(ValueError):
                validate_model_result(already_stopped_down)
            safe_aperture_alternative = {
                **complete,
                "shooting_advice": [{
                    "suggestion": "降低曝光补偿或缩小光圈", "reason": "减少进光",
                    "exif_basis": "aperture: 22.0",
                }],
            }
            self.assertEqual(
                validate_model_result(safe_aperture_alternative)["shooting_advice"][0]["suggestion"],
                "降低曝光补偿",
            )
            self.assertEqual(_format_exposure_seconds(0.006666666667), "1/150 秒")
            self.assertEqual(_format_exposure_seconds(2.5), "2.5 秒")


if __name__ == "__main__":
    unittest.main()
