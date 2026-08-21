from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .database import transaction
from .inventory import utc_now


def create_archive_baseline(
    connection: sqlite3.Connection,
    name: str,
    note: str | None = None,
    *,
    scope: str = "archive",
) -> dict[str, Any]:
    if scope not in {"archive", "active"}:
        raise ValueError("Baseline scope must be archive or active")
    state = connection.execute("SELECT status FROM library_state WHERE id=1").fetchone()
    if scope == "archive" and state and state["status"] == "active":
        raise ValueError("历史原片基线已冻结；切换后请建立活动图库基线")
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 120:
        raise ValueError("Baseline name must contain 1 to 120 characters")
    latest_run = connection.execute(
        "SELECT id, root_path FROM scan_runs WHERE status='complete' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    totals = connection.execute(
        "SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes "
        "FROM files WHERE present=1"
    ).fetchone()
    with transaction(connection):
        cursor = connection.execute(
            """
            INSERT INTO archive_baselines(
                name, created_at, scan_run_id, file_count, total_bytes, note, root_path, scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_name, utc_now(), latest_run["id"] if latest_run else None,
                totals["count"], totals["bytes"], note,
                latest_run["root_path"] if latest_run else None,
                scope,
            ),
        )
        baseline_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO archive_baseline_files(
                baseline_id, relative_path, size_bytes, modified_ns, sha256
            )
            SELECT ?, f.relative_path, f.size_bytes, f.modified_ns,
                   CASE WHEN h.size_bytes=f.size_bytes AND h.modified_ns=f.modified_ns
                        THEN h.digest ELSE NULL END
            FROM files f LEFT JOIN file_hashes h ON h.file_id=f.id AND h.algorithm='sha256'
            WHERE f.present=1
            """,
            (baseline_id,),
        )
        connection.execute(
            """
            INSERT INTO archive_checks(
                baseline_id, scan_run_id, checked_at, missing_count,
                changed_count, new_count, healthy, sample_json
            ) VALUES (?, ?, ?, 0, 0, 0, 1, '[]')
            """,
            (baseline_id, latest_run["id"] if latest_run else None, utc_now()),
        )
    return {
        "id": baseline_id,
        "name": clean_name,
        "file_count": totals["count"],
        "total_bytes": totals["bytes"],
        "scope": scope,
    }


def latest_baseline(
    connection: sqlite3.Connection, scope: str = "archive"
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM archive_baselines WHERE scope=? ORDER BY id DESC LIMIT 1",
        (scope,),
    ).fetchone()
    return dict(row) if row else None


def compare_archive_baseline(
    connection: sqlite3.Connection, baseline_id: int, sample_limit: int = 20
) -> dict[str, Any]:
    baseline = connection.execute(
        "SELECT * FROM archive_baselines WHERE id=?", (baseline_id,)
    ).fetchone()
    if baseline is None:
        raise ValueError("Archive baseline does not exist")
    counts = connection.execute(
        """
        SELECT
          SUM(CASE WHEN f.id IS NULL THEN 1 ELSE 0 END) AS missing,
          SUM(CASE WHEN f.id IS NOT NULL AND
                       (f.size_bytes != bf.size_bytes OR f.modified_ns != bf.modified_ns)
                   THEN 1 ELSE 0 END) AS changed
        FROM archive_baseline_files bf
        LEFT JOIN files f ON f.relative_path=bf.relative_path AND f.present=1
        WHERE bf.baseline_id=?
        """,
        (baseline_id,),
    ).fetchone()
    new_count = connection.execute(
        """
        SELECT COUNT(*) FROM files f
        LEFT JOIN archive_baseline_files bf
          ON bf.baseline_id=? AND bf.relative_path=f.relative_path
        WHERE f.present=1 AND bf.relative_path IS NULL
        """,
        (baseline_id,),
    ).fetchone()[0]
    samples = [dict(row) for row in connection.execute(
        """
        SELECT bf.relative_path,
               CASE WHEN f.id IS NULL THEN 'missing' ELSE 'changed' END AS status,
               bf.size_bytes AS baseline_size, f.size_bytes AS current_size
        FROM archive_baseline_files bf
        LEFT JOIN files f ON f.relative_path=bf.relative_path AND f.present=1
        WHERE bf.baseline_id=? AND
              (f.id IS NULL OR f.size_bytes != bf.size_bytes OR f.modified_ns != bf.modified_ns)
        ORDER BY status, bf.relative_path LIMIT ?
        """,
        (baseline_id, sample_limit),
    )]
    return {
        "baseline": dict(baseline),
        "missing": counts["missing"] or 0,
        "changed": counts["changed"] or 0,
        "new": new_count,
        "healthy": not (counts["missing"] or counts["changed"]),
        "samples": samples,
    }


