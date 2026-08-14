from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence

from .database import transaction
from .inventory import utc_now


class CaptureReviewError(ValueError):
    pass


class CaptureReviewNotFoundError(CaptureReviewError):
    pass


SELECTION_REASONS = frozenset({"动作差异", "表情差异", "构图差异", "关键瞬间", "叙事补充"})


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
