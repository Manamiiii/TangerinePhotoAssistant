from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime

from .database import transaction
from .inventory import utc_now


class CaptureReviewError(ValueError):
    pass


class CaptureReviewNotFoundError(CaptureReviewError):
    pass


SELECTION_REASONS = frozenset({"动作差异", "表情差异", "构图差异", "关键瞬间", "叙事补充"})


def batch_update_capture_reviews(
    connection: sqlite3.Connection,
    capture_ids: Sequence[int],
    *,
    rating: int | None = None,
    selection: str | None = None,
) -> int:
    unique_ids = list(dict.fromkeys(int(capture_id) for capture_id in capture_ids))
    if not unique_ids or len(unique_ids) > 500:
        raise CaptureReviewError("每次必须选择 1 到 500 张照片")
    if rating is not None and not 0 <= rating <= 5:
        raise CaptureReviewError("批量星级必须在 0 到 5 之间")
    if selection not in {None, "picked", "rejected", "clear"}:
        raise CaptureReviewError("批量选片结论无效")
    if rating is None and selection is None:
        raise CaptureReviewError("没有需要应用的批量评价")
    placeholders = ",".join("?" for _ in unique_ids)
    existing_ids = {
        int(row[0])
        for row in connection.execute(
            f"SELECT id FROM captures WHERE id IN ({placeholders})", unique_ids
        )
    }
    missing = [capture_id for capture_id in unique_ids if capture_id not in existing_ids]
    if missing:
        raise CaptureReviewNotFoundError(f"拍摄单元不存在：{missing[:5]}")

    update_rating = rating is not None
    stored_rating = None if rating == 0 else rating
    update_selection = selection is not None
    stored_pick = 1 if selection == "picked" else 0
    stored_reject = 1 if selection == "rejected" else 0
    clear_reasons = selection in {"rejected", "clear"}
    now = utc_now()
    with transaction(connection):
        connection.executemany(
            """INSERT INTO capture_reviews(
                   capture_id, user_rating, user_pick, user_reject, user_note,
                   selection_reason_json, updated_at
               ) VALUES (?, ?, ?, ?, NULL, ?, ?)
               ON CONFLICT(capture_id) DO UPDATE SET
                   user_rating=CASE WHEN ? THEN excluded.user_rating ELSE capture_reviews.user_rating END,
                   user_pick=CASE WHEN ? THEN excluded.user_pick ELSE capture_reviews.user_pick END,
                   user_reject=CASE WHEN ? THEN excluded.user_reject ELSE capture_reviews.user_reject END,
                   selection_reason_json=CASE WHEN ? THEN '[]' ELSE capture_reviews.selection_reason_json END,
                   updated_at=excluded.updated_at""",
            [
                (
                    capture_id,
                    stored_rating,
                    stored_pick if update_selection else None,
                    stored_reject,
                    "[]" if clear_reasons else None,
                    now,
                    update_rating,
                    update_selection,
                    update_selection,
                    clear_reasons,
                )
                for capture_id in unique_ids
            ],
        )
    return len(unique_ids)


def begin_selection_session(
    connection: sqlite3.Connection, group_id: int
) -> dict[str, object]:
    if connection.execute(
        "SELECT 1 FROM similarity_groups WHERE id=?", (group_id,)
    ).fetchone() is None:
        raise CaptureReviewNotFoundError("相似组不存在")
    now = utc_now()
    row = connection.execute(
        """SELECT * FROM selection_sessions
           WHERE group_id=? AND status='active' ORDER BY id DESC LIMIT 1""",
        (group_id,),
    ).fetchone()
    if row is not None:
        elapsed = (datetime.fromisoformat(now) - datetime.fromisoformat(row["last_activity_at"])).total_seconds()
        if elapsed <= 1800:
            return dict(row)
        connection.execute(
            "UPDATE selection_sessions SET status='abandoned' WHERE id=?", (row["id"],)
        )
    cursor = connection.execute(
        """INSERT INTO selection_sessions(group_id, started_at, last_activity_at)
           VALUES (?, ?, ?)""",
        (group_id, now, now),
    )
    connection.commit()
    return dict(connection.execute(
        "SELECT * FROM selection_sessions WHERE id=?", (cursor.lastrowid,)
    ).fetchone())


