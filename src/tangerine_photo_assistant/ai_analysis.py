from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import transaction
from .editing import normalize_edit_parameters
from .inventory import utc_now
from .tags import replace_analysis_subject_tags

PROMPT_VERSION = "photo-critique-v5"


def _balanced_benchmark_candidates(
    rows: list[sqlite3.Row], limit: int
) -> list[sqlite3.Row]:
    by_category: dict[str, dict[int, list[sqlite3.Row]]] = {}
    for row in rows:
        by_category.setdefault(row["category"], {}).setdefault(
            int(row["event_id"]), []
        ).append(row)
    event_offsets = {category: 0 for category in by_category}
    interleaved: list[sqlite3.Row] = []
    while len(interleaved) < len(rows):
        added = False
        for category in sorted(by_category):
            events = sorted(by_category[category])
            if not events:
                continue
            start = event_offsets[category] % len(events)
            for offset in range(len(events)):
                event_id = events[(start + offset) % len(events)]
                bucket = by_category[category][event_id]
                if bucket:
                    interleaved.append(bucket.pop(0))
                    event_offsets[category] = (start + offset + 1) % len(events)
                    added = True
                    break
        if not added:
            break

    selected: list[sqlite3.Row] = []
    deferred: list[sqlite3.Row] = []
    seen_similarity_groups: set[int] = set()
    for row in interleaved:
        group_id = row["similarity_group_id"]
        if group_id is not None and int(group_id) in seen_similarity_groups:
            deferred.append(row)
            continue
        selected.append(row)
        if group_id is not None:
            seen_similarity_groups.add(int(group_id))
    return (selected + deferred)[:limit]


def model_id(model_path: Path, model_variant: str | None = None) -> str:
    variant = (model_variant or "").strip().lower()
    return f"{model_path.name}@{variant}" if variant and variant != "none" else model_path.name


def create_ai_run(
    connection: sqlite3.Connection,
    model_path: Path,
    mode: str,
    limit: int,
    model_variant: str | None = None,
) -> dict[str, int | str]:
    if mode not in {"benchmark", "recommended"}:
        raise ValueError("AI mode must be benchmark or recommended")
    if limit <= 0 or limit > 5000:
        raise ValueError("AI analysis limit must be between 1 and 5000")
    current = connection.execute(
        """SELECT id FROM ai_runs
           WHERE status IN ('queued', 'running', 'pause_requested', 'paused',
                            'cancel_requested') LIMIT 1"""
    ).fetchone()
    if current:
        raise RuntimeError("已有本地大模型任务正在运行")

    candidate_rows = connection.execute(
        """
        SELECT
            c.id AS capture_id,
            CASE
                WHEN cr.auto_pick = 1 THEN 120
                WHEN qm.technical_score < 55 THEN 100
                WHEN sgc.capture_id IS NULL THEN 50
                ELSE 20
            END AS priority,
            CASE
                WHEN cr.auto_pick = 1 THEN 'similarity_group_representative'
                WHEN qm.technical_score < 55 THEN 'technical_issue_review'
                WHEN sgc.capture_id IS NULL THEN 'standalone_sample'
                ELSE 'similarity_group_comparison'
            END AS selection_reason,
            e.id AS event_id, e.category,
            MIN(sgc.group_id) AS similarity_group_id,
            COALESCE(qm.technical_score, 0) AS technical_score
        FROM captures c
        JOIN event_captures ec ON ec.capture_id = c.id
        JOIN events e ON e.id = ec.event_id
        JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
        JOIN files f ON f.id = cf.file_id AND f.present = 1
        LEFT JOIN quality_metrics qm ON qm.capture_id = c.id AND qm.error IS NULL
        LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
        LEFT JOIN similarity_group_captures sgc ON sgc.capture_id = c.id
        WHERE qm.capture_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM ai_analyses previous
              WHERE previous.capture_id = c.id
                AND previous.model_id = ?
                AND previous.prompt_version = ?
                AND previous.status = 'complete'
          )
          AND (
              ? = 'benchmark'
              OR cr.auto_pick = 1
              OR qm.technical_score < 55
              OR (sgc.capture_id IS NULL AND c.id % 5 = 0)
          )
        GROUP BY c.id
        ORDER BY priority DESC, c.id
        """,
        (model_id(model_path, model_variant), PROMPT_VERSION, mode),
    ).fetchall()
    if mode == "benchmark":
        candidate_rows = _balanced_benchmark_candidates(candidate_rows, limit)
    else:
        candidate_rows = candidate_rows[:limit]
    if not candidate_rows:
        raise ValueError("没有可分析的候选；请先运行技术质量分析，或候选已全部完成")

    with transaction(connection):
        cursor = connection.execute(
            """
            INSERT INTO ai_runs(
                mode, model_id, prompt_version, status, requested_count, started_at
            ) VALUES (?, ?, ?, 'queued', ?, ?)
            """,
            (
                mode, model_id(model_path, model_variant), PROMPT_VERSION,
                len(candidate_rows), utc_now(),
            ),
        )
        run_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO ai_analyses(
                run_id, capture_id, model_id, prompt_version,
                status, priority, selection_reason
            ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
            """,
            [
                (
                    run_id, row["capture_id"], model_id(model_path, model_variant),
                    PROMPT_VERSION,
                    row["priority"], row["selection_reason"],
                )
                for row in candidate_rows
            ],
        )
    return {"run_id": run_id, "mode": mode, "requested_count": len(candidate_rows)}


def create_ai_failure_retry_run(
    connection: sqlite3.Connection,
    source_run_id: int,
    model_path: Path,
    model_variant: str | None = None,
) -> dict[str, int | str]:
    active = connection.execute(
        """SELECT id FROM ai_runs
           WHERE status IN ('queued', 'running', 'pause_requested', 'paused',
                            'cancel_requested') LIMIT 1"""
    ).fetchone()
    if active:
        raise RuntimeError("已有本地大模型任务正在运行")
    source = connection.execute(
        "SELECT id FROM ai_runs WHERE id=?", (source_run_id,)
    ).fetchone()
    if source is None:
        raise ValueError("原模型任务不存在")
    failures = connection.execute(
        """
        SELECT capture_id, priority, selection_reason
        FROM ai_analyses
        WHERE run_id=? AND status='failed'
        ORDER BY priority DESC, id
        """,
        (source_run_id,),
    ).fetchall()
    if not failures:
        raise ValueError("原模型任务没有失败照片")
    with transaction(connection):
        cursor = connection.execute(
            """
            INSERT INTO ai_runs(
                mode, model_id, prompt_version, status, requested_count, started_at
            ) VALUES ('retry', ?, ?, 'queued', ?, ?)
            """,
            (
                model_id(model_path, model_variant), PROMPT_VERSION,
                len(failures), utc_now(),
            ),
        )
        run_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO ai_analyses(
                run_id, capture_id, model_id, prompt_version,
                status, priority, selection_reason
            ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
            """,
            [
                (
                    run_id, row["capture_id"], model_id(model_path, model_variant),
                    PROMPT_VERSION, row["priority"],
                    f"retry:{source_run_id}:{row['selection_reason']}",
                )
                for row in failures
            ],
        )
    return {"run_id": run_id, "mode": "retry", "requested_count": len(failures)}


