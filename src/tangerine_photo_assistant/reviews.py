from __future__ import annotations

import sqlite3

from .database import transaction
from .inventory import utc_now


class CaptureReviewError(ValueError):
    pass


class CaptureReviewNotFoundError(CaptureReviewError):
    pass


def save_capture_review(
    connection: sqlite3.Connection,
    capture_id: int,
    *,
    user_rating: int | None,
    user_pick: bool | None,
    user_reject: bool,
    user_note: str | None,
) -> None:
    if user_rating is not None and not 1 <= user_rating <= 5:
        raise CaptureReviewError("人工星级必须在 1 到 5 之间")
    if user_pick and user_reject:
        raise CaptureReviewError("同一照片不能同时标为保留和待淘汰")
    if connection.execute(
        "SELECT 1 FROM captures WHERE id=?", (capture_id,)
    ).fetchone() is None:
        raise CaptureReviewNotFoundError("拍摄单元不存在")
    with transaction(connection):
        connection.execute(
            """INSERT INTO capture_reviews(
                   capture_id, user_rating, user_pick, user_reject, user_note, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(capture_id) DO UPDATE SET
                   user_rating=excluded.user_rating,
                   user_pick=excluded.user_pick,
                   user_reject=excluded.user_reject,
                   user_note=excluded.user_note,
                   updated_at=excluded.updated_at""",
            (
                capture_id,
                user_rating,
                int(user_pick) if user_pick is not None else None,
                int(user_reject),
                user_note,
                utc_now(),
            ),
        )
