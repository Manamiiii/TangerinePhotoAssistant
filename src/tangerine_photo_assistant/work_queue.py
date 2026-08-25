from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

WORK_ITEM_STATUSES = frozenset(
    {"pending", "confirmed", "ignored", "snoozed", "resolved"}
)
WORK_ITEM_KINDS = frozenset({"quality", "ai"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def quality_fingerprint(algorithm_version: str, issue_json: str) -> str:
    return f"{algorithm_version}:{issue_json}"


def current_work_item_fingerprint(
    connection: sqlite3.Connection, source_kind: str, subject_id: int
) -> str:
    if source_kind == "quality":
        row = connection.execute(
            """SELECT algorithm_version, issue_json
               FROM quality_metrics WHERE capture_id=? AND issue_json <> '[]'""",
            (subject_id,),
        ).fetchone()
        if row is None:
            raise ValueError("照片当前没有需要复核的技术检测项")
        return quality_fingerprint(row["algorithm_version"], row["issue_json"])
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
    quality = connection.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN wis.subject_id IS NULL THEN 1 ELSE 0 END) AS new_count,
            SUM(CASE WHEN wis.subject_id IS NOT NULL
                      AND wis.fingerprint <> (qm.algorithm_version || ':' || qm.issue_json)
                     THEN 1 ELSE 0 END) AS reappeared_count
        FROM quality_metrics qm
        LEFT JOIN work_item_states wis
          ON wis.source_kind='quality' AND wis.subject_id=qm.capture_id
        WHERE qm.error IS NULL AND qm.issue_json <> '[]'
          AND (
            wis.subject_id IS NULL
            OR wis.fingerprint <> (qm.algorithm_version || ':' || qm.issue_json)
            OR wis.status='pending'
            OR (wis.status='snoozed' AND wis.due_at <= CURRENT_TIMESTAMP)
          )
        """
    ).fetchone()
    ai = connection.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN wis.subject_id IS NULL THEN 1 ELSE 0 END) AS new_count
        FROM ai_analyses aa
        LEFT JOIN work_item_states wis
          ON wis.source_kind='ai' AND wis.subject_id=aa.id
        WHERE aa.status='complete' AND aa.result_json IS NOT NULL
          AND aa.user_verdict IS NULL
          AND (aa.audit_bits IS NULL OR aa.audit_flags_json <> '[]')
          AND (
            wis.subject_id IS NULL OR wis.status='pending'
            OR (wis.status='snoozed' AND wis.due_at <= CURRENT_TIMESTAMP)
          )
        """
    ).fetchone()
    quality_total = int(quality["total"] or 0)
    ai_total = int(ai["total"] or 0)
    daily_limit = max(5, min(int(daily_limit), 200))
    return {
        "open_count": quality_total + ai_total,
        "today_count": min(daily_limit, quality_total + ai_total),
        "daily_limit": daily_limit,
        "estimated_minutes": min(daily_limit, quality_total + ai_total) * 2,
        "quality": {
            "open_count": quality_total,
            "new_count": int(quality["new_count"] or 0),
            "reappeared_count": int(quality["reappeared_count"] or 0),
        },
        "ai": {
            "open_count": ai_total,
            "new_count": int(ai["new_count"] or 0),
        },
    }
