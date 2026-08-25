from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from typing import Any

from .database import transaction
from .inventory import utc_now


def _eligible_rows(
    connection: sqlite3.Connection,
    album_id: int | None = None,
    group_ids: list[int] | None = None,
    limit: int = 200,
) -> list[sqlite3.Row]:
    filters = []
    parameters: list[Any] = []
    if album_id is not None:
        filters.append("b.event_id=?")
        parameters.append(album_id)
    if group_ids:
        filters.append(f"sg.id IN ({','.join('?' for _ in group_ids)})")
        parameters.extend(group_ids)
    extra_where = " AND " + " AND ".join(filters) if filters else ""
    return connection.execute(
        f"""SELECT sg.id, sg.capture_count, sg.max_adjacent_hamming,
                   b.event_id, e.proposed_name AS event_name, b.start_at,
                   MAX(CASE WHEN cr.auto_pick=1 THEN c.id END)
                       AS recommended_capture_id,
                   MAX(CASE WHEN cr.auto_pick=1 THEN c.stem END)
                       AS recommended_stem,
                   MAX(CASE WHEN cr.auto_pick=1 THEN qm.technical_score END)
                       AS recommended_score,
                   MAX(CASE WHEN cr.auto_pick=1
                            THEN COALESCE(cr.user_reject,0) END)
                       AS recommended_reject,
                   MAX(CASE WHEN COALESCE(cr.auto_pick,0)=0
                            THEN qm.technical_score END) AS runner_up_score,
                   SUM(CASE WHEN qm.technical_score IS NOT NULL THEN 1 ELSE 0 END)
                       AS analyzed_count,
                   SUM(CASE WHEN COALESCE(cr.auto_pick,0)=1 THEN 1 ELSE 0 END)
                       AS auto_pick_count,
                   SUM(CASE WHEN COALESCE(cr.user_pick,0)=1 THEN 1 ELSE 0 END)
                       AS pick_count,
                   SUM(CASE WHEN COALESCE(cr.user_reject,0)=1 THEN 1 ELSE 0 END)
                       AS reject_count,
                   SUM(CASE WHEN sgo.capture_id IS NOT NULL THEN 1 ELSE 0 END)
                       AS override_count,
                   GROUP_CONCAT(sgc.capture_id) AS capture_ids
              FROM similarity_groups sg
              JOIN bursts b ON b.id=sg.burst_id
              JOIN events e ON e.id=b.event_id
              JOIN similarity_group_captures sgc ON sgc.group_id=sg.id
              JOIN captures c ON c.id=sgc.capture_id
              LEFT JOIN quality_metrics qm
                ON qm.capture_id=c.id AND qm.error IS NULL
              LEFT JOIN capture_reviews cr ON cr.capture_id=c.id
              LEFT JOIN similarity_group_overrides sgo ON sgo.capture_id=c.id
             WHERE 1=1 {extra_where}
             GROUP BY sg.id
            HAVING pick_count=0 AND reject_count<sg.capture_count
               AND auto_pick_count=1 AND analyzed_count=sg.capture_count
               AND recommended_reject=0
               AND override_count=0 AND max_adjacent_hamming<=8
               AND recommended_score>=75
               AND (runner_up_score IS NULL
                    OR recommended_score-runner_up_score>=5)
             ORDER BY b.start_at, sg.id LIMIT ?""",
        (*parameters, limit),
    ).fetchall()


