from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from .database import transaction
from .inventory import utc_now


TAG_DIMENSIONS = frozenset({"subject", "status", "problem", "location"})
MAX_TAGS_PER_CAPTURE = 64
MAX_TAG_NAME_LENGTH = 40


class CaptureTagError(ValueError):
    pass


class CaptureTagNotFoundError(CaptureTagError):
    pass


def _normalize_tags(tags: Iterable[Mapping[str, Any]]) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for tag in tags:
        dimension = str(tag.get("dimension", "")).strip().lower()
        name = " ".join(str(tag.get("name", "")).split())
        if dimension not in TAG_DIMENSIONS:
            raise CaptureTagError("标签维度无效")
        if not name:
            raise CaptureTagError("标签名称不能为空")
        if len(name) > MAX_TAG_NAME_LENGTH:
            raise CaptureTagError(f"标签名称不能超过 {MAX_TAG_NAME_LENGTH} 个字符")
        key = (dimension, name.casefold())
        if key in seen:
            continue
        seen.add(key)
        normalized.append((dimension, name))
    if len(normalized) > MAX_TAGS_PER_CAPTURE:
        raise CaptureTagError(f"每张照片最多保存 {MAX_TAGS_PER_CAPTURE} 个标签")
    if sum(dimension == "status" for dimension, _ in normalized) > 1:
        raise CaptureTagError("一张照片只能有一个当前工作状态")
    return normalized


def list_capture_tags(
    connection: sqlite3.Connection, capture_id: int
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in connection.execute(
            """SELECT td.id, td.dimension, td.name, td.built_in,
                      ct.source, ct.confidence
               FROM capture_tags ct
               JOIN tag_definitions td ON td.id = ct.tag_id
               WHERE ct.capture_id = ?
               ORDER BY CASE td.dimension
                            WHEN 'subject' THEN 1 WHEN 'status' THEN 2
                            WHEN 'problem' THEN 3 ELSE 4 END,
                        td.sort_order, td.name""",
            (capture_id,),
        )
    ]


def replace_manual_capture_tags(
    connection: sqlite3.Connection,
    capture_id: int,
    tags: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized = _normalize_tags(tags)
    if connection.execute(
        "SELECT 1 FROM captures WHERE id=?", (capture_id,)
    ).fetchone() is None:
        raise CaptureTagNotFoundError("拍摄单元不存在")

    now = utc_now()
    with transaction(connection):
        tag_ids: list[int] = []
        for dimension, name in normalized:
            connection.execute(
                """INSERT OR IGNORE INTO tag_definitions(
                       dimension, name, built_in, sort_order, created_at
                   ) VALUES (?, ?, 0, 1000, ?)""",
                (dimension, name, now),
            )
            row = connection.execute(
                """SELECT id FROM tag_definitions
                   WHERE dimension=? AND name=?""",
                (dimension, name),
            ).fetchone()
            if row is None:
                raise CaptureTagError("标签保存失败")
            tag_ids.append(int(row["id"]))

        connection.execute(
            "DELETE FROM capture_tags WHERE capture_id=? AND source='manual'",
            (capture_id,),
        )
        connection.executemany(
            """INSERT INTO capture_tags(
                   capture_id, tag_id, source, confidence, created_at
               ) VALUES (?, ?, 'manual', NULL, ?)""",
            ((capture_id, tag_id, now) for tag_id in tag_ids),
        )
    return list_capture_tags(connection, capture_id)