def _record_selection_session_action(
    connection: sqlite3.Connection,
    session_id: int,
    capture_id: int,
    before: tuple[bool, bool],
    after: tuple[bool, bool],
) -> None:
    if before == after:
        return
    row = connection.execute(
        """SELECT * FROM selection_sessions WHERE id=? AND status='active'
           AND EXISTS(SELECT 1 FROM similarity_group_captures sgc
                      WHERE sgc.group_id=selection_sessions.group_id
                        AND sgc.capture_id=?)""",
        (session_id, capture_id),
    ).fetchone()
    if row is None:
        return
    now = utc_now()
    elapsed = max(0.0, min(300.0, (
        datetime.fromisoformat(now) - datetime.fromisoformat(row["last_activity_at"])
    ).total_seconds()))
    resolved = connection.execute(
        """SELECT MAX(CASE WHEN COALESCE(cr.user_pick, 0)=1 THEN 1 ELSE 0 END),
                  MIN(CASE WHEN COALESCE(cr.user_reject, 0)=1 THEN 1 ELSE 0 END)
           FROM similarity_group_captures sgc
           LEFT JOIN capture_reviews cr ON cr.capture_id=sgc.capture_id
           WHERE sgc.group_id=?""",
        (row["group_id"],),
    ).fetchone()
    completed = bool(resolved[0] or resolved[1])
    connection.execute(
        """UPDATE selection_sessions
           SET last_activity_at=?, active_seconds=active_seconds+?,
               decision_count=decision_count+1,
               status=?, completed_at=?
           WHERE id=?""",
        (now, elapsed, "completed" if completed else "active", now if completed else None, session_id),
    )


def _normalize_selection_reasons(reasons: Sequence[str] | None) -> list[str] | None:
    if reasons is None:
        return None
    normalized = list(dict.fromkeys(" ".join(str(reason).split()) for reason in reasons))
    if any(not reason or reason not in SELECTION_REASONS for reason in normalized):
        raise CaptureReviewError("选片保留理由无效")
    return normalized


def save_capture_review(
    connection: sqlite3.Connection,
    capture_id: int,
    *,
    user_rating: int | None,
    user_pick: bool | None,
    user_reject: bool,
    user_note: str | None,
    selection_reasons: Sequence[str] | None = None,
    selection_session_id: int | None = None,
) -> None:
    if user_rating is not None and not 1 <= user_rating <= 5:
        raise CaptureReviewError("人工星级必须在 1 到 5 之间")
    if user_pick and user_reject:
        raise CaptureReviewError("同一照片不能同时标为入选和排除")
    normalized_reasons = _normalize_selection_reasons(selection_reasons)
    if user_pick is False or user_reject:
        normalized_reasons = []
    if connection.execute(
        "SELECT 1 FROM captures WHERE id=?", (capture_id,)
    ).fetchone() is None:
        raise CaptureReviewNotFoundError("拍摄单元不存在")
    previous = connection.execute(
        "SELECT user_pick, user_reject FROM capture_reviews WHERE capture_id=?", (capture_id,)
    ).fetchone()
    before_decision = (
        bool(previous["user_pick"]) if previous else False,
        bool(previous["user_reject"]) if previous else False,
    )
    with transaction(connection):
        connection.execute(
            """INSERT INTO capture_reviews(
                   capture_id, user_rating, user_pick, user_reject, user_note,
                   selection_reason_json, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(capture_id) DO UPDATE SET
                   user_rating=excluded.user_rating,
                   user_pick=excluded.user_pick,
                   user_reject=excluded.user_reject,
                   user_note=excluded.user_note,
                   selection_reason_json=COALESCE(
                       excluded.selection_reason_json,
                       capture_reviews.selection_reason_json
                   ),
                   updated_at=excluded.updated_at""",
            (
                capture_id,
                user_rating,
                int(user_pick) if user_pick is not None else None,
                int(user_reject),
                user_note,
                json.dumps(normalized_reasons, ensure_ascii=False)
                if normalized_reasons is not None else None,
                utc_now(),
            ),
        )
        if selection_session_id is not None:
            _record_selection_session_action(
                connection,
                selection_session_id,
                capture_id,
                before_decision,
                (bool(user_pick), bool(user_reject)),
            )
