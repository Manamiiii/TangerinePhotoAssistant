from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import platform
import sqlite3
import subprocess
import sys
import time
import tracemalloc
from collections.abc import Callable, Iterable
from pathlib import Path
from statistics import median
from typing import Any

from .ai_analysis import ai_results_page
from .database import SCHEMA_VERSION, connect, connect_readonly, read_schema_version
from .queries.library import query_library_captures
from .queries.similarity import query_similarity_groups
from .statistics import build_statistics

SCENARIOS = (
    "library-first-page",
    "library-deep-page",
    "collapsed-large-album",
    "model-problem-filter",
    "ai-risk-queue",
    "statistics-overview",
    "similarity-pending",
)
DEFAULT_SIZES = (10_000, 50_000, 100_000)
GENERATOR_VERSION = 1
WORKSPACE_MARKER = ".tangerine-synthetic-benchmark"


def _batches(values: Iterable[tuple[Any, ...]], size: int = 5_000) -> Iterable[list[tuple[Any, ...]]]:
    batch: list[tuple[Any, ...]] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _insert_batches(
    connection: sqlite3.Connection, sql: str, values: Iterable[tuple[Any, ...]]
) -> None:
    for batch in _batches(values):
        connection.executemany(sql, batch)


def _album_id(capture_id: int, album_count: int) -> int:
    # Keep one realistically large album while distributing the rest broadly.
    return 1 if capture_id % 5 == 0 else 2 + (capture_id % (album_count - 1))


