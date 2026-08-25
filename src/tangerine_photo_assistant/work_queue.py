from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .task_incidents import task_incident_summary

WORK_ITEM_STATUSES = frozenset(
    {"pending", "confirmed", "ignored", "snoozed", "resolved"}
)
WORK_ITEM_KINDS = frozenset({"quality", "ai"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def quality_fingerprint(
    algorithm_version: str,
    issue_json: str,
    *,
    error: str | None = None,
    source_file_id: int | None = None,
    size_bytes: int | None = None,
    modified_ns: int | None = None,
) -> str:
    if error:
        # Do not persist the raw decoder error: it can contain a local path and is
        # included in portable human-data backups. File identity and source state
        # are sufficient to reopen the item after the source changes.
        return f"{algorithm_version}:error:{source_file_id or ''}:{size_bytes or ''}:{modified_ns or ''}"
    return f"{algorithm_version}:{issue_json}"


def quality_fingerprint_sql(alias: str = "qm") -> str:
    return f"""CASE WHEN {alias}.error IS NOT NULL THEN
        ({alias}.algorithm_version || ':error:' ||
         COALESCE(CAST({alias}.source_file_id AS TEXT), '') || ':' ||
         COALESCE(CAST({alias}.size_bytes AS TEXT), '') || ':' ||
         COALESCE(CAST({alias}.modified_ns AS TEXT), ''))
        ELSE ({alias}.algorithm_version || ':' || {alias}.issue_json) END"""


def current_work_item_fingerprint(
    connection: sqlite3.Connection, source_kind: str, subject_id: int
) -> str:
    if source_kind == "quality":
        row = connection.execute(
            """SELECT algorithm_version, issue_json, error, source_file_id,
                      size_bytes, modified_ns
               FROM quality_metrics
               WHERE capture_id=? AND (error IS NOT NULL OR issue_json <> '[]')""",
            (subject_id,),
        ).fetchone()
        if row is None:
            raise ValueError("照片当前没有需要复核的技术检测项")
        return quality_fingerprint(
            row["algorithm_version"], row["issue_json"], error=row["error"],
            source_file_id=row["source_file_id"], size_bytes=row["size_bytes"],
            modified_ns=row["modified_ns"],
        )
    if source_kind == "ai":
        row = connection.execute(
            """SELECT c.capture_key, aa.model_id, aa.prompt_version
               FROM ai_analyses aa JOIN captures c ON c.id=aa.capture_id
               WHERE aa.id=? AND aa.status='complete' AND aa.result_json IS NOT NULL""",
            (subject_id,),
        ).fetchone()
        if row is None:
            raise ValueError("模型结果不存在或尚未完成")
        return f"ai:{row['capture_key']}:{row['model_id']}:{row['prompt_version']}"
    raise ValueError("不支持的待办来源")


def _source_seen_at(
    connection: sqlite3.Connection, source_kind: str, subject_id: int, fallback: str
) -> str:
    if source_kind == "quality":
        row = connection.execute(
            "SELECT computed_at FROM quality_metrics WHERE capture_id=?", (subject_id,)
        ).fetchone()
    else:
        row = connection.execute(
            "SELECT finished_at FROM ai_analyses WHERE id=?", (subject_id,)
        ).fetchone()
    return str(row[0]) if row is not None and row[0] else fallback


def save_work_item_state(
    connection: sqlite3.Connection,
    source_kind: str,
    subject_id: int,
    status: str,
    *,
    snooze_days: int | None = None,
    note: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    if source_kind not in WORK_ITEM_KINDS:
        raise ValueError("不支持的待办来源")
    if status not in WORK_ITEM_STATUSES:
        raise ValueError("待办状态无效")
    if status == "snoozed" and not snooze_days:
        snooze_days = 7
    if snooze_days is not None and not 1 <= snooze_days <= 365:
        raise ValueError("稍后处理天数必须在 1 到 365 之间")
    fingerprint = current_work_item_fingerprint(connection, source_kind, subject_id)
    now = _now()
    seen_at = _source_seen_at(connection, source_kind, subject_id, now)
    due_at = (
        (datetime.now(UTC) + timedelta(days=snooze_days)).isoformat()
        if status == "snoozed" and snooze_days else None
    )
    cleaned_note = note.strip() if note and note.strip() else None
    connection.execute(
        """
        INSERT INTO work_item_states(
            source_kind, subject_id, fingerprint, status,
            first_seen_at, last_seen_at, reviewed_at, due_at, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_kind, subject_id) DO UPDATE SET
            fingerprint=excluded.fingerprint,
            status=excluded.status,
            last_seen_at=excluded.last_seen_at,
            reviewed_at=excluded.reviewed_at,
            due_at=excluded.due_at,
            note=COALESCE(excluded.note, work_item_states.note),
            occurrence_count=work_item_states.occurrence_count +
                CASE WHEN work_item_states.fingerprint <> excluded.fingerprint
                     THEN 1 ELSE 0 END
        """,
        (
            source_kind, subject_id, fingerprint, status,
            seen_at, seen_at, now, due_at, cleaned_note,
        ),
    )
    if commit:
        connection.commit()
    return {
        "source_kind": source_kind,
        "subject_id": subject_id,
        "status": status,
        "due_at": due_at,
        "reviewed_at": now,
    }


def save_work_item_states(
    connection: sqlite3.Connection,
    source_kind: str,
    subject_ids: list[int],
    status: str,
    *,
    snooze_days: int | None = None,
) -> dict[str, Any]:
    if not subject_ids or len(subject_ids) > 200:
        raise ValueError("批量待办一次必须包含 1 到 200 项")
    unique_ids = list(dict.fromkeys(subject_ids))
    try:
        for subject_id in unique_ids:
            save_work_item_state(
                connection, source_kind, subject_id, status,
                snooze_days=snooze_days, commit=False,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"affected_count": len(unique_ids), "status": status}


def work_queue_summary(
    connection: sqlite3.Connection, daily_limit: int = 30
) -> dict[str, Any]:
    current_quality_fingerprint = quality_fingerprint_sql()
    quality = connection.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN wis.subject_id IS NULL THEN 1 ELSE 0 END) AS new_count,
            SUM(CASE WHEN qm.error IS NOT NULL THEN 1 ELSE 0 END) AS error_count,
            SUM(CASE WHEN wis.subject_id IS NOT NULL
                      AND wis.fingerprint <> ({current_quality_fingerprint})
                     THEN 1 ELSE 0 END) AS reappeared_count,
            MIN(COALESCE(wis.first_seen_at, qm.computed_at)) AS oldest_seen_at
        FROM quality_metrics qm
        LEFT JOIN work_item_states wis
          ON wis.source_kind='quality' AND wis.subject_id=qm.capture_id
        WHERE (qm.error IS NOT NULL OR qm.issue_json <> '[]')
          AND (
            wis.subject_id IS NULL
            OR wis.fingerprint <> ({current_quality_fingerprint})
            OR wis.status='pending'
            OR (wis.status='snoozed' AND julianday(wis.due_at) <= julianday('now'))
          )
        """
    ).fetchone()
    ai = connection.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN wis.subject_id IS NULL THEN 1 ELSE 0 END) AS new_count,
               MIN(COALESCE(wis.first_seen_at, aa.finished_at)) AS oldest_seen_at
        FROM ai_analyses aa
        LEFT JOIN work_item_states wis
          ON wis.source_kind='ai' AND wis.subject_id=aa.id
        WHERE aa.status='complete' AND aa.result_json IS NOT NULL
          AND aa.user_verdict IS NULL
          AND (aa.audit_bits IS NULL OR aa.audit_flags_json <> '[]')
          AND (
            wis.subject_id IS NULL OR wis.status='pending'
            OR (wis.status='snoozed' AND julianday(wis.due_at) <= julianday('now'))
          )
        """
    ).fetchone()
    integrity = connection.execute(
        """WITH latest_checks AS (
               SELECT ab.scope, MAX(ac.id) AS check_id
               FROM archive_checks ac
               JOIN archive_baselines ab ON ab.id=ac.baseline_id
               GROUP BY ab.scope
           ), current_findings AS (
               SELECT lc.scope, ac.checked_at, acd.relative_path, acd.status,
                      ii.fingerprint, ii.status AS saved_status, ii.due_at,
                      COALESCE(ii.first_seen_at, (
                          SELECT MIN(ac_seen.checked_at)
                          FROM archive_check_differences acd_seen
                          JOIN archive_checks ac_seen ON ac_seen.id=acd_seen.check_id
                          JOIN archive_baselines ab_seen ON ab_seen.id=ac_seen.baseline_id
                          WHERE ab_seen.scope=lc.scope
                            AND acd_seen.relative_path=acd.relative_path
                      )) AS first_seen_at,
                      ii.reappeared
               FROM latest_checks lc
               JOIN archive_checks ac ON ac.id=lc.check_id
               JOIN archive_check_differences acd ON acd.check_id=lc.check_id
               LEFT JOIN integrity_investigations ii
                 ON ii.scope=lc.scope AND ii.relative_path=acd.relative_path
           )
           SELECT COUNT(*) AS total,
                  SUM(CASE WHEN fingerprint IS NULL THEN 1 ELSE 0 END) AS new_count,
                  SUM(CASE WHEN reappeared=1 OR
                                    fingerprint <> ('integrity:' || status)
                           THEN 1 ELSE 0 END) AS reappeared_count,
                  MIN(COALESCE(first_seen_at, checked_at)) AS oldest_seen_at
           FROM current_findings
           WHERE fingerprint IS NULL
              OR reappeared=1
              OR fingerprint <> ('integrity:' || status)
              OR saved_status='pending'
              OR (saved_status='snoozed' AND julianday(due_at) <= julianday('now'))"""
    ).fetchone()
    task = task_incident_summary(connection)
    quality_total = int(quality["total"] or 0)
    ai_total = int(ai["total"] or 0)
    integrity_total = int(integrity["total"] or 0)
    task_total = int(task["open_count"] or 0)
    open_total = quality_total + ai_total + integrity_total + task_total
    daily_limit = max(5, min(int(daily_limit), 200))
    task_today = min(task_total, daily_limit)
    integrity_today = min(integrity_total, daily_limit - task_today)
    analysis_today = min(
        quality_total + ai_total, daily_limit - task_today - integrity_today
    )
    oldest_candidates = [
        str(value) for value in (
            quality["oldest_seen_at"], ai["oldest_seen_at"],
            integrity["oldest_seen_at"], task["oldest_seen_at"],
        )
        if value
    ]
    oldest_seen_at = min(oldest_candidates) if oldest_candidates else None
    oldest_age_days = None
    if oldest_seen_at:
        try:
            parsed = datetime.fromisoformat(oldest_seen_at)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            oldest_age_days = max(0, (datetime.now(UTC) - parsed).days)
        except ValueError:
            oldest_age_days = None
    return {
        "open_count": open_total,
        "today_count": min(daily_limit, open_total),
        "analysis_today_count": analysis_today,
        "integrity_today_count": integrity_today,
        "task_today_count": task_today,
        "daily_limit": daily_limit,
        "estimated_minutes": min(daily_limit, open_total) * 2,
        "oldest_seen_at": oldest_seen_at,
        "oldest_age_days": oldest_age_days,
        "quality": {
            "open_count": quality_total,
            "new_count": int(quality["new_count"] or 0),
            "reappeared_count": int(quality["reappeared_count"] or 0),
            "error_count": int(quality["error_count"] or 0),
        },
        "ai": {
            "open_count": ai_total,
            "new_count": int(ai["new_count"] or 0),
        },
        "integrity": {
            "open_count": integrity_total,
            "new_count": int(integrity["new_count"] or 0),
            "reappeared_count": int(integrity["reappeared_count"] or 0),
        },
        "task": {
            "open_count": task_total,
            "new_count": int(task["new_count"] or 0),
            "reappeared_count": int(task["reappeared_count"] or 0),
        },
    }
