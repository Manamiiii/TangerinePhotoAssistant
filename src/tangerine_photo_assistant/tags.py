from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from .database import transaction
from .inventory import utc_now


TAG_DIMENSIONS = frozenset({"subject", "status", "problem", "location"})
MAX_TAGS_PER_CAPTURE = 64
MAX_TAG_NAME_LENGTH = 40
RETIRED_WORKFLOW_STATUSES = frozenset({"精选", "待淘汰"})
ANALYSIS_SUBJECT_LIMIT = 8


class CaptureTagError(ValueError):
    pass


class CaptureTagNotFoundError(CaptureTagError):
    pass


def _analysis_subjects(result: Mapping[str, Any]) -> list[tuple[str, float | None]]:
    raw_tags = result.get("subject_tags")
    candidates: list[tuple[object, object]] = []
    if isinstance(raw_tags, list):
        for raw in raw_tags:
            if isinstance(raw, str):
                candidates.append((raw, result.get("overall_confidence")))
            elif isinstance(raw, Mapping):
                candidates.append((raw.get("name"), raw.get("confidence")))
    if not candidates:
        candidates.append((result.get("subject_type"), result.get("overall_confidence")))

    subjects: list[tuple[str, float | None]] = []
    seen: set[str] = set()
    for raw_name, raw_confidence in candidates:
        name = " ".join(str(raw_name or "").split())
        if not name or len(name) > MAX_TAG_NAME_LENGTH or name.casefold() in seen:
            continue
        try:
            confidence = max(0.0, min(1.0, float(raw_confidence)))
        except (TypeError, ValueError):
            confidence = None
        seen.add(name.casefold())
        subjects.append((name, round(confidence, 2) if confidence is not None else None))
        if len(subjects) >= ANALYSIS_SUBJECT_LIMIT:
            break
    return subjects


