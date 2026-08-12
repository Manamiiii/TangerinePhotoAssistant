from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from pathlib import PureWindowsPath
from typing import Any
from uuid import uuid4

from .database import transaction
from .inventory import utc_now

DATE_COMPONENT = re.compile(
    r"^(?P<year>\d{4})[.-](?P<month>\d{1,2})[.-](?P<day>\d{1,2})"
    r"(?:-(?P<end_year>\d{4})[.-](?P<end_month>\d{1,2})[.-](?P<end_day>\d{1,2}))?"
    r"[._-]?(?P<title>.*)$"
)
TRAILING_NUMBER = re.compile(r"(\d+)$")


@dataclass(frozen=True)
class CaptureRecord:
    id: int
    parent_relative: str
    stem: str
    captured_at: str | None
    camera_model: str | None


@dataclass
class EventGroup:
    key: str
    proposed_name: str
    category: str
    date_label: str | None
    confidence: float
    method: str
    captures: list[CaptureRecord]
    sources: set[str]
    legacy_buckets: set[str]


def _parse_date_component(parent_relative: str) -> dict[str, str] | None:
    for component in PureWindowsPath(parent_relative).parts:
        match = DATE_COMPONENT.match(component)
        if match is None:
            continue
        values = {key: value or "" for key, value in match.groupdict().items()}
        values["start"] = (
            f"{int(values['year']):04d}-{int(values['month']):02d}-{int(values['day']):02d}"
        )
        values["end"] = (
            f"{int(values['end_year']):04d}-{int(values['end_month']):02d}-"
            f"{int(values['end_day']):02d}"
            if values["end_year"]
            else values["start"]
        )
        values["title"] = values["title"].strip(" ._-+·") or "未命名事件"
        return values
    return None


def _legacy_bucket(parent_relative: str) -> str:
    parts = PureWindowsPath(parent_relative).parts
    if parts and parts[0].casefold() == "myphoto" and len(parts) > 1:
        return parts[1]
    return parts[0] if parts else "未分类"


def _fallback_title(parent_relative: str, bucket: str) -> str:
    parts = list(PureWindowsPath(parent_relative).parts)
    ignored = {"myphoto", bucket.casefold(), "nikon", "sony"}
    candidates = [
        part
        for part in parts
        if part.casefold() not in ignored and not part.casefold().startswith("dji_")
    ]
    return candidates[0] if candidates else bucket


def _category(title: str, buckets: set[str]) -> str:
    combined = " ".join([title, *buckets])
    if "素材" in combined:
        return "素材"
    if any(word in combined for word in ("小乖", "旺旺", "宠物")):
        return "宠物"
    if any(word in combined for word in ("家人", "父母")):
        return "家人"
    if any(word in combined for word in ("新年", "春节", "老家")):
        return "回家"
    if any(word in combined for word in ("星空", "月亮", "车轨")):
        return "专题"
    if any(word in combined for word in ("毕业", "生日", "圣诞", "演唱会")):
        return "纪念"
    return "旅行"


def _load_captures(connection: sqlite3.Connection) -> list[CaptureRecord]:
    rows = connection.execute(
        """
        SELECT
            c.id, c.parent_relative, c.stem, c.captured_at,
            MAX(f.camera_model) AS camera_model
        FROM captures c
        JOIN capture_files cf ON cf.capture_id = c.id
        JOIN files f ON f.id = cf.file_id
        WHERE f.present = 1
        GROUP BY c.id
        ORDER BY COALESCE(c.captured_at, ''), c.id
        """
    ).fetchall()
    return [
        CaptureRecord(
            id=row["id"],
            parent_relative=row["parent_relative"],
            stem=row["stem"],
            captured_at=row["captured_at"],
            camera_model=row["camera_model"],
        )
        for row in rows
    ]