def low_risk_preview(
    connection: sqlite3.Connection,
    album_id: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if album_id is not None and album_id <= 0:
        raise ValueError("相册无效")
    if not 1 <= limit <= 200:
        raise ValueError("预览组数必须在 1 到 200 之间")
    rows = _eligible_rows(connection, album_id=album_id, limit=limit)
    items = []
    for row in rows:
        item = dict(row)
        item.pop("capture_ids", None)
        item["score_margin"] = round(
            float(item["recommended_score"])
            - float(item["runner_up_score"] or item["recommended_score"]), 1
        )
        item["thumbnail_url"] = (
            f"/api/thumbnails/{item['recommended_capture_id']}?size=320"
        )
        items.append(item)
    return {
        "group_count": len(items),
        "capture_count": sum(int(item["capture_count"]) for item in items),
        "audit_count": math.ceil(len(items) * 0.05) if items else 0,
        "items": items,
    }


def apply_low_risk_batch(
    connection: sqlite3.Connection,
    group_ids: list[int],
    album_id: int | None = None,
) -> dict[str, Any]:
    ordered_ids = list(dict.fromkeys(group_ids))
    if not ordered_ids or len(ordered_ids) > 200:
        raise ValueError("请选择 1 到 200 个低风险相似组")
    rows = _eligible_rows(
        connection, album_id=album_id, group_ids=ordered_ids, limit=len(ordered_ids)
    )
    if {int(row["id"]) for row in rows} != set(ordered_ids):
        raise ValueError("预览已过期，部分相似组不再满足低风险条件")
    before = []
    after = []
    for row in rows:
        capture_id = int(row["recommended_capture_id"])
        review = connection.execute(
            "SELECT user_pick,user_reject FROM capture_reviews WHERE capture_id=?",
            (capture_id,),
        ).fetchone()
        before.append({
            "capture_id": capture_id,
            "user_pick": review["user_pick"] if review else None,
            "user_reject": int(review["user_reject"] or 0) if review else 0,
        })
        after.append({"capture_id": capture_id, "user_pick": 1, "user_reject": 0})
    audit_count = math.ceil(len(rows) * 0.05)
    audit_representatives = {
        int(row["recommended_capture_id"])
        for row in sorted(
            rows,
            key=lambda item: hashlib.sha256(
                str(item["capture_ids"]).encode("utf-8")
            ).hexdigest(),
        )[:audit_count]
    }
    now = utc_now()
    with transaction(connection):
        cursor = connection.execute(
            """INSERT INTO similarity_review_batches(
                   album_id,mode,group_count,capture_count,before_json,after_json,
                   status,created_at
               ) VALUES (?,'low_risk_accept',?,?,?,?, 'applied',?)""",
            (
                album_id, len(rows), sum(int(row["capture_count"]) for row in rows),
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False), now,
            ),
        )
        batch_id = int(cursor.lastrowid)
        for item in after:
            updated = connection.execute(
                """UPDATE capture_reviews SET user_pick=1,user_reject=0,updated_at=?
                   WHERE capture_id=? AND COALESCE(user_pick,0)=0
                     AND user_reject=0""",
                (now, item["capture_id"]),
            )
            if updated.rowcount != 1:
                raise ValueError("预览已过期，技术推荐已被人工修改")
        connection.executemany(
            """INSERT INTO similarity_review_batch_groups(
                   batch_id,representative_capture_id,capture_ids_json,confidence,
                   requires_audit,audit_status)
               VALUES (?,?,?,'high',?,'pending')""",
            [
                (
                    batch_id, int(row["recommended_capture_id"]),
                    json.dumps(
                        [int(value) for value in str(row["capture_ids"]).split(",")]
                    ),
                    int(int(row["recommended_capture_id"]) in audit_representatives),
                )
                for row in rows
            ],
        )
    return {
        "batch_id": batch_id, "group_count": len(rows),
        "capture_count": sum(int(row["capture_count"]) for row in rows),
        "audit_count": audit_count,
    }