def ai_run_status(connection: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM ai_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"AI run {run_id} does not exist")
    return dict(row)


def update_ai_review(
    connection: sqlite3.Connection,
    analysis_id: int,
    verdict: str | None,
    note: str | None,
) -> dict[str, Any]:
    if verdict not in {None, "accurate", "partial", "inaccurate"}:
        raise ValueError("模型复核结论无效")
    row = connection.execute(
        "SELECT status, capture_id, result_json FROM ai_analyses WHERE id=?", (analysis_id,)
    ).fetchone()
    if row is None:
        raise ValueError("模型分析记录不存在")
    if row["status"] != "complete":
        raise ValueError("只能复核已完成的模型结果")
    cleaned_note = note.strip() if note and note.strip() else None
    reviewed_at = utc_now() if verdict is not None or cleaned_note is not None else None
    with transaction(connection):
        connection.execute(
            """
            UPDATE ai_analyses
            SET user_verdict=?, user_note=?, reviewed_at=?
            WHERE id=?
            """,
            (verdict, cleaned_note, reviewed_at, analysis_id),
        )
        is_latest = connection.execute(
            """SELECT 1 FROM ai_analyses
               WHERE id=? AND id=(SELECT MAX(newest.id) FROM ai_analyses newest
                                  WHERE newest.capture_id=? AND newest.status='complete')""",
            (analysis_id, row["capture_id"]),
        ).fetchone()
        if is_latest:
            if verdict == "inaccurate":
                connection.execute(
                    """DELETE FROM capture_tags WHERE capture_id=? AND source='analysis'
                         AND tag_id IN (SELECT id FROM tag_definitions
                                        WHERE dimension='subject')""",
                    (row["capture_id"],),
                )
            else:
                try:
                    result = json.loads(row["result_json"] or "{}")
                except json.JSONDecodeError:
                    result = {}
                if isinstance(result, dict):
                    replace_analysis_subject_tags(
                        connection, int(row["capture_id"]), result
                    )
    return {
        "id": analysis_id,
        "user_verdict": verdict,
        "user_note": cleaned_note,
        "reviewed_at": reviewed_at,
    }