def propose_events(connection: sqlite3.Connection) -> dict[str, int]:
    confirmed_capture_ids = {
        row[0]
        for row in connection.execute(
            """
            SELECT ec.capture_id FROM event_captures ec
            JOIN events e ON e.id = ec.event_id
            WHERE e.status = 'confirmed'
            """
        )
    }
    library_state = connection.execute(
        "SELECT status FROM library_state WHERE id=1"
    ).fetchone()
    active_assignments = {
        row["capture_id"]: row["event_id"]
        for row in connection.execute(
            "SELECT capture_id, event_id FROM event_captures"
        )
    } if library_state and library_state["status"] == "active" else {}
    locked_capture_ids = confirmed_capture_ids | set(active_assignments)
    grouped: dict[str, EventGroup] = {}
    excluded_reference = 0

    for capture in _load_captures(connection):
        if capture.id in locked_capture_ids:
            continue
        bucket = _legacy_bucket(capture.parent_relative)
        if bucket == "素材":
            excluded_reference += 1
            continue
        parsed = _parse_date_component(capture.parent_relative)
        if parsed:
            key = f"dated:{parsed['start']}:{parsed['end']}:{parsed['title'].casefold()}"
            date_label = (
                parsed["start"]
                if parsed["start"] == parsed["end"]
                else f"{parsed['start']} 至 {parsed['end']}"
            )
            name = f"{date_label} · {parsed['title']}"
            method = "directory_date_and_title"
            confidence = 0.95
            title = parsed["title"]
        else:
            captured_day = capture.captured_at[:10] if capture.captured_at else None
            title = _fallback_title(capture.parent_relative, bucket)
            key = (
                f"dated:{captured_day}:{captured_day}:{title.casefold()}"
                if captured_day
                else f"unknown:{capture.parent_relative.casefold()}"
            )
            date_label = captured_day
            name = f"{captured_day} · {title}" if captured_day else f"日期未知 · {title}"
            method = "capture_date_and_source_title" if captured_day else "source_directory_only"
            confidence = 0.8 if captured_day else 0.5

        group = grouped.get(key)
        if group is None:
            group = EventGroup(
                key=key,
                proposed_name=name,
                category="待确认",
                date_label=date_label,
                confidence=confidence,
                method=method,
                captures=[],
                sources=set(),
                legacy_buckets=set(),
            )
            grouped[key] = group
        group.captures.append(capture)
        group.sources.add(capture.parent_relative)
        group.legacy_buckets.add(bucket)
        group.category = _category(title, group.legacy_buckets)

    now = utc_now()
    existing_events = {
        row["event_key"]: row
        for row in connection.execute(
            "SELECT id, event_key, status, created_at FROM events"
        )
    }
    existing_event_members = {
        row["id"]: {
            item[0]
            for item in connection.execute(
                "SELECT capture_id FROM event_captures WHERE event_id=?", (row["id"],)
            )
        }
        for row in existing_events.values()
    }
    retained_event_ids: set[int] = set(active_assignments.values())
    with transaction(connection):
        marker = uuid4().hex
        movable_event_ids = [
            row["id"] for row in existing_events.values()
            if row["status"] == "proposed" and row["id"] not in retained_event_ids
        ]
        if movable_event_ids:
            connection.executemany(
                "UPDATE events SET event_key=? || ':' || id WHERE id=?",
                ((f"rebuild:{marker}", event_id) for event_id in movable_event_ids),
            )
        for event_id in sorted(retained_event_ids):
            connection.execute("DELETE FROM event_sources WHERE event_id=?", (event_id,))
            connection.execute(
                """INSERT INTO event_sources(event_id, parent_relative)
                   SELECT ?, c.parent_relative FROM event_captures ec
                   JOIN captures c ON c.id=ec.capture_id
                   WHERE ec.event_id=? GROUP BY c.parent_relative""",
                (event_id, event_id),
            )
            connection.execute(
                """UPDATE events SET
                       capture_count=(SELECT COUNT(*) FROM event_captures WHERE event_id=?),
                       start_at=(SELECT MIN(c.captured_at) FROM event_captures ec
                                 JOIN captures c ON c.id=ec.capture_id WHERE ec.event_id=?),
                       end_at=(SELECT MAX(c.captured_at) FROM event_captures ec
                               JOIN captures c ON c.id=ec.capture_id WHERE ec.event_id=?),
                       updated_at=? WHERE id=?""",
                (event_id, event_id, event_id, now, event_id),
            )
        for group in sorted(
            grouped.values(),
            key=lambda item: min(
                (capture.captured_at or "9999" for capture in item.captures), default="9999"
            ),
        ):
            ordered = sorted(
                group.captures,
                key=lambda capture: (capture.captured_at or "9999", capture.stem, capture.id),
            )
            dates = [capture.captured_at for capture in ordered if capture.captured_at]
            reason = {
                "method": group.method,
                "source_count": len(group.sources),
                "legacy_buckets": sorted(group.legacy_buckets),
            }
            existing = existing_events.get(group.key)
            if (
                existing is None
                or existing["status"] != "proposed"
                or existing["id"] in retained_event_ids
            ):
                capture_ids = {capture.id for capture in ordered}
                candidates = [
                    row for row in existing_events.values()
                    if row["status"] == "proposed"
                    and row["id"] not in retained_event_ids
                ]
                scored = [
                    (
                        len(capture_ids & existing_event_members[row["id"]])
                        / max(
                            1,
                            min(
                                len(capture_ids),
                                len(existing_event_members[row["id"]]),
                            ),
                        ),
                        row,
                    )
                    for row in candidates
                ]
                best = max(scored, key=lambda item: item[0], default=(0.0, None))
                existing = best[1] if best[0] >= 0.5 else None
            if existing is not None and existing["status"] == "proposed":
                event_id = int(existing["id"])
                connection.execute(
                    """UPDATE events SET event_key=?, proposed_name=?, category=?, date_label=?,
                           start_at=?, end_at=?, capture_count=?, confidence=?,
                           reason_json=?, updated_at=? WHERE id=?""",
                    (
                        group.key, group.proposed_name, group.category, group.date_label,
                        min(dates) if dates else None, max(dates) if dates else None,
                        len(ordered), group.confidence,
                        json.dumps(reason, ensure_ascii=False), now, event_id,
                    ),
                )
                connection.execute("DELETE FROM event_sources WHERE event_id=?", (event_id,))
                connection.execute("DELETE FROM event_captures WHERE event_id=?", (event_id,))
            elif existing is not None:
                # Confirmed events are owned by the user and are never overwritten here.
                continue
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO events(
                        event_key, proposed_name, category, date_label, start_at, end_at,
                        capture_count, status, confidence, reason_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?)
                    """,
                    (
                        group.key, group.proposed_name, group.category, group.date_label,
                        min(dates) if dates else None, max(dates) if dates else None,
                        len(ordered), group.confidence,
                        json.dumps(reason, ensure_ascii=False), now, now,
                    ),
                )
                event_id = int(cursor.lastrowid)
            retained_event_ids.add(event_id)
            connection.executemany(
                "INSERT INTO event_sources(event_id, parent_relative) VALUES (?, ?)",
                ((event_id, source) for source in sorted(group.sources)),
            )
            connection.executemany(
                """
                INSERT INTO event_captures(event_id, capture_id, sequence_index)
                VALUES (?, ?, ?)
                """,
                ((event_id, capture.id, index) for index, capture in enumerate(ordered)),
            )
        stale_proposed = [
            row["id"]
            for row in existing_events.values()
            if row["status"] == "proposed" and row["id"] not in retained_event_ids
        ]
        if stale_proposed:
            for event_id in stale_proposed:
                referenced = connection.execute(
                    "SELECT 1 FROM migration_items WHERE event_id=? LIMIT 1", (event_id,)
                ).fetchone()
                if referenced:
                    connection.execute(
                        """UPDATE events SET status='archived', capture_count=0,
                               updated_at=? WHERE id=?""",
                        (now, event_id),
                    )
                    connection.execute("DELETE FROM event_sources WHERE event_id=?", (event_id,))
                    connection.execute("DELETE FROM event_captures WHERE event_id=?", (event_id,))
                else:
                    connection.execute("DELETE FROM events WHERE id=?", (event_id,))

    return {
        "proposed_events": len(grouped),
        "assigned_captures": (
            len(locked_capture_ids)
            + sum(len(group.captures) for group in grouped.values())
        ),
        "excluded_reference_captures": excluded_reference,
        "confirmed_captures_preserved": len(confirmed_capture_ids),
    }


def _stem_sequence(stem: str) -> tuple[str, int, int] | None:
    match = TRAILING_NUMBER.search(stem)
    if match is None:
        return None
    digits = match.group(1)
    return stem[:match.start()].casefold(), int(digits), len(digits)


def _can_join_burst(
    previous: CaptureRecord,
    current: CaptureRecord,
    gap_seconds: float,
) -> bool:
    if previous.captured_at is None or current.captured_at is None:
        return False
    delta = (
        datetime.fromisoformat(current.captured_at) - datetime.fromisoformat(previous.captured_at)
    ).total_seconds()
    if delta < 0 or delta > gap_seconds:
        return False
    previous_sequence = _stem_sequence(previous.stem)
    current_sequence = _stem_sequence(current.stem)
    if previous_sequence is None or current_sequence is None:
        return False
    previous_prefix, previous_number, previous_width = previous_sequence
    current_prefix, current_number, current_width = current_sequence
    if previous_prefix != current_prefix or previous_width != current_width:
        return False
    if current_number == previous_number + 1:
        return True
    rollover = 10**previous_width - 1
    return previous_number == rollover and current_number in {0, 1}


def rebuild_bursts(connection: sqlite3.Connection, gap_seconds: float) -> dict[str, int]:
    events = connection.execute("SELECT id FROM events ORDER BY id").fetchall()
    burst_groups: list[tuple[int, str, list[CaptureRecord]]] = []

    for event in events:
        rows = connection.execute(
            """
            SELECT
                c.id, c.parent_relative, c.stem, c.captured_at,
                MAX(f.camera_model) AS camera_model
            FROM event_captures ec
            JOIN captures c ON c.id = ec.capture_id
            JOIN capture_files cf ON cf.capture_id = c.id
            JOIN files f ON f.id = cf.file_id
            WHERE ec.event_id = ? AND c.captured_at IS NOT NULL
            GROUP BY c.id
            ORDER BY c.captured_at, c.stem, c.id
            """,
            (event["id"],),
        ).fetchall()
        by_camera: dict[str, list[CaptureRecord]] = defaultdict(list)
        for row in rows:
            camera = row["camera_model"] or "未知相机"
            by_camera[camera].append(
                CaptureRecord(
                    id=row["id"],
                    parent_relative=row["parent_relative"],
                    stem=row["stem"],
                    captured_at=row["captured_at"],
                    camera_model=row["camera_model"],
                )
            )

        for camera, captures in by_camera.items():
            current_group: list[CaptureRecord] = []
            for capture in captures:
                if current_group and not _can_join_burst(
                    current_group[-1], capture, gap_seconds
                ):
                    if len(current_group) >= 2:
                        burst_groups.append((event["id"], camera, current_group))
                    current_group = []
                current_group.append(capture)
            if len(current_group) >= 2:
                burst_groups.append((event["id"], camera, current_group))

    existing_rows = connection.execute(
        "SELECT id, event_id, burst_key, camera_model FROM bursts"
    ).fetchall()
    existing_members = {
        row["id"]: {
            item[0]
            for item in connection.execute(
                "SELECT capture_id FROM burst_captures WHERE burst_id=?", (row["id"],)
            )
        }
        for row in existing_rows
    }
    existing_by_key = {row["burst_key"]: row for row in existing_rows}
    used_burst_ids: set[int] = set()
    with transaction(connection):
        marker = uuid4().hex
        connection.execute(
            "UPDATE bursts SET burst_key=? || ':' || id", (f"rebuild:{marker}",)
        )
        for event_id, camera, captures in burst_groups:
            start = captures[0].captured_at
            end = captures[-1].captured_at
            assert start is not None and end is not None
            identity = f"{event_id}:{camera}:{captures[0].id}:{captures[-1].id}"
            burst_key = sha1(identity.encode("utf-8")).hexdigest()
            capture_ids = {capture.id for capture in captures}
            existing = existing_by_key.get(burst_key)
            if existing is None or existing["id"] in used_burst_ids:
                candidates = [
                    row for row in existing_rows
                    if row["id"] not in used_burst_ids
                    and row["event_id"] == event_id
                    and (row["camera_model"] or "未知相机") == camera
                ]
                scored = [
                    (
                        len(capture_ids & existing_members[row["id"]])
                        / max(1, min(len(capture_ids), len(existing_members[row["id"]]))),
                        row,
                    )
                    for row in candidates
                ]
                best = max(scored, key=lambda item: item[0], default=(0.0, None))
                existing = best[1] if best[0] >= 0.5 else None
            if existing is not None:
                burst_id = int(existing["id"])
                connection.execute(
                    """UPDATE bursts SET event_id=?, burst_key=?, start_at=?, end_at=?,
                           capture_count=?, camera_model=?,
                           grouping_method='metadata_time_sequence', status='candidate'
                       WHERE id=?""",
                    (event_id, burst_key, start, end, len(captures), camera, burst_id),
                )
                connection.execute("DELETE FROM burst_captures WHERE burst_id=?", (burst_id,))
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO bursts(
                        event_id, burst_key, start_at, end_at, capture_count,
                        camera_model, grouping_method, status
                    ) VALUES (?, ?, ?, ?, ?, ?, 'metadata_time_sequence', 'candidate')
                    """,
                    (event_id, burst_key, start, end, len(captures), camera),
                )
                burst_id = int(cursor.lastrowid)
            used_burst_ids.add(burst_id)
            start_time = datetime.fromisoformat(start)
            connection.executemany(
                """
                INSERT INTO burst_captures(
                    burst_id, capture_id, sequence_index, offset_ms
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    (
                        burst_id,
                        capture.id,
                        index,
                        int(
                            (
                                datetime.fromisoformat(capture.captured_at or start) - start_time
                            ).total_seconds()
                            * 1000
                        ),
                    )
                    for index, capture in enumerate(captures)
                ),
            )
        stale_bursts = [
            row["id"] for row in existing_rows if row["id"] not in used_burst_ids
        ]
        if stale_bursts:
            connection.executemany(
                "DELETE FROM bursts WHERE id=?", ((burst_id,) for burst_id in stale_bursts)
            )

    return {
        "candidate_bursts": len(burst_groups),
        "captures_in_bursts": sum(len(group[2]) for group in burst_groups),
        "largest_burst": max((len(group[2]) for group in burst_groups), default=0),
    }


def rebuild_structure(
    connection: sqlite3.Connection,
    burst_time_gap_seconds: float,
) -> dict[str, int]:
    event_result = propose_events(connection)
    burst_result = rebuild_bursts(connection, burst_time_gap_seconds)
    connection.execute("PRAGMA optimize")
    return {**event_result, **burst_result}


def structure_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    category_rows = connection.execute(
        """
        SELECT category, COUNT(*) AS event_count, SUM(capture_count) AS capture_count
        FROM events GROUP BY category ORDER BY capture_count DESC
        """
    ).fetchall()
    burst = connection.execute(
        """
        SELECT
            COUNT(*) AS burst_count,
            COALESCE(SUM(capture_count), 0) AS capture_count,
            COALESCE(MAX(capture_count), 0) AS largest_burst
        FROM bursts
        """
    ).fetchone()
    return {
        "event_count": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "unconfirmed_event_count": connection.execute(
            "SELECT COUNT(*) FROM events WHERE status <> 'confirmed'"
        ).fetchone()[0],
        "unassigned_capture_count": connection.execute(
            """SELECT COUNT(*) FROM captures c
               WHERE NOT EXISTS (
                   SELECT 1 FROM event_captures ec WHERE ec.capture_id=c.id
               )
                 AND EXISTS (
                   SELECT 1 FROM capture_files cf
                   JOIN files f ON f.id=cf.file_id
                   WHERE cf.capture_id=c.id AND f.present=1
                 )"""
        ).fetchone()[0],
        "categories": [dict(row) for row in category_rows],
        "burst_count": burst["burst_count"],
        "captures_in_bursts": burst["capture_count"],
        "largest_burst": burst["largest_burst"],
    }