def list_review_batches(connection: sqlite3.Connection, limit: int = 20) -> dict[str, Any]:
    rows = connection.execute(
        """SELECT b.*, e.proposed_name AS album_name,
                  SUM(CASE WHEN bg.requires_audit=1 THEN 1 ELSE 0 END) AS audit_count,
                  SUM(CASE WHEN bg.requires_audit=1 AND bg.audit_status='pending'
                           THEN 1 ELSE 0 END) AS pending_audit_count
             FROM similarity_review_batches b
             LEFT JOIN events e ON e.id=b.album_id
             LEFT JOIN similarity_review_batch_groups bg ON bg.batch_id=b.id
            GROUP BY b.id ORDER BY b.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        after = json.loads(item.pop("after_json"))
        item.pop("before_json")
        item["can_undo"] = item["status"] == "applied" and all(
            (current := connection.execute(
                "SELECT user_pick,user_reject FROM capture_reviews WHERE capture_id=?",
                (entry["capture_id"],),
            ).fetchone()) is not None
            and int(current["user_pick"] or 0) == 1
            and int(current["user_reject"] or 0) == 0
            for entry in after
        )
        items.append(item)
    return {"items": items}


def undo_review_batch(connection: sqlite3.Connection, batch_id: int) -> dict[str, Any]:
    row = connection.execute(
        """SELECT before_json,after_json,status FROM similarity_review_batches
           WHERE id=?""", (batch_id,),
    ).fetchone()
    if row is None:
        raise ValueError("批量处理记录不存在")
    if row["status"] != "applied":
        raise ValueError("这批处理已经撤销")
    before = json.loads(row["before_json"])
    after = json.loads(row["after_json"])
    for entry in after:
        current = connection.execute(
            "SELECT user_pick,user_reject FROM capture_reviews WHERE capture_id=?",
            (entry["capture_id"],),
        ).fetchone()
        if current is None or int(current["user_pick"] or 0) != 1 \
                or int(current["user_reject"] or 0) != 0:
            raise ValueError("部分照片此后已人工修改，不能覆盖新结论")
    now = utc_now()
    with transaction(connection):
        for entry in before:
            connection.execute(
                """UPDATE capture_reviews SET user_pick=?,user_reject=?,updated_at=?
                   WHERE capture_id=?""",
                (entry["user_pick"], entry["user_reject"], now, entry["capture_id"]),
            )
        connection.execute(
            """UPDATE similarity_review_batches SET status='undone',undone_at=?
               WHERE id=?""", (now, batch_id),
        )
    return {"batch_id": batch_id, "status": "undone", "restored_count": len(before)}


def list_audit_groups(connection: sqlite3.Connection, limit: int = 100) -> dict[str, Any]:
    rows = connection.execute(
        """SELECT bg.batch_id,bg.representative_capture_id,bg.audit_status,
                  bg.audited_at,bg.note,b.created_at,
                  COALESCE(e.proposed_name,
                    (SELECT MIN(member_album.proposed_name)
                       FROM event_captures member_link
                       JOIN events member_album ON member_album.id=member_link.event_id
                      WHERE member_link.capture_id=bg.representative_capture_id))
                    AS album_name,
                  c.stem,
                  (SELECT sgc.group_id FROM similarity_group_captures sgc
                   WHERE sgc.capture_id=bg.representative_capture_id LIMIT 1) AS group_id
             FROM similarity_review_batch_groups bg
             JOIN similarity_review_batches b ON b.id=bg.batch_id
             JOIN captures c ON c.id=bg.representative_capture_id
             LEFT JOIN events e ON e.id=b.album_id
            WHERE bg.requires_audit=1 AND b.status='applied'
            ORDER BY CASE bg.audit_status WHEN 'pending' THEN 0 ELSE 1 END,
                     b.id DESC LIMIT ?""", (limit,),
    ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["thumbnail_url"] = (
            f"/api/thumbnails/{item['representative_capture_id']}?size=320"
        )
    return {"items": items}


def save_audit_result(
    connection: sqlite3.Connection,
    batch_id: int,
    capture_id: int,
    status: str,
    note: str | None = None,
) -> dict[str, Any]:
    if status not in {"confirmed", "problem"}:
        raise ValueError("抽检结论无效")
    clean_note = note.strip()[:500] if note and note.strip() else None
    now = utc_now()
    cursor = connection.execute(
        """UPDATE similarity_review_batch_groups
              SET audit_status=?,audited_at=?,note=?
            WHERE batch_id=? AND representative_capture_id=? AND requires_audit=1""",
        (status, now, clean_note, batch_id, capture_id),
    )
    if not cursor.rowcount:
        raise ValueError("抽检记录不存在")
    connection.commit()
    return {"batch_id": batch_id, "capture_id": capture_id, "status": status}