def generate_synthetic_catalog(database_path: Path, capture_count: int) -> dict[str, Any]:
    """Create metadata-only deterministic data; no photo files are created or read."""
    if capture_count < 100:
        raise ValueError("capture_count must be at least 100")
    if database_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing benchmark database: {database_path}")
    connection = connect(database_path)
    album_count = min(100, max(5, capture_count // 100))
    group_count = capture_count // 5
    ai_count = capture_count // 5
    now = "2026-08-24T00:00:00+00:00"
    model_result_ok = json.dumps({
        "subject_type": "风景",
        "quality_summary": "合成基准结果",
        "visible_problems": [],
        "shooting_advice": [],
        "lightroom_suggestions": [],
        "photoshop_needed": False,
        "photoshop_reason": "不需要",
        "overall_confidence": 0.82,
    }, ensure_ascii=False)
    model_result_problem = json.dumps({
        "subject_type": "夜景",
        "quality_summary": "合成基准结果",
        "visible_problems": [{"name": "噪点", "confidence": 0.92}],
        "shooting_advice": [],
        "lightroom_suggestions": [],
        "photoshop_needed": False,
        "photoshop_reason": "不需要",
        "overall_confidence": 0.92,
    }, ensure_ascii=False)
    try:
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            """INSERT INTO scan_runs(id, started_at, finished_at, root_path, status, files_seen)
               VALUES (1, ?, ?, 'SYNTHETIC_BENCHMARK_ONLY', 'complete', ?)""",
            (now, now, capture_count),
        )
        connection.executemany(
            """INSERT INTO events(
                   id, event_key, proposed_name, category, date_label, start_at, end_at,
                   capture_count, status, confidence, reason_json, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', 1, '[]', ?, ?)""",
            [
                (
                    album_id,
                    f"benchmark-album-{album_id:03d}",
                    f"基准相册 {album_id:03d}",
                    ("旅行", "风景", "城市", "日常")[album_id % 4],
                    f"2025-{(album_id % 12) + 1:02d}",
                    f"2025-{(album_id % 12) + 1:02d}-01T08:00:00",
                    f"2025-{(album_id % 12) + 1:02d}-28T18:00:00",
                    sum(1 for capture_id in range(1, capture_count + 1)
                        if _album_id(capture_id, album_count) == album_id),
                    now,
                    now,
                )
                for album_id in range(1, album_count + 1)
            ],
        )
        _insert_batches(
            connection,
            """INSERT INTO files(
                   id, path, relative_path, parent_relative, file_name, stem, extension,
                   media_kind, size_bytes, modified_ns, first_seen_run_id, last_seen_run_id,
                   present, metadata_status, captured_at, camera_make, camera_model,
                   lens_model, exposure_time, f_number, iso, focal_length_mm,
                   focal_length_35mm, width, height, metadata_profile_version
               ) VALUES (?, ?, ?, ?, ?, ?, '.jpg', 'image', ?, ?, 1, 1, 1, 'complete',
                         ?, ?, ?, ?, ?, ?, ?, ?, ?, 6240, 4160, 3)""",
            (
                (
                    capture_id,
                    f"SYNTHETIC:/Album-{_album_id(capture_id, album_count):03d}/IMG_{capture_id:07d}.jpg",
                    f"Album-{_album_id(capture_id, album_count):03d}/IMG_{capture_id:07d}.jpg",
                    f"Album-{_album_id(capture_id, album_count):03d}",
                    f"IMG_{capture_id:07d}.jpg",
                    f"IMG_{capture_id:07d}",
                    2_000_000 + (capture_id % 12_000_000),
                    1_700_000_000_000_000_000 + capture_id,
                    f"2025-{(capture_id % 12) + 1:02d}-{(capture_id % 28) + 1:02d}T{capture_id % 24:02d}:00:00",
                    ("FUJIFILM", "SONY", "Canon", "NIKON")[capture_id % 4],
                    ("X-S20", "ILCE-7M4", "EOS R6 Mark II", "Z 6_2")[capture_id % 4],
                    ("23mm F1.4", "35mm F1.8", "24-70mm F2.8", "70-300mm")[capture_id % 4],
                    (1 / 60, 1 / 125, 1 / 250, 1 / 500)[capture_id % 4],
                    (1.4, 2.8, 5.6, 8.0)[capture_id % 4],
                    (100, 400, 1600, 3200)[capture_id % 4],
                    (23.0, 35.0, 50.0, 100.0)[capture_id % 4],
                    (35.0, 50.0, 75.0, 150.0)[capture_id % 4],
                )
                for capture_id in range(1, capture_count + 1)
            ),
        )
        _insert_batches(
            connection,
            """INSERT INTO captures(id, capture_key, parent_relative, stem, captured_at, pairing_status)
               VALUES (?, ?, ?, ?, ?, 'jpeg_only')""",
            (
                (
                    capture_id,
                    f"benchmark-capture-{capture_id:07d}",
                    f"Album-{_album_id(capture_id, album_count):03d}",
                    f"IMG_{capture_id:07d}",
                    f"2025-{(capture_id % 12) + 1:02d}-{(capture_id % 28) + 1:02d}T{capture_id % 24:02d}:00:00",
                )
                for capture_id in range(1, capture_count + 1)
            ),
        )
        _insert_batches(
            connection,
            "INSERT INTO capture_files(capture_id, file_id, role) VALUES (?, ?, 'jpeg')",
            ((capture_id, capture_id) for capture_id in range(1, capture_count + 1)),
        )
        _insert_batches(
            connection,
            "INSERT INTO event_captures(event_id, capture_id, sequence_index) VALUES (?, ?, ?)",
            ((_album_id(capture_id, album_count), capture_id, capture_id)
             for capture_id in range(1, capture_count + 1)),
        )
        _insert_batches(
            connection,
            """INSERT INTO capture_reviews(
                   capture_id, auto_rating, auto_pick, similarity_rank, user_rating,
                   user_pick, user_reject, updated_at, selection_reason_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    capture_id,
                    1 + capture_id % 5,
                    int(capture_id % 5 == 1),
                    1 + capture_id % 3,
                    1 + capture_id % 5 if capture_id % 4 == 0 else None,
                    int(capture_id % 25 == 1),
                    int(capture_id % 25 in {2, 3}),
                    now,
                    '["动作"]' if capture_id % 25 == 1 else "[]",
                )
                for capture_id in range(1, capture_count + 1)
            ),
        )
        _insert_batches(
            connection,
            """INSERT INTO quality_metrics(
                   capture_id, source_file_id, algorithm_version, technical_score,
                   issue_json, size_bytes, modified_ns, computed_at
               ) VALUES (?, ?, 'synthetic-v1', ?, ?, ?, ?, ?)""",
            (
                (
                    capture_id,
                    capture_id,
                    45.0 + capture_id % 51,
                    '[{"code":"noise","message":"合成噪点"}]'
                    if capture_id % 10 == 0 else "[]",
                    2_000_000 + (capture_id % 12_000_000),
                    1_700_000_000_000_000_000 + capture_id,
                    now,
                )
                for capture_id in range(1, capture_count + 1)
            ),
        )
        connection.executemany(
            """INSERT INTO bursts(
                   id, event_id, burst_key, start_at, end_at, capture_count,
                   camera_model, grouping_method, status
               ) VALUES (?, 1, ?, ?, ?, 3, 'X-S20', 'synthetic', 'candidate')""",
            [
                (group_id, f"benchmark-burst-{group_id:07d}", now, now)
                for group_id in range(1, group_count + 1)
            ],
        )
        connection.executemany(
            """INSERT INTO similarity_groups(
                   id, burst_id, group_key, capture_count, max_adjacent_hamming, status
               ) VALUES (?, ?, ?, 3, 4, 'candidate')""",
            [
                (group_id, group_id, f"benchmark-group-{group_id:07d}")
                for group_id in range(1, group_count + 1)
            ],
        )
        _insert_batches(
            connection,
            """INSERT INTO similarity_group_captures(
                   group_id, capture_id, sequence_index, distance_from_previous
               ) VALUES (?, ?, ?, ?)""",
            (
                (group_id, (group_id - 1) * 5 + member, member - 1, member - 1)
                for group_id in range(1, group_count + 1)
                for member in (1, 2, 3)
            ),
        )
        connection.execute(
            """INSERT INTO ai_runs(
                   id, mode, model_id, prompt_version, status, requested_count,
                   completed_count, failed_count, started_at, finished_at
               ) VALUES (1, 'benchmark', 'synthetic-model', 'synthetic-v1', 'complete',
                         ?, ?, 0, ?, ?)""",
            (ai_count, ai_count, now, now),
        )
        _insert_batches(
            connection,
            """INSERT INTO ai_analyses(
                   id, run_id, capture_id, model_id, prompt_version, status, priority,
                   selection_reason, result_json, attempt_count, started_at, finished_at,
                   audit_flags_json, audit_bits, audit_confidence,
                   audit_visible_problem_count
               ) VALUES (?, 1, ?, 'synthetic-model', 'synthetic-v1', 'complete', 0,
                         'synthetic', ?, 1, ?, ?, ?, ?, ?, ?)""",
            (
                (
                    analysis_id,
                    capture_id,
                    model_result_problem if capture_id % 10 == 0 else model_result_ok,
                    now,
                    now,
                    '["overconfident"]' if capture_id % 100 == 0 else "[]",
                    256 if capture_id % 100 == 0 else 0,
                    0.92 if capture_id % 10 == 0 else 0.82,
                    1 if capture_id % 10 == 0 else 0,
                )
                for analysis_id, capture_id in enumerate(range(5, capture_count + 1, 5), 1)
            ),
        )
        subject_tag_ids = [
            row["id"] for row in connection.execute(
                """SELECT id FROM tag_definitions
                   WHERE dimension='subject' AND active=1 ORDER BY id LIMIT 4"""
            ).fetchall()
        ]
        if subject_tag_ids:
            _insert_batches(
                connection,
                """INSERT OR IGNORE INTO capture_tags(
                       capture_id, tag_id, source, confidence, created_at
                   ) VALUES (?, ?, 'manual', NULL, ?)""",
                (
                    (capture_id, subject_tag_ids[capture_id % len(subject_tag_ids)], now)
                    for capture_id in range(1, capture_count + 1)
                ),
            )
        connection.execute("ANALYZE")
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    metadata = {
        "generator_version": GENERATOR_VERSION,
        "schema_version": SCHEMA_VERSION,
        "capture_count": capture_count,
        "album_count": album_count,
        "similarity_group_count": group_count,
        "ai_analysis_count": ai_count,
        "integrity_check": integrity,
        "database_bytes": database_path.stat().st_size,
        "photos_created": 0,
    }
    database_path.with_suffix(".meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def _scenario(
    database_path: Path, name: str, trace: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> Callable[[], Any]:
    context = context if context is not None else _scenario_context(database_path)
    callback = trace.append if trace is not None else None
    if name == "library-first-page":
        return lambda: query_library_captures(database_path, 40, 0, trace=callback)
    if name == "library-deep-page":
        return lambda: query_library_captures(
            database_path, 40, max(0, context["visible_capture_count"] - 80), trace=callback
        )
    if name == "collapsed-large-album":
        return lambda: query_library_captures(
            database_path, 40, 0, album_id=context["album_id"], collapse_groups=True,
            trace=callback,
        )
    if name == "model-problem-filter":
        return lambda: query_library_captures(
            database_path, 40, 0, model_problem=context["model_problem"], trace=callback
        )
    if name == "similarity-pending":
        return lambda: query_similarity_groups(
            database_path, 40, 0, review_filter="pending", trace=callback
        )
    if name == "ai-risk-queue":
        def run_ai_risk() -> dict[str, Any]:
            connection = connect_readonly(database_path)
            try:
                if trace is not None:
                    connection.set_trace_callback(trace.append)
                return ai_results_page(connection, limit=40, audit="risk")
            finally:
                connection.close()
        return run_ai_risk
    if name == "statistics-overview":
        def run_statistics() -> dict[str, Any]:
            connection = connect_readonly(database_path)
            try:
                if trace is not None:
                    connection.set_trace_callback(trace.append)
                return build_statistics(connection)
            finally:
                connection.close()
        return run_statistics
    raise ValueError(f"Unknown benchmark scenario: {name}")


def _scenario_context(database_path: Path) -> dict[str, Any]:
    """Choose populated scenarios from visible photos, not synthetic fixture IDs."""
    connection = connect_readonly(database_path)
    visible = """SELECT DISTINCT cf.capture_id FROM capture_files cf
                 JOIN files f ON f.id=cf.file_id WHERE cf.role='jpeg' AND f.present=1"""
    try:
        count = connection.execute(f"SELECT COUNT(*) FROM ({visible})").fetchone()[0]
        album = connection.execute(
            f"""SELECT ec.event_id, COUNT(*) AS photos FROM event_captures ec
                JOIN ({visible}) v ON v.capture_id=ec.capture_id
                GROUP BY ec.event_id ORDER BY photos DESC, ec.event_id LIMIT 1"""
        ).fetchone()
        problem = connection.execute(
            f"""SELECT json_extract(problem.value, '$.name') AS name,
                       COUNT(DISTINCT aa.capture_id) AS photos
                FROM ai_analyses aa JOIN ({visible}) v ON v.capture_id=aa.capture_id,
                     json_each(json_extract(aa.result_json, '$.visible_problems')) problem
                WHERE aa.status='complete' AND COALESCE(aa.user_verdict, '')!='inaccurate'
                  AND aa.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                             WHERE newest.capture_id=aa.capture_id AND newest.status='complete')
                  AND typeof(json_extract(problem.value, '$.name'))='text'
                  AND trim(json_extract(problem.value, '$.name'))!=''
                GROUP BY name ORDER BY photos DESC, name LIMIT 1"""
        ).fetchone()
        return {
            "visible_capture_count": count,
            "album_id": album[0] if album else None,
            "album_capture_count": album[1] if album else 0,
            "model_problem": problem[0] if problem else None,
            "model_problem_capture_count": problem[1] if problem else 0,
        }
    finally:
        connection.close()


def _capture_count(database_path: Path) -> int:
    connection = connect_readonly(database_path)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0])
    finally:
        connection.close()


def _process_memory() -> dict[str, int | None]:
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong), ("page_fault_count", ctypes.c_ulong),
                ("peak_working_set_size", ctypes.c_size_t),
                ("working_set_size", ctypes.c_size_t),
                ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                ("quota_paged_pool_usage", ctypes.c_size_t),
                ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                ("quota_non_paged_pool_usage", ctypes.c_size_t),
                ("pagefile_usage", ctypes.c_size_t),
                ("peak_pagefile_usage", ctypes.c_size_t),
            ]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong,
        )
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        success = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        if success:
            return {
                "working_set_bytes": int(counters.working_set_size),
                "peak_working_set_bytes": int(counters.peak_working_set_size),
            }
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if platform.system() != "Darwin":
            peak *= 1024
        return {"working_set_bytes": None, "peak_working_set_bytes": peak}
    except (ImportError, OSError):
        return {"working_set_bytes": None, "peak_working_set_bytes": None}


def _query_plans(database_path: Path, statements: list[str]) -> list[dict[str, Any]]:
    connection = connect_readonly(database_path)
    plans: list[dict[str, Any]] = []
    try:
        seen: set[str] = set()
        for statement in statements:
            normalized = statement.strip()
            if normalized in seen or not normalized.upper().startswith(("SELECT", "WITH")):
                continue
            seen.add(normalized)
            try:
                rows = connection.execute(f"EXPLAIN QUERY PLAN {normalized}").fetchall()
            except sqlite3.Error as exc:
                plans.append({"sql": normalized, "error": type(exc).__name__})
                continue
            plans.append({
                "sql": normalized,
                "steps": [dict(row) for row in rows],
            })
    finally:
        connection.close()
    return plans


def benchmark_scenario(
    database_path: Path, name: str, iterations: int = 5
) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    context = _scenario_context(database_path)
    if (name == "collapsed-large-album" and context["album_id"] is None
            or name == "model-problem-filter" and context["model_problem"] is None):
        return {"scenario": name, "status": "skipped", "reason": "no-matching-data",
                "iterations": 0, "p50_ms": None, "p95_ms": None, "result_count": 0,
                "query_plans": []}
    # Trace and allocation tracking distort timing. Collect them in separate passes.
    trace: list[str] = []
    run = _scenario(database_path, name, context=context)
    started = time.perf_counter()
    run()
    first_call_ms = (time.perf_counter() - started) * 1_000
    before = _process_memory()
    durations: list[float] = []
    result: Any = None
    for _ in range(iterations):
        started = time.perf_counter()
        result = run()
        durations.append((time.perf_counter() - started) * 1_000)
    after = _process_memory()
    tracemalloc.start()
    try:
        run()
        _, python_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    _scenario(database_path, name, trace, context)()
    ordered = sorted(durations)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    result_count = None
    if isinstance(result, dict):
        result_count = result.get("count")
        if result_count is None and isinstance(result.get("summary"), dict):
            result_count = result["summary"].get("capture_count")
    return {
        "scenario": name,
        "status": "measured",
        "first_call_ms": round(first_call_ms, 3),
        "timing_instrumentation": "none",
        "memory_measurement": "separate-pass",
        "context": {key: value for key, value in context.items() if key != "model_problem"},
        "iterations": iterations,
        "p50_ms": round(median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "min_ms": round(min(ordered), 3),
        "max_ms": round(max(ordered), 3),
        "python_peak_bytes": python_peak,
        "working_set_before_bytes": before["working_set_bytes"],
        "working_set_after_bytes": after["working_set_bytes"],
        "process_peak_working_set_bytes": after["peak_working_set_bytes"],
        "result_count": result_count,
        "query_plans": _query_plans(database_path, trace),
    }


def run_benchmark_suite(
    workspace: Path, sizes: Iterable[int], iterations: int = 5
) -> dict[str, Any]:
    workspace = workspace.resolve()
    marker = workspace / WORKSPACE_MARKER
    if workspace.exists() and not marker.is_file() and any(workspace.iterdir()):
        raise RuntimeError(
            "Benchmark workspace is not empty and has no Tangerine synthetic marker"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(
            json.dumps({
                "purpose": "TangerinePhotoAssistant metadata-only performance benchmark",
                "photos_created": 0,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    reports = []
    for size in sizes:
        database_path = workspace / f"synthetic-{size}.sqlite3"
        if database_path.exists():
            metadata_path = database_path.with_suffix(".meta.json")
            if not metadata_path.is_file():
                raise RuntimeError(
                    f"Existing {database_path.name} has no generator metadata; "
                    "remove the isolated benchmark directory before rebuilding"
                )
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            actual = _capture_count(database_path)
            if (
                actual != size
                or metadata.get("capture_count") != size
                or metadata.get("generator_version") != GENERATOR_VERSION
                or metadata.get("schema_version") != SCHEMA_VERSION
            ):
                raise RuntimeError(
                    f"Existing {database_path.name} does not match the current generator; "
                    "remove the isolated benchmark directory before rebuilding"
                )
            generated = {**metadata, "database_bytes": database_path.stat().st_size,
                         "reused": True}
        else:
            generated = generate_synthetic_catalog(database_path, size)
        scenarios = []
        for name in SCENARIOS:
            completed = subprocess.run(
                [
                    sys.executable, "-m",
                    "tangerine_photo_assistant.large_library_benchmark",
                    "--worker", str(database_path), name, str(iterations),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            scenarios.append(json.loads(completed.stdout))
        reports.append({"dataset": generated, "scenarios": scenarios})
    report = {
        "benchmark_version": 2,
        "schema_version": SCHEMA_VERSION,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "iterations": iterations,
        "datasets": reports,
        "source_photos_read": 0,
        "source_photos_written": 0,
    }
    output = workspace / "large-library-benchmark.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(output)
    return report


def benchmark_existing_catalog(
    database_path: Path,
    output_path: Path,
    iterations: int = 5,
    scenarios: Iterable[str] = SCENARIOS,
) -> dict[str, Any]:
    """Benchmark an existing current-schema catalog without reading source photos."""
    database_path = database_path.resolve()
    output_path = output_path.resolve()
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if not database_path.is_file():
        raise FileNotFoundError("Existing benchmark catalog does not exist")
    if output_path == database_path:
        raise ValueError("Benchmark report must not replace the catalog")
    if output_path.suffix.casefold() != ".json":
        raise ValueError("Benchmark report must use a .json filename")
    if output_path.exists():
        raise FileExistsError("Refusing to overwrite an existing benchmark report")
    if not output_path.parent.is_dir():
        raise FileNotFoundError("Benchmark report directory does not exist")
    schema_version = read_schema_version(database_path)
    if schema_version != SCHEMA_VERSION:
        raise RuntimeError(
            f"Existing catalog schema is {schema_version}; expected {SCHEMA_VERSION}"
        )
    capture_count = _capture_count(database_path)
    measured = []
    for name in scenarios:
        if name not in SCENARIOS:
            raise ValueError(f"Unknown benchmark scenario: {name}")
        completed = subprocess.run(
            [
                sys.executable, "-m",
                "tangerine_photo_assistant.large_library_benchmark",
                "--worker", str(database_path), name, str(iterations),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        measured.append(json.loads(completed.stdout))
    report = {
        "benchmark_version": 2,
        "schema_version": schema_version,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "iterations": iterations,
        "catalog": {
            "capture_count": capture_count,
            "database_bytes": database_path.stat().st_size,
        },
        "scenarios": measured,
        "integrity_check": "not-run",
        "source_photos_read": 0,
        "source_photos_written": 0,
    }
    with output_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    return {**report, "report_path": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build metadata-only synthetic catalogs and benchmark large-library queries."
    )
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--existing-database", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sizes", nargs="+", type=int, default=list(DEFAULT_SIZES))
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--worker", nargs=3, metavar=("DATABASE", "SCENARIO", "ITERATIONS"))
    arguments = parser.parse_args()
    if arguments.worker:
        database, scenario, iterations = arguments.worker
        print(json.dumps(
            benchmark_scenario(Path(database), scenario, int(iterations)),
            ensure_ascii=False,
        ))
        return
    if arguments.existing_database is not None:
        if arguments.workspace is not None:
            parser.error("--workspace and --existing-database cannot be combined")
        if arguments.output is None:
            parser.error("--output is required with --existing-database")
        try:
            report = benchmark_existing_catalog(
                arguments.existing_database, arguments.output, arguments.iterations
            )
        except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
            parser.exit(2, f"error: {exc}\n")
        print(json.dumps({
            "report_path": report["report_path"],
            "capture_count": report["catalog"]["capture_count"],
        }, ensure_ascii=False))
        return
    if arguments.workspace is None:
        parser.error("--workspace is required")
    if arguments.output is not None:
        parser.error("--output is only valid with --existing-database")
    report = run_benchmark_suite(arguments.workspace, arguments.sizes, arguments.iterations)
    print(json.dumps({
        "report_path": report["report_path"],
        "datasets": len(report["datasets"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