def resume_ai_run(connection: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    run = ai_run_status(connection, run_id)
    if run["status"] not in {"failed", "cancelled", "paused"}:
        raise ValueError("只能继续失败、已取消或已暂停的模型任务")
    with transaction(connection):
        connection.execute(
            """
            UPDATE ai_analyses SET status='queued', error=NULL,
                started_at=NULL, finished_at=NULL
            WHERE run_id=? AND status != 'complete'
            """,
            (run_id,),
        )
        completed = connection.execute(
            "SELECT COUNT(*) FROM ai_analyses WHERE run_id=? AND status='complete'",
            (run_id,),
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE ai_runs SET status='queued', completed_count=?, failed_count=0,
                finished_at=NULL, error=NULL WHERE id=?
            """,
            (completed, run_id),
        )
    return {
        "run_id": run_id,
        "mode": run["mode"],
        "requested_count": run["requested_count"],
    }


def _process_exists(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, ProcessLookupError):
        return False
    return True


def recover_interrupted_ai_runs(connection: sqlite3.Connection) -> dict[str, list[int]]:
    rows = connection.execute(
        """
        SELECT id, worker_pid FROM ai_runs
        WHERE status IN ('queued', 'running', 'pause_requested', 'cancel_requested')
        ORDER BY id
        """
    ).fetchall()
    recovered: list[int] = []
    still_running: list[int] = []
    for row in rows:
        if _process_exists(row["worker_pid"]):
            still_running.append(row["id"])
            continue
        with transaction(connection):
            connection.execute(
                """
                UPDATE ai_analyses SET status='failed',
                    error=COALESCE(error, '服务中断时该照片正在处理'), finished_at=?
                WHERE run_id=? AND status='running'
                """,
                (utc_now(), row["id"]),
            )
            counts = connection.execute(
                """SELECT SUM(status='complete'), SUM(status='failed')
                   FROM ai_analyses WHERE run_id=?""",
                (row["id"],),
            ).fetchone()
            connection.execute(
                """
                UPDATE ai_runs SET status='failed', completed_count=?, failed_count=?,
                    finished_at=?, worker_pid=NULL,
                    error='模型工作进程不存在；任务已解锁，可安全继续'
                WHERE id=?
                """,
                (counts[0] or 0, counts[1] or 0, utc_now(), row["id"]),
            )
        recovered.append(row["id"])
    return {"recovered": recovered, "still_running": still_running}


def _decorate_ai_run(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    run = dict(row)
    timing = connection.execute(
        """
        SELECT COUNT(*) AS timed_count,
               AVG((julianday(finished_at) - julianday(started_at)) * 86400.0)
                   AS average_seconds,
               SUM(attempt_count) AS total_attempts,
               MAX(attempt_count) AS max_attempts
        FROM ai_analyses
        WHERE run_id=? AND started_at IS NOT NULL AND finished_at IS NOT NULL
        """,
        (run["id"],),
    ).fetchone()
    processed = run["completed_count"] + run["failed_count"]
    average_seconds = timing["average_seconds"]
    backup = connection.execute(
        """
        SELECT COUNT(*) AS backup_count, MAX(created_at) AS latest_backup_at
        FROM ai_run_backups WHERE run_id=?
        """,
        (run["id"],),
    ).fetchone()
    run.update({
        "report_available": True,
        "processed_count": processed,
        "success_rate": (
            round(run["completed_count"] / processed * 100, 2) if processed else None
        ),
        "average_seconds_per_photo": (
            round(average_seconds, 2) if average_seconds is not None else None
        ),
        "throughput_per_hour": (
            round(3600.0 / average_seconds, 1) if average_seconds and average_seconds > 0
            else None
        ),
        "estimated_remaining_seconds": (
            round(max(0, run["requested_count"] - processed) * average_seconds, 1)
            if average_seconds and run["status"] in {"queued", "running"}
            else None
        ),
        "total_attempts": timing["total_attempts"] or 0,
        "max_attempts": timing["max_attempts"] or 0,
        "backup_count": backup["backup_count"] or 0,
        "latest_backup_at": backup["latest_backup_at"],
    })
    return run


def ai_run_history(
    connection: sqlite3.Connection, limit: int = 20, offset: int = 0
) -> dict[str, Any]:
    total = connection.execute("SELECT COUNT(*) FROM ai_runs").fetchone()[0]
    rows = connection.execute(
        "SELECT * FROM ai_runs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    return {
        "count": total,
        "limit": limit,
        "offset": offset,
        "items": [_decorate_ai_run(connection, row) for row in rows],
    }


def ai_run_failures(
    connection: sqlite3.Connection, run_id: int, limit: int = 100
) -> list[dict[str, Any]]:
    exists = connection.execute("SELECT 1 FROM ai_runs WHERE id=?", (run_id,)).fetchone()
    if exists is None:
        raise ValueError(f"AI run {run_id} does not exist")
    return [dict(row) for row in connection.execute(
        """
        SELECT aa.id, aa.capture_id, c.stem, c.captured_at,
               aa.status, aa.selection_reason, aa.attempt_count,
               aa.error, aa.started_at, aa.finished_at
        FROM ai_analyses aa
        JOIN captures c ON c.id = aa.capture_id
        WHERE aa.run_id=? AND aa.status='failed'
        ORDER BY aa.id LIMIT ?
        """,
        (run_id, limit),
    )]


AUDIT_VISIBLE_PROBLEMS = 1
AUDIT_SHOOTING_ADVICE = 2
AUDIT_LIGHTROOM_SUGGESTIONS = 4
AUDIT_PHOTOSHOP_NEEDED = 8
AUDIT_EMPTY_PHOTOSHOP_REASON = 16
AUDIT_PARSE_ERROR = 32
AUDIT_SCHEMA_ERROR = 64
AUDIT_UNSAFE_ACTION = 128
AUDIT_OVERCONFIDENT = 256
AUDIT_LOW_CONFIDENCE = 512
AUDIT_RISK_MASK = (
    AUDIT_PARSE_ERROR | AUDIT_SCHEMA_ERROR | AUDIT_UNSAFE_ACTION
    | AUDIT_OVERCONFIDENT | AUDIT_LOW_CONFIDENCE
)


def model_result_audit_metadata(result: dict[str, Any]) -> dict[str, Any]:
    bits = 0
    flags: list[str] = []
    try:
        validate_model_result(result)
    except ValueError:
        bits |= AUDIT_SCHEMA_ERROR
        flags.append("structure_or_parameter_logic")
    result_text = json.dumps(result, ensure_ascii=False)
    if any(
        phrase in result_text
        for phrase in ("删除原片", "写入XMP", "修改EXIF", "上传到云", "上传云端", "覆盖原片")
    ):
        bits |= AUDIT_UNSAFE_ACTION
        flags.append("unsafe_action_mention")
    if result.get("visible_problems"):
        bits |= AUDIT_VISIBLE_PROBLEMS
    if result.get("shooting_advice"):
        bits |= AUDIT_SHOOTING_ADVICE
    if result.get("lightroom_suggestions"):
        bits |= AUDIT_LIGHTROOM_SUGGESTIONS
    if result.get("photoshop_needed") is True:
        bits |= AUDIT_PHOTOSHOP_NEEDED
    if not str(result.get("photoshop_reason") or "").strip():
        bits |= AUDIT_EMPTY_PHOTOSHOP_REASON
    confidence = result.get("overall_confidence")
    if isinstance(confidence, (int, float)):
        confidence = float(confidence)
        if confidence >= 0.99:
            bits |= AUDIT_OVERCONFIDENT
            flags.append("overconfident")
        elif confidence < 0.5:
            bits |= AUDIT_LOW_CONFIDENCE
            flags.append("low_confidence")
    else:
        confidence = None
    return {
        "bits": bits,
        "flags_json": json.dumps(flags, ensure_ascii=False),
        "confidence": confidence,
        "visible_problem_count": len(result.get("visible_problems") or []),
    }


def backfill_ai_audit_metadata(connection: sqlite3.Connection) -> int:
    total = 0
    while True:
        rows = connection.execute(
            """SELECT id, result_json FROM ai_analyses
               WHERE status='complete' AND result_json IS NOT NULL
                 AND audit_bits IS NULL
               ORDER BY id LIMIT 500"""
        ).fetchall()
        if not rows:
            return total
        updates = []
        for row in rows:
            try:
                metadata = model_result_audit_metadata(json.loads(row["result_json"]))
            except (TypeError, json.JSONDecodeError):
                metadata = {
                    "bits": AUDIT_PARSE_ERROR,
                    "flags_json": '["parse_error"]',
                    "confidence": None,
                    "visible_problem_count": 0,
                }
            updates.append((
                metadata["flags_json"], metadata["bits"], metadata["confidence"],
                metadata["visible_problem_count"], row["id"],
            ))
        connection.executemany(
            """UPDATE ai_analyses
               SET audit_flags_json=?, audit_bits=?, audit_confidence=?,
                   audit_visible_problem_count=?
               WHERE id=?""",
            updates,
        )
        connection.commit()
        total += len(updates)


def ai_result_audit(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute(
        f"""
        SELECT prompt_version, MAX(id) AS last_analysis_id,
               COUNT(*) AS result_count,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_PARSE_ERROR}) != 0
                        THEN 1 ELSE 0 END) AS parse_errors,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_SCHEMA_ERROR}) != 0
                        THEN 1 ELSE 0 END) AS schema_errors,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_UNSAFE_ACTION}) != 0
                        THEN 1 ELSE 0 END) AS unsafe_action_mentions,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_VISIBLE_PROBLEMS}) != 0
                        THEN 1 ELSE 0 END) AS with_visible_problems,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_SHOOTING_ADVICE}) != 0
                        THEN 1 ELSE 0 END) AS with_shooting_advice,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_LIGHTROOM_SUGGESTIONS}) != 0
                        THEN 1 ELSE 0 END) AS with_lightroom_suggestions,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_PHOTOSHOP_NEEDED}) != 0
                        THEN 1 ELSE 0 END) AS photoshop_needed,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_EMPTY_PHOTOSHOP_REASON}) != 0
                        THEN 1 ELSE 0 END) AS empty_photoshop_reason,
               SUM(CASE WHEN (COALESCE(audit_bits, 0) & {AUDIT_OVERCONFIDENT}) != 0
                        THEN 1 ELSE 0 END) AS overconfident,
               SUM(CASE WHEN audit_bits IS NULL OR (audit_bits & {AUDIT_RISK_MASK}) != 0
                        THEN 1 ELSE 0 END) AS risk_count,
               SUM(CASE WHEN audit_bits IS NULL THEN 1 ELSE 0 END)
                   AS pending_audit_metadata,
               SUM(CASE WHEN user_verdict IN ('accurate', 'partial', 'inaccurate')
                        THEN 1 ELSE 0 END) AS reviewed,
               SUM(CASE WHEN user_verdict='accurate' THEN 1 ELSE 0 END) AS accurate,
               SUM(CASE WHEN user_verdict='partial' THEN 1 ELSE 0 END) AS partial,
               SUM(CASE WHEN user_verdict='inaccurate' THEN 1 ELSE 0 END) AS inaccurate,
               COALESCE(SUM(audit_confidence), 0.0) AS confidence_total,
               COALESCE(SUM(CASE
                   WHEN (julianday(finished_at) - julianday(started_at)) >= 0
                   THEN (julianday(finished_at) - julianday(started_at)) * 86400.0
                   ELSE 0 END), 0.0) AS duration_total,
               SUM(CASE WHEN (julianday(finished_at) - julianday(started_at)) >= 0
                        THEN 1 ELSE 0 END) AS timed_count
        FROM ai_analyses
        WHERE status='complete' AND result_json IS NOT NULL
        GROUP BY prompt_version
        ORDER BY last_analysis_id DESC
        """
    ).fetchall()
    versions: list[dict[str, Any]] = []
    for row in rows:
        audit = dict(row)
        audit["verdicts"] = {
            "accurate": audit.pop("accurate"),
            "partial": audit.pop("partial"),
            "inaccurate": audit.pop("inaccurate"),
        }
        valid_count = audit["result_count"] - audit["parse_errors"]
        audit["average_confidence"] = (
            round(audit.pop("confidence_total") / valid_count, 3)
            if valid_count else None
        )
        audit["average_seconds_per_photo"] = (
            round(audit.pop("duration_total") / audit["timed_count"], 2)
            if audit["timed_count"] else None
        )
        versions.append(audit)
    return {"versions": versions, "latest": versions[0] if versions else None}


def _model_result_review_flags(result: dict[str, Any]) -> list[str]:
    return json.loads(model_result_audit_metadata(result)["flags_json"])


def ai_recent_results(
    connection: sqlite3.Connection, limit: int = 16
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT aa.id, aa.capture_id, aa.model_id, aa.prompt_version,
               aa.finished_at, aa.user_verdict, aa.user_note,
               c.stem, e.proposed_name AS event_name, e.category,
               qm.technical_score, aa.result_json
        FROM ai_analyses aa
        JOIN captures c ON c.id=aa.capture_id
        LEFT JOIN event_captures ec ON ec.capture_id=c.id
        LEFT JOIN events e ON e.id=ec.event_id
        LEFT JOIN quality_metrics qm ON qm.capture_id=c.id
        WHERE aa.status='complete' AND aa.result_json IS NOT NULL
        ORDER BY aa.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            result = json.loads(item.pop("result_json"))
        except (TypeError, json.JSONDecodeError):
            continue
        item.update({
            "subject_type": result.get("subject_type"),
            "quality_summary": result.get("quality_summary"),
            "visible_problem_count": len(result.get("visible_problems") or []),
            "overall_confidence": result.get("overall_confidence"),
            "photoshop_needed": result.get("photoshop_needed") is True,
            "review_flags": _model_result_review_flags(result),
            "thumbnail_url": f"/api/thumbnails/{item['capture_id']}?size=320",
        })
        results.append(item)
    return results


def ai_results_page(
    connection: sqlite3.Connection,
    limit: int = 48,
    offset: int = 0,
    prompt_version: str | None = None,
    verdict: str | None = None,
    audit: str | None = None,
    workflow: str | None = None,
) -> dict[str, Any]:
    if limit <= 0 or limit > 200 or offset < 0:
        raise ValueError("AI result page bounds are invalid")
    if verdict not in {None, "accurate", "partial", "inaccurate", "unreviewed"}:
        raise ValueError("AI result verdict filter is invalid")
    if audit not in {None, "risk", "sample"}:
        raise ValueError("AI result audit filter is invalid")
    if workflow not in {
        None, "open", "new", "reappeared", "pending", "confirmed",
        "ignored", "snoozed", "resolved",
    }:
        raise ValueError("AI result workflow filter is invalid")
    filters = ["aa.status='complete'", "aa.result_json IS NOT NULL"]
    parameters: list[Any] = []
    if prompt_version:
        filters.append("aa.prompt_version=?")
        parameters.append(prompt_version)
    if verdict == "unreviewed":
        filters.append("aa.user_verdict IS NULL")
    elif verdict:
        filters.append("aa.user_verdict=?")
        parameters.append(verdict)
    if audit == "risk":
        filters.append(
            f"(aa.audit_bits IS NULL OR (aa.audit_bits & {AUDIT_RISK_MASK}) != 0)"
        )
    elif audit == "sample":
        filters.append("aa.user_verdict IS NULL AND aa.id % 20 = 0")
    workflow_status = """CASE
        WHEN aa.user_verdict IS NOT NULL THEN 'confirmed'
        WHEN wis.subject_id IS NULL THEN 'new'
        WHEN wis.status='snoozed' AND wis.due_at <= CURRENT_TIMESTAMP THEN 'pending'
        ELSE wis.status END"""
    if workflow == "open":
        filters.append(f"({workflow_status}) IN ('new', 'reappeared', 'pending')")
    elif workflow:
        filters.append(f"({workflow_status}) = ?")
        parameters.append(workflow)
    where = " AND ".join(filters)
    from_sql = """FROM ai_analyses aa
        LEFT JOIN work_item_states wis
          ON wis.source_kind='ai' AND wis.subject_id=aa.id"""
    total = connection.execute(
        f"SELECT COUNT(*) {from_sql} WHERE {where}", parameters
    ).fetchone()[0]
    rows = connection.execute(
        f"""
        SELECT aa.id, aa.capture_id, aa.model_id, aa.prompt_version,
               aa.finished_at, aa.user_verdict, aa.user_note,
               aa.audit_flags_json, aa.audit_confidence,
               c.stem, e.proposed_name AS event_name, e.category,
               qm.technical_score, aa.result_json
               , ({workflow_status}) AS workflow_status,
               wis.due_at AS workflow_due_at,
               wis.reviewed_at AS workflow_reviewed_at,
               COALESCE(wis.first_seen_at, aa.finished_at) AS workflow_first_seen_at,
               MAX(0, CAST(julianday('now') - julianday(
                   COALESCE(wis.first_seen_at, aa.finished_at)
               ) AS INTEGER)) AS workflow_age_days
        {from_sql}
        JOIN captures c ON c.id=aa.capture_id
        LEFT JOIN event_captures ec ON ec.capture_id=c.id
        LEFT JOIN events e ON e.id=ec.event_id
        LEFT JOIN quality_metrics qm ON qm.capture_id=c.id
        WHERE {where}
        ORDER BY CASE ({workflow_status})
                     WHEN 'reappeared' THEN 0 WHEN 'new' THEN 1
                     WHEN 'pending' THEN 2 ELSE 3 END,
                 COALESCE(wis.first_seen_at, aa.finished_at) ASC,
                 aa.id DESC
        LIMIT ? OFFSET ?
        """,
        (*parameters, limit, offset),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            result = json.loads(item.pop("result_json"))
        except (TypeError, json.JSONDecodeError):
            continue
        audit_confidence = item.pop("audit_confidence")
        raw_audit_flags = item.pop("audit_flags_json")
        item.update({
            "subject_type": result.get("subject_type"),
            "quality_summary": result.get("quality_summary"),
            "visible_problem_count": len(result.get("visible_problems") or []),
            "overall_confidence": (
                audit_confidence
                if audit_confidence is not None else result.get("overall_confidence")
            ),
            "photoshop_needed": result.get("photoshop_needed") is True,
            "review_flags": (
                json.loads(raw_audit_flags)
                if raw_audit_flags else _model_result_review_flags(result)
            ),
            "thumbnail_url": f"/api/thumbnails/{item['capture_id']}?size=320",
        })
        items.append(item)
    return {"count": total, "limit": limit, "offset": offset, "items": items}


def ai_candidate_counts(
    connection: sqlite3.Connection,
    model_path: Path,
    model_variant: str | None = None,
) -> dict[str, int]:
    row = connection.execute(
        """
        SELECT COUNT(DISTINCT c.id) AS benchmark_available,
               COUNT(DISTINCT CASE WHEN
                   cr.auto_pick = 1
                   OR qm.technical_score < 55
                   OR (sgc.capture_id IS NULL AND c.id % 5 = 0)
               THEN c.id END) AS recommended_available
        FROM captures c
        JOIN event_captures ec ON ec.capture_id=c.id
        JOIN capture_files cf ON cf.capture_id=c.id AND cf.role='jpeg'
        JOIN files f ON f.id=cf.file_id AND f.present=1
        JOIN quality_metrics qm ON qm.capture_id=c.id AND qm.error IS NULL
        LEFT JOIN capture_reviews cr ON cr.capture_id=c.id
        LEFT JOIN similarity_group_captures sgc ON sgc.capture_id=c.id
        WHERE NOT EXISTS (
            SELECT 1 FROM ai_analyses previous
            WHERE previous.capture_id=c.id
              AND previous.model_id=?
              AND previous.prompt_version=?
              AND previous.status='complete'
        )
        """,
        (model_id(model_path, model_variant), PROMPT_VERSION),
    ).fetchone()
    return {
        "benchmark_available": int(row["benchmark_available"] or 0),
        "recommended_available": int(row["recommended_available"] or 0),
    }


def write_ai_run_report(
    connection: sqlite3.Connection, reports_path: Path, run_id: int
) -> dict[str, Any]:
    run_row = connection.execute(
        "SELECT * FROM ai_runs WHERE id=?", (run_id,)
    ).fetchone()
    if run_row is None:
        raise ValueError("模型任务不存在")
    run = _decorate_ai_run(connection, run_row)
    rows = connection.execute(
        """
        SELECT aa.id, aa.capture_id, c.stem, e.proposed_name AS event_name,
               e.category, aa.model_id, aa.prompt_version, aa.status,
               aa.selection_reason, aa.attempt_count, aa.error,
               aa.started_at, aa.finished_at, aa.user_verdict, aa.user_note,
               aa.reviewed_at, aa.result_json
        FROM ai_analyses aa
        JOIN captures c ON c.id=aa.capture_id
        LEFT JOIN event_captures ec ON ec.capture_id=c.id
        LEFT JOIN events e ON e.id=ec.event_id
        WHERE aa.run_id=? ORDER BY aa.id
        """,
        (run_id,),
    ).fetchall()
    analyses: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw_result = item.pop("result_json")
        try:
            result = json.loads(raw_result) if raw_result else None
        except json.JSONDecodeError:
            result = None
        item["result"] = result
        analyses.append(item)
        csv_rows.append({
            **{key: value for key, value in item.items() if key != "result"},
            "subject_type": result.get("subject_type") if result else None,
            "quality_summary": result.get("quality_summary") if result else None,
            "visible_problems": "；".join(
                str(problem.get("name", ""))
                for problem in (result.get("visible_problems") or [])
            ) if result else None,
            "shooting_advice": "；".join(
                str(advice.get("suggestion", ""))
                for advice in (result.get("shooting_advice") or [])
            ) if result else None,
            "lightroom_suggestions": "；".join(
                str(advice.get("adjustment", ""))
                for advice in (result.get("lightroom_suggestions") or [])
            ) if result else None,
            "photoshop_needed": result.get("photoshop_needed") if result else None,
            "overall_confidence": result.get("overall_confidence") if result else None,
        })
    reports_path.mkdir(parents=True, exist_ok=True)
    csv_name = f"ai-run-{run_id}-results.csv"
    json_name = f"ai-run-{run_id}-results.json"
    csv_path = reports_path / csv_name
    json_path = reports_path / json_name
    token = uuid4().hex
    csv_temporary = reports_path / f".{csv_name}.{token}.partial"
    json_temporary = reports_path / f".{json_name}.{token}.partial"
    fields = list(csv_rows[0]) if csv_rows else ["id", "capture_id", "status"]
    try:
        with csv_temporary.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(csv_rows)
        json_temporary.write_text(
            json.dumps({
                "generated_at": utc_now(),
                "local_only": True,
                "photos_mutated": False,
                "run": run,
                "result_audit": ai_result_audit(connection),
                "analyses": analyses,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        csv_temporary.replace(csv_path)
        json_temporary.replace(json_path)
    finally:
        csv_temporary.unlink(missing_ok=True)
        json_temporary.unlink(missing_ok=True)
    return {
        "run_id": run_id, "row_count": len(analyses),
        "csv_name": csv_name, "json_name": json_name,
    }


def ai_summary(
    connection: sqlite3.Connection,
    model_path: Path | None = None,
    model_variant: str | None = None,
) -> dict[str, Any]:
    counts = connection.execute(
        """
        SELECT
            COUNT(*) AS completed,
            COUNT(DISTINCT capture_id) AS analyzed_captures
        FROM ai_analyses WHERE status = 'complete'
        """
    ).fetchone()
    history = ai_run_history(connection, limit=8)
    latest_run = history["items"][0] if history["items"] else None
    return {
        "completed_analysis_count": counts["completed"],
        "analyzed_capture_count": counts["analyzed_captures"],
        "latest_run": latest_run,
        "recent_runs": history["items"],
        "latest_failures": (
            ai_run_failures(connection, latest_run["id"], limit=20)
            if latest_run and latest_run["failed_count"] else []
        ),
        "result_audit": ai_result_audit(connection),
        "recent_results": ai_recent_results(connection),
        "candidates": (
            ai_candidate_counts(connection, model_path, model_variant)
            if model_path is not None else None
        ),
    }


def quality_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS analyzed,
               SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
               ROUND(AVG(technical_score), 2) AS average_score,
               SUM(CASE WHEN technical_score < 55 AND error IS NULL THEN 1 ELSE 0 END) AS flagged
        FROM quality_metrics
        """
    ).fetchone()
    ratings = [dict(item) for item in connection.execute(
        """
        SELECT auto_rating AS rating, COUNT(*) AS count
        FROM capture_reviews WHERE auto_rating IS NOT NULL
        GROUP BY auto_rating ORDER BY auto_rating DESC
        """
    )]
    return {
        "analyzed": row["analyzed"],
        "errors": row["errors"] or 0,
        "average_score": row["average_score"],
        "flagged": row["flagged"] or 0,
        "recommended_picks": connection.execute(
            "SELECT COUNT(*) FROM capture_reviews WHERE auto_pick = 1"
        ).fetchone()[0],
        "ratings": ratings,
    }