def replace_analysis_subject_tags(
    connection: sqlite3.Connection,
    capture_id: int,
    result: Mapping[str, Any],
) -> int:
    """Replace only model-derived subject tags; manual/import tags stay untouched."""
    subjects = _analysis_subjects(result)
    now = utc_now()
    connection.execute(
        """DELETE FROM capture_tags WHERE capture_id=? AND source='analysis'
             AND tag_id IN (SELECT id FROM tag_definitions WHERE dimension='subject')""",
        (capture_id,),
    )
    for order, (name, confidence) in enumerate(subjects, start=1):
        connection.execute(
            """INSERT OR IGNORE INTO tag_definitions(
                   dimension, name, built_in, sort_order, created_at
               ) VALUES ('subject', ?, 1, ?, ?)""",
            (name, order * 10, now),
        )
        tag_id = connection.execute(
            "SELECT id FROM tag_definitions WHERE dimension='subject' AND name=?",
            (name,),
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO capture_tags(capture_id, tag_id, source, confidence, created_at)
               VALUES (?, ?, 'analysis', ?, ?)""",
            (capture_id, tag_id, confidence, now),
        )
    return len(subjects)


def sync_analysis_subject_tags(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """SELECT aa.capture_id, aa.result_json
           FROM ai_analyses aa
           WHERE aa.status='complete' AND aa.result_json IS NOT NULL
             AND COALESCE(aa.user_verdict, '')!='inaccurate'
             AND aa.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                        WHERE newest.capture_id=aa.capture_id
                          AND newest.status='complete')
           ORDER BY aa.capture_id"""
    ).fetchall()
    synchronized = 0
    links = 0
    ignored = 0
    with transaction(connection):
        connection.execute(
            """DELETE FROM capture_tags WHERE source='analysis'
                 AND tag_id IN (SELECT id FROM tag_definitions WHERE dimension='subject')"""
        )
        for row in rows:
            try:
                result = json.loads(row["result_json"])
            except (TypeError, json.JSONDecodeError):
                ignored += 1
                continue
            if not isinstance(result, dict):
                ignored += 1
                continue
            links += replace_analysis_subject_tags(
                connection, int(row["capture_id"]), result
            )
            synchronized += 1
    return {
        "eligible_captures": len(rows),
        "synchronized_captures": synchronized,
        "tag_links": links,
        "ignored_results": ignored,
    }


def clear_analysis_subject_tags(connection: sqlite3.Connection) -> int:
    with transaction(connection):
        cursor = connection.execute(
            """DELETE FROM capture_tags WHERE source='analysis'
                 AND tag_id IN (SELECT id FROM tag_definitions WHERE dimension='subject')"""
        )
    return int(cursor.rowcount)


def analysis_subject_tag_status(connection: sqlite3.Connection) -> dict[str, int]:
    row = connection.execute(
        """SELECT COUNT(DISTINCT CASE WHEN aa.id IS NOT NULL THEN c.id END) AS eligible_captures,
                  COUNT(DISTINCT CASE WHEN ct.capture_id IS NOT NULL THEN c.id END) AS tagged_captures,
                  COUNT(DISTINCT ct.tag_id) AS subject_count,
                  COUNT(ct.tag_id) AS tag_links
           FROM captures c
           LEFT JOIN ai_analyses aa ON aa.capture_id=c.id AND aa.status='complete'
             AND COALESCE(aa.user_verdict, '')!='inaccurate'
             AND aa.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                        WHERE newest.capture_id=c.id AND newest.status='complete')
           LEFT JOIN capture_tags ct ON ct.capture_id=c.id AND ct.source='analysis'
             AND ct.tag_id IN (SELECT id FROM tag_definitions WHERE dimension='subject')"""
    ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


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
    inactive = {
        (str(row["dimension"]), str(row["name"]).casefold())
        for row in connection.execute(
            "SELECT dimension, name FROM tag_definitions WHERE active=0"
        )
    }
    existing_inactive = {
        (str(row["dimension"]), str(row["name"]).casefold())
        for row in connection.execute(
            """SELECT td.dimension, td.name FROM capture_tags ct
               JOIN tag_definitions td ON td.id=ct.tag_id
               WHERE ct.capture_id=? AND ct.source='manual' AND td.active=0""",
            (capture_id,),
        )
    }
    if any(
        (
            dimension == "status"
            and name in RETIRED_WORKFLOW_STATUSES
            and (dimension, name.casefold()) not in existing_inactive
        )
        or (
            (dimension, name.casefold()) in inactive
            and (dimension, name.casefold()) not in existing_inactive
        )
        for dimension, name in normalized
    ):
        raise CaptureTagError("精选和待淘汰请使用选片入选/排除，不再作为工作状态新增")

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


def update_manual_tag_for_captures(
    connection: sqlite3.Connection,
    capture_ids: Iterable[int],
    *,
    dimension: str,
    name: str,
    action: str,
) -> int:
    ids = list(dict.fromkeys(int(capture_id) for capture_id in capture_ids))
    if not ids:
        raise CaptureTagError("至少选择一张照片")
    if len(ids) > 500:
        raise CaptureTagError("每次最多批量标记 500 张照片")
    normalized = _normalize_tags(({"dimension": dimension, "name": name},))
    normalized_dimension, normalized_name = normalized[0]
    if action not in {"add", "remove"}:
        raise CaptureTagError("批量标签操作无效")
    placeholders = ",".join("?" for _ in ids)
    existing_count = connection.execute(
        f"SELECT COUNT(*) FROM captures WHERE id IN ({placeholders})", ids
    ).fetchone()[0]
    if existing_count != len(ids):
        raise CaptureTagNotFoundError("选择中包含不存在的拍摄单元")

    now = utc_now()
    if action == "remove":
        row = connection.execute(
            "SELECT id FROM tag_definitions WHERE dimension=? AND name=?",
            (normalized_dimension, normalized_name),
        ).fetchone()
        if row is None:
            return 0
        with transaction(connection):
            cursor = connection.execute(
                f"""DELETE FROM capture_tags
                    WHERE source='manual' AND tag_id=?
                      AND capture_id IN ({placeholders})""",
                (row["id"], *ids),
            )
        return int(cursor.rowcount)
    existing_definition = connection.execute(
        "SELECT active FROM tag_definitions WHERE dimension=? AND name=?",
        (normalized_dimension, normalized_name),
    ).fetchone()
    if (
        normalized_dimension == "status"
        and normalized_name in RETIRED_WORKFLOW_STATUSES
    ) or (existing_definition is not None and not existing_definition["active"]):
        raise CaptureTagError("精选和待淘汰请使用选片入选/排除，不再作为工作状态新增")
    with transaction(connection):
        connection.execute(
            """INSERT OR IGNORE INTO tag_definitions(
                   dimension, name, built_in, sort_order, created_at
               ) VALUES (?, ?, 0, 1000, ?)""",
            (normalized_dimension, normalized_name, now),
        )
        tag_id = connection.execute(
            "SELECT id FROM tag_definitions WHERE dimension=? AND name=?",
            (normalized_dimension, normalized_name),
        ).fetchone()[0]
        if normalized_dimension == "status":
            connection.execute(
                f"""DELETE FROM capture_tags
                    WHERE source='manual' AND capture_id IN ({placeholders})
                      AND tag_id IN (
                          SELECT id FROM tag_definitions WHERE dimension='status'
                      )""",
                ids,
            )
        connection.executemany(
            """INSERT OR IGNORE INTO capture_tags(
                   capture_id, tag_id, source, confidence, created_at
               ) VALUES (?, ?, 'manual', NULL, ?)""",
            ((capture_id, tag_id, now) for capture_id in ids),
        )
    return len(ids)