def compare_archive_baseline_on_disk(
    connection: sqlite3.Connection,
    baseline_id: int,
    sample_limit: int = 20,
    on_difference: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    baseline = connection.execute(
        """SELECT b.*, COALESCE(b.root_path, s.root_path) AS effective_root
           FROM archive_baselines b LEFT JOIN scan_runs s ON s.id=b.scan_run_id
           WHERE b.id=?""",
        (baseline_id,),
    ).fetchone()
    if baseline is None or not baseline["effective_root"]:
        raise ValueError("原片保护基线没有可核对的档案根目录")
    root = Path(baseline["effective_root"])
    expected = {
        row["relative_path"].casefold(): row
        for row in connection.execute(
            """SELECT relative_path, size_bytes, modified_ns
               FROM archive_baseline_files WHERE baseline_id=?""",
            (baseline_id,),
        )
    }
    seen: set[str] = set()
    samples: list[dict[str, Any]] = []
    changed = 0
    new = 0
    for directory, _, names in os.walk(root):
        for name in names:
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            key = relative.casefold()
            seen.add(key)
            item = expected.get(key)
            try:
                stat = path.stat()
            except OSError:
                changed += 1
                if on_difference:
                    on_difference(relative, "unreadable")
                if len(samples) < sample_limit:
                    samples.append({"relative_path": relative, "status": "unreadable"})
                continue
            if item is None:
                new += 1
                if on_difference:
                    on_difference(relative, "new")
                if len(samples) < sample_limit:
                    samples.append({"relative_path": relative, "status": "new"})
            elif stat.st_size != item["size_bytes"] or stat.st_mtime_ns != item["modified_ns"]:
                changed += 1
                if on_difference:
                    on_difference(relative, "changed")
                if len(samples) < sample_limit:
                    samples.append({"relative_path": relative, "status": "changed"})
    missing_paths = [row["relative_path"] for key, row in expected.items() if key not in seen]
    if on_difference:
        for relative in missing_paths:
            on_difference(relative, "missing")
    for relative in missing_paths[: max(0, sample_limit - len(samples))]:
        samples.append({"relative_path": relative, "status": "missing"})
    return {
        "baseline": dict(baseline),
        "missing": len(missing_paths),
        "changed": changed,
        "new": new,
        "healthy": not missing_paths and not changed and not new,
        "samples": samples,
        "checked_root": str(root),
    }


def _recorded_integrity_status(
    connection: sqlite3.Connection, scope: str
) -> dict[str, Any]:
    baseline = latest_baseline(connection, scope)
    if baseline is None:
        return {"baseline": None, "comparison": None}
    check = connection.execute(
        """
        SELECT * FROM archive_checks
        WHERE baseline_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (baseline["id"],),
    ).fetchone()
    if check is None:
        return {"baseline": baseline, "comparison": None}
    return {
        "baseline": baseline,
        "comparison": {
            "baseline": baseline,
            "missing": check["missing_count"],
            "changed": check["changed_count"],
            "new": check["new_count"],
            "healthy": bool(check["healthy"]),
            "samples": json.loads(check["sample_json"]),
            "checked_at": check["checked_at"],
        },
    }


def run_integrity_check(
    connection: sqlite3.Connection, scope: str
) -> dict[str, Any]:
    if scope not in {"archive", "active"}:
        raise ValueError("Integrity scope must be archive or active")
    baseline = latest_baseline(connection, scope)
    if baseline is None:
        raise ValueError("No integrity baseline exists")
    checked_at = utc_now()
    check_id = connection.execute(
        """
        INSERT INTO archive_checks(
            baseline_id, scan_run_id, checked_at, missing_count,
            changed_count, new_count, healthy, sample_json
        ) VALUES (?, ?, ?, 0, 0, 0, 0, '[]')
        ON CONFLICT(baseline_id, scan_run_id) DO UPDATE SET
            checked_at=excluded.checked_at
        RETURNING id
        """,
        (baseline["id"], baseline["scan_run_id"], checked_at),
    ).fetchone()[0]
    connection.execute(
        "DELETE FROM archive_check_differences WHERE check_id=?", (check_id,)
    )
    pending: list[tuple[int, str, str]] = []

    def record_difference(relative_path: str, status: str) -> None:
        pending.append((check_id, relative_path, status))
        if len(pending) >= 500:
            connection.executemany(
                """INSERT OR IGNORE INTO archive_check_differences(
                       check_id, relative_path, status
                   ) VALUES (?, ?, ?)""",
                pending,
            )
            pending.clear()

    result = compare_archive_baseline_on_disk(
        connection, baseline["id"], on_difference=record_difference
    )
    if pending:
        connection.executemany(
            """INSERT OR IGNORE INTO archive_check_differences(
                   check_id, relative_path, status
               ) VALUES (?, ?, ?)""",
            pending,
        )
    connection.execute(
        """UPDATE archive_checks
           SET checked_at=?, missing_count=?, changed_count=?, new_count=?,
               healthy=?, sample_json=?
           WHERE id=?""",
        (
            checked_at, result["missing"], result["changed"], result["new"],
            int(result["healthy"]), json.dumps(result["samples"], ensure_ascii=False),
            check_id,
        ),
    )
    connection.commit()
    result["checked_at"] = checked_at
    return {"baseline": baseline, "comparison": result}


def integrity_differences(
    connection: sqlite3.Connection,
    scope: str,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
) -> dict[str, Any]:
    if scope not in {"archive", "active"}:
        raise ValueError("Integrity scope must be archive or active")
    if status not in {None, "missing", "changed", "new", "unreadable"}:
        raise ValueError("Integrity difference status is invalid")
    check = connection.execute(
        """SELECT ac.id, ac.checked_at
           FROM archive_checks ac
           JOIN archive_baselines ab ON ab.id=ac.baseline_id
           WHERE ab.scope=? ORDER BY ac.id DESC LIMIT 1""",
        (scope,),
    ).fetchone()
    if check is None:
        return {"check_id": None, "count": 0, "limit": limit, "offset": offset, "items": []}
    where = "check_id=?"
    parameters: list[Any] = [check["id"]]
    if status:
        where += " AND status=?"
        parameters.append(status)
    count = connection.execute(
        f"SELECT COUNT(*) FROM archive_check_differences WHERE {where}", parameters
    ).fetchone()[0]
    rows = connection.execute(
        f"""SELECT relative_path, status FROM archive_check_differences
            WHERE {where} ORDER BY status, relative_path LIMIT ? OFFSET ?""",
        (*parameters, limit, offset),
    ).fetchall()
    return {
        "check_id": check["id"],
        "checked_at": check["checked_at"],
        "count": count,
        "limit": limit,
        "offset": offset,
        "items": [dict(row) for row in rows],
    }


def recorded_archive_status(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return the latest saved result without walking the archive directory."""
    return _recorded_integrity_status(connection, "archive")


def recorded_active_library_status(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return the latest saved result without walking the active library."""
    return _recorded_integrity_status(connection, "active")