def parse_model_json(response: str) -> dict[str, Any]:
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model response does not contain a JSON object")
    result = json.loads(text[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("Model response root must be an object")
    return result


def validate_model_result(result: dict[str, Any]) -> dict[str, Any]:
    required = {
        "subject_type": str,
        "quality_summary": str,
        "visible_problems": list,
        "shooting_advice": list,
        "lightroom_suggestions": list,
        "photoshop_needed": bool,
        "photoshop_reason": str,
        "overall_confidence": (int, float),
    }
    missing = [key for key in required if key not in result]
    if missing:
        raise ValueError("Model JSON is missing required fields: " + ", ".join(missing))
    invalid = [
        key for key, expected in required.items()
        if not isinstance(result[key], expected)
    ]
    if invalid:
        raise ValueError("Model JSON has invalid field types: " + ", ".join(invalid))
    allowed_subject_types = {"人像", "风景", "宠物", "家人", "星空", "其他"}
    if result["subject_type"] not in allowed_subject_types:
        raise ValueError("Model JSON subject_type is invalid")
    if not result["quality_summary"].strip():
        raise ValueError("Model JSON quality_summary cannot be empty")
    if "subject_tags" in result:
        subject_tags = result["subject_tags"]
        allowed_subject_tags = allowed_subject_types | {"建筑", "美食", "旅行", "纪实"}
        if not isinstance(subject_tags, list) or not 1 <= len(subject_tags) <= 3:
            raise ValueError("Model JSON subject_tags must contain 1 to 3 items")
        seen_subjects: set[str] = set()
        for tag in subject_tags:
            if not isinstance(tag, dict) or not isinstance(tag.get("name"), str):
                raise ValueError("Model JSON subject_tags item has invalid name")
            if tag["name"] not in allowed_subject_tags or tag["name"] in seen_subjects:
                raise ValueError("Model JSON subject_tags item is invalid or duplicated")
            if not isinstance(tag.get("confidence"), (int, float)):
                raise ValueError("Model JSON subject_tags item has invalid confidence")
            tag_confidence = float(tag["confidence"])
            if not 0.0 <= tag_confidence <= 1.0:
                raise ValueError("Model JSON subject_tags confidence is invalid")
            seen_subjects.add(tag["name"])
    if "edit_parameters" in result:
        if not isinstance(result["edit_parameters"], dict):
            raise ValueError("Model JSON edit_parameters must be an object")
        try:
            result["edit_parameters"] = normalize_edit_parameters(
                result["edit_parameters"]
            )
        except ValueError as exc:
            raise ValueError(f"Model JSON edit_parameters is invalid: {exc}") from exc
    confidence = float(result["overall_confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("Model JSON overall_confidence must be between 0 and 1")
    list_schemas: dict[str, dict[str, type | tuple[type, ...]]] = {
        "visible_problems": {
            "name": str, "severity": str, "evidence": str,
            "confidence": (int, float),
        },
        "shooting_advice": {
            "suggestion": str, "reason": str, "exif_basis": str,
        },
        "lightroom_suggestions": {
            "adjustment": str, "direction": str, "reason": str,
        },
    }
    for list_name, schema in list_schemas.items():
        items = result[list_name]
        if len(items) > 2:
            raise ValueError(f"Model JSON {list_name} must contain at most 2 items")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"Model JSON {list_name} items must be objects")
            for key, expected in schema.items():
                if key not in item or not isinstance(item[key], expected):
                    raise ValueError(
                        f"Model JSON {list_name} item has invalid field: {key}"
                    )
            if list_name == "visible_problems":
                severity = item["severity"].strip().lower()
                severity = {
                    "warning": "medium", "moderate": "medium",
                    "minor": "low", "severe": "high",
                }.get(severity, severity)
                item["severity"] = severity
                if severity not in {"low", "medium", "high"}:
                    raise ValueError("Model JSON problem severity is invalid")
                item_confidence = float(item["confidence"])
                if not 0.0 <= item_confidence <= 1.0:
                    raise ValueError("Model JSON problem confidence is invalid")

    problem_text = json.dumps(result["visible_problems"], ensure_ascii=False)
    advice_text = json.dumps(result["shooting_advice"], ensure_ascii=False)
    compact_advice = re.sub(r"\s+", "", advice_text).upper()
    if ("过曝" in problem_text or "高光" in problem_text) and "提高ISO" in compact_advice:
        raise ValueError("Model JSON contradicts overexposure by recommending higher ISO")
    if (
        ("高ISO" in problem_text.replace(" ", "") or "噪点" in problem_text)
        and any(term in compact_advice for term in ("提高ISO", "提升ISO", "增加ISO"))
    ):
        raise ValueError("Model JSON contradicts high-ISO noise by recommending higher ISO")
    if (
        result["subject_type"] in {"人像", "宠物", "家人"}
        and "三脚架" in advice_text
        and "静止" not in advice_text
    ):
        raise ValueError("Model JSON recommends a tripod for a potentially moving subject")
    for advice in result["shooting_advice"]:
        if "缩小光圈" not in advice["suggestion"]:
            continue
        aperture_match = re.search(
            r"(?:aperture|f/)\s*:?\s*(\d+(?:\.\d+)?)",
            advice["exif_basis"],
            flags=re.IGNORECASE,
        )
        if aperture_match and float(aperture_match.group(1)) >= 16:
            safe_suggestion = advice["suggestion"].replace("或缩小光圈", "").replace(
                "缩小光圈或", ""
            ).strip(" ，、或")
            if safe_suggestion and any(
                action in safe_suggestion
                for action in ("降低曝光补偿", "加快快门", "降低ISO", "使用ND")
            ):
                advice["suggestion"] = safe_suggestion
            else:
                raise ValueError(
                    "Model JSON recommends stopping down an already small aperture"
                )

    normalized = dict(result)
    normalized["overall_confidence"] = min(confidence, 0.95)
    if not normalized["photoshop_needed"] and not normalized["photoshop_reason"].strip():
        normalized["photoshop_reason"] = "不需要"
    return normalized


def _format_exposure_seconds(value: float | None) -> str | None:
    if value is None or value <= 0:
        return None
    seconds = float(value)
    if seconds < 1:
        denominator = max(1, round(1.0 / seconds))
        return f"1/{denominator} 秒"
    return f"{seconds:g} 秒"


def build_prompt(row: sqlite3.Row, issues: list[dict[str, Any]], equipment: str) -> str:
    exif = {
        "captured_at": row["captured_at"],
        "camera": row["camera_model"],
        "lens": row["lens_model"],
        "exposure_seconds": row["exposure_time"],
        "exposure_display": _format_exposure_seconds(row["exposure_time"]),
        "aperture": row["f_number"],
        "iso": row["iso"],
        "focal_length_mm": row["focal_length_mm"],
        "focal_length_35mm": row["focal_length_35mm"],
        "exposure_compensation": row["exposure_compensation"],
    }
    metrics = {
        "technical_score": row["technical_score"],
        "exposure_score": row["exposure_score"],
        "sharpness_score": row["sharpness_score"],
        "highlight_clip_pct": row["highlight_clip_pct"],
        "shadow_clip_pct": row["shadow_clip_pct"],
        "detected_issues": issues,
    }
    return f"""你是本地摄影复盘助手。请以画面可见内容为第一依据分析，但不要评价人物长相、身材或身份。
所有结论必须区分可见事实和推测；不知道拍摄意图时明确说明。第三方模型建议只供人工复核，不能决定删除。

摄影规则：
- 技术检测只是提示，不能压过画面语境。shadow_clip_pct 表示近黑像素，不是过曝；highlight_clip_pct 才表示近白像素。
- 月亮、星空、夜景和剪影中的大面积纯黑可能是正常背景；除非画面中本应可见的主体细节确实丢失，否则不要建议提亮黑色天空或阴影。
- 禁止仅因 shadow_clip_pct 较高就把“暗部占比高”或“背景过暗”列为画面问题；必须指出主体上实际丢失的细节，否则问题数组留空。
- exposure_seconds 必须换算正确，例如 0.005 秒是 1/200 秒，不是长曝光。
- 快门速度优先直接引用 exposure_display，不要自行把小数秒的分母照抄成倒数；单条建议不能并列方向相反的参数调整。
- 如果判断高光或亮部过曝，不得建议提高 ISO，也不能用“进光不足”解释该过曝问题。
- f 数越小光圈越大、进光越多；f 数越大光圈越小、进光越少。不要建议用更小光圈解决弱光或降低 ISO，除非有明确景深理由。
- 三脚架不能冻结移动人物或宠物；镜头防抖只能减轻相机抖动。不要仅凭参数断言画面模糊，必须有可见证据。
- 不要编造闭眼、失焦、噪点、背景问题或拍摄意图。没有可信问题时使用空数组。
- subject_type 只给一个兼容主类；subject_tags 按画面可见内容给 1–3 个互不重复的题材，不能写人物身份或姓名。
- edit_parameters 给出可选的全局预览起点；无明确依据时各项填 0，不要把预览滑块宣称为 Lightroom 精确数值。
- 输出务必精炼：总结不超过 60 个汉字；每个建议数组最多 2 项；每个字符串字段不超过 50 个汉字。
- 置信度必须校准在 0.50 到 0.95 之间，不能输出 1.0；证据有限时降低置信度。
- photoshop_needed 为 false 时，photoshop_reason 必须写“不需要”，不能留空。

器材资料：
{equipment}

EXIF：{json.dumps(exif, ensure_ascii=False)}
技术检测：{json.dumps(metrics, ensure_ascii=False)}

仅输出一个紧凑、完整、合法的 JSON 对象，不要 Markdown或额外解释，结构为：
{{
  "subject_type": "人像/风景/宠物/家人/星空/其他",
  "subject_tags": [{{"name":"人像/风景/宠物/家人/星空/建筑/美食/旅行/纪实/其他", "confidence":0.0}}],
  "quality_summary": "简短总结",
  "visible_problems": [{{"name":"问题", "severity":"low/medium/high", "evidence":"画面证据", "confidence":0.0}}],
  "shooting_advice": [{{"suggestion":"下次如何拍", "reason":"为什么", "exif_basis":"相关参数或无"}}],
  "lightroom_suggestions": [{{"adjustment":"调整项", "direction":"方向与大致幅度", "reason":"原因"}}],
  "edit_parameters": {{"exposure_ev":0.0,"contrast":0,"highlights":0,"shadows":0,"temperature":0,"tint":0,"saturation":0,"sharpness":0}},
  "photoshop_needed": false,
  "photoshop_reason": "不需要或具体用途",
  "overall_confidence": 0.0
}}
"""
