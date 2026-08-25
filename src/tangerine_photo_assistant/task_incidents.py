from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

TASK_INCIDENT_STATUSES = frozenset(
    {"pending", "confirmed", "ignored", "snoozed", "resolved"}
)
TASK_KIND_LABELS = {
    "scan": "图库更新",
    "visual": "相似组分析",
    "quality": "技术检测",
    "detail": "详情补全",
    "ai": "本地模型分析",
    "migration": "图库迁移",
    "system": "后台任务",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_kind(task_kind: str) -> str:
    clean_kind = task_kind.strip().lower()
    if clean_kind not in TASK_KIND_LABELS:
        raise ValueError("后台任务类型无效")
    return clean_kind


def record_task_incident(
    connection: sqlite3.Connection,
    task_kind: str,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    """Record one safe task failure, converging repeated failures by task family."""
    clean_kind = _validate_kind(task_kind)
    clean_code = error_code.strip()[:80] or "TaskFailure"
    clean_message = message.strip()[:160] or "后台任务失败"
    fingerprint = f"{clean_kind}:{clean_code}"
    now = _now()
    connection.execute(
        """INSERT INTO task_incidents(
               task_kind, fingerprint, error_code, message, status,
               first_seen_at, last_seen_at, occurrence_count, reappeared
           ) VALUES (?, ?, ?, ?, 'pending', ?, ?, 1, 0)
           ON CONFLICT(task_kind) DO UPDATE SET
               fingerprint=excluded.fingerprint,
               error_code=excluded.error_code,
               message=excluded.message,
               status=CASE
                   WHEN task_incidents.fingerprint <> excluded.fingerprint
                     OR task_incidents.status IN ('confirmed','ignored','resolved')
                   THEN 'pending' ELSE task_incidents.status END,
               first_seen_at=CASE
                   WHEN task_incidents.fingerprint <> excluded.fingerprint
                   THEN excluded.first_seen_at ELSE task_incidents.first_seen_at END,
               last_seen_at=excluded.last_seen_at,
               reviewed_at=CASE
                   WHEN task_incidents.fingerprint <> excluded.fingerprint
                   THEN NULL ELSE task_incidents.reviewed_at END,
               due_at=CASE
                   WHEN task_incidents.fingerprint <> excluded.fingerprint
                     OR task_incidents.status IN ('confirmed','ignored','resolved')
                   THEN NULL ELSE task_incidents.due_at END,
               occurrence_count=task_incidents.occurrence_count + CASE
                   WHEN task_incidents.fingerprint <> excluded.fingerprint
                     OR task_incidents.status IN ('confirmed','ignored','resolved')
                   THEN 1 ELSE 0 END,
               reappeared=CASE
                   WHEN task_incidents.status IN ('confirmed','ignored','resolved')
                   THEN 1 ELSE 0 END""",
        (clean_kind, fingerprint, clean_code, clean_message, now, now),
    )
    connection.commit()
    return {"task_kind": clean_kind, "fingerprint": fingerprint}


def resolve_task_incident(
    connection: sqlite3.Connection, task_kind: str
) -> bool:
    clean_kind = _validate_kind(task_kind)
    cursor = connection.execute(
        """UPDATE task_incidents
           SET status='resolved', reviewed_at=?, due_at=NULL, reappeared=0
           WHERE task_kind=? AND status <> 'resolved'""",
        (_now(), clean_kind),
    )
    connection.commit()
    return cursor.rowcount > 0


def save_task_incident_state(
    connection: sqlite3.Connection,
    task_kind: str,
    status: str,
    *,
    snooze_days: int | None = None,
) -> dict[str, Any]:
    clean_kind = _validate_kind(task_kind)
    if status not in TASK_INCIDENT_STATUSES:
        raise ValueError("后台任务处理状态无效")
    if status == "snoozed" and not snooze_days:
        snooze_days = 7
    if snooze_days is not None and not 1 <= snooze_days <= 365:
        raise ValueError("稍后处理天数必须在 1 到 365 之间")
    due_at = (
        (datetime.now(UTC) + timedelta(days=snooze_days)).isoformat()
        if status == "snoozed" and snooze_days else None
    )
    cursor = connection.execute(
        """UPDATE task_incidents
           SET status=?, reviewed_at=?, due_at=?, reappeared=0
           WHERE task_kind=?""",
        (status, _now(), due_at, clean_kind),
    )
    if cursor.rowcount == 0:
        raise ValueError("后台任务异常不存在")
    connection.commit()
    return {"task_kind": clean_kind, "status": status, "due_at": due_at}


def task_incidents_page(
    connection: sqlite3.Connection,
    workflow: str = "open",
) -> dict[str, Any]:
    if workflow not in {
        "all", "open", "new", "reappeared", "pending", "confirmed",
        "ignored", "snoozed", "resolved",
    }:
        raise ValueError("后台任务调查状态无效")
    workflow_sql = """CASE
        WHEN reappeared=1 THEN 'reappeared'
        WHEN reviewed_at IS NULL THEN 'new'
        WHEN status='snoozed' AND julianday(due_at) <= julianday('now') THEN 'pending'
        ELSE status END"""
    where = ""
    parameters: list[Any] = []
    if workflow == "open":
        where = f"WHERE ({workflow_sql}) IN ('new','reappeared','pending')"
    elif workflow != "all":
        where = f"WHERE ({workflow_sql})=?"
        parameters.append(workflow)
    rows = connection.execute(
        f"""SELECT task_kind, error_code, message, status, first_seen_at,
                   last_seen_at, due_at, occurrence_count,
                   ({workflow_sql}) AS workflow_status,
                   MAX(0, CAST(julianday('now') - julianday(first_seen_at)
                       AS INTEGER)) AS workflow_age_days
            FROM task_incidents {where}
            ORDER BY CASE ({workflow_sql})
                         WHEN 'reappeared' THEN 0 WHEN 'new' THEN 1
                         WHEN 'pending' THEN 2 ELSE 3 END,
                     first_seen_at ASC, task_kind""",
        parameters,
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["task_label"] = TASK_KIND_LABELS.get(item["task_kind"], "后台任务")
        items.append(item)
    return {"count": len(items), "items": items}


def task_incident_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    page = task_incidents_page(connection, "open")
    items = page["items"]
    return {
        "open_count": page["count"],
        "new_count": sum(item["workflow_status"] == "new" for item in items),
        "reappeared_count": sum(
            item["workflow_status"] == "reappeared" for item in items
        ),
        "oldest_seen_at": min(
            (item["first_seen_at"] for item in items), default=None
        ),
    }
