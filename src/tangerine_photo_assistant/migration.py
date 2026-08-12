from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Any

from .database import transaction
from .inventory import utc_now

INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
EXCLUDED_TOP_LEVEL = frozenset({"素材"})
COPY_BUFFER_SIZE = 4 * 1024 * 1024


class MigrationStopped(RuntimeError):
    pass


def _safe_component(value: str) -> str:
    cleaned = INVALID_COMPONENT.sub("_", value).strip(" .")
    return cleaned[:120] or "未命名"


def _year(captured_at: str | None) -> str:
    if captured_at and len(captured_at) >= 4 and captured_at[:4].isdigit():
        return captured_at[:4]
    return "日期未知"


def _target_for(row: sqlite3.Row) -> tuple[str, str]:
    if row["event_id"] is not None:
        target = PureWindowsPath(
            _safe_component(row["category"]),
            _year(row["captured_at"] or row["event_start"]),
            _safe_component(row["event_name"]),
            row["file_name"],
        )
        return str(target), "event"

    original = PureWindowsPath(row["relative_path"])
    parent_parts = [_safe_component(part) for part in original.parent.parts]
    target = PureWindowsPath("待整理", "未分配", *parent_parts, row["file_name"])
    return str(target), "unassigned"


def _rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT f.id AS file_id, f.relative_path, f.parent_relative, f.file_name,
               f.size_bytes, f.modified_ns, f.captured_at,
               e.id AS event_id, e.proposed_name AS event_name,
               e.category, e.start_at AS event_start,
               CASE WHEN h.size_bytes=f.size_bytes AND h.modified_ns=f.modified_ns
                    THEN h.digest ELSE NULL END AS source_sha256
        FROM files f
        LEFT JOIN capture_files cf ON cf.file_id=f.id
        LEFT JOIN event_captures ec ON ec.capture_id=cf.capture_id
        LEFT JOIN events e ON e.id=ec.event_id
        LEFT JOIN file_hashes h ON h.file_id=f.id AND h.algorithm='sha256'
        WHERE f.present=1
        ORDER BY f.relative_path COLLATE NOCASE
        """
    ).fetchall()


def migration_status(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM migration_plans ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {"plan": None}
    plan = dict(row)
    plan["ready"] = plan["conflict_count"] == 0 and plan["available_bytes"] >= plan["total_bytes"]
    plan["csv_name"] = f"migration-plan-{plan['id']}.csv"
    plan["json_name"] = f"migration-plan-{plan['id']}.json"
    plan["csv_url"] = f"/api/reports/{plan['csv_name']}"
    plan["json_url"] = f"/api/reports/{plan['json_name']}"
    plan["sample_conflicts"] = [dict(item) for item in connection.execute(
        """SELECT source_relative, target_relative, reason
           FROM migration_items WHERE plan_id=? AND status='conflict'
           ORDER BY target_relative LIMIT 20""",
        (plan["id"],),
    )]
    plan["sample_unassigned"] = [dict(item) for item in connection.execute(
        """SELECT source_relative, target_relative, reason
           FROM migration_items WHERE plan_id=? AND reason!='event'
           ORDER BY source_relative LIMIT 20""",
        (plan["id"],),
    )]
    run = connection.execute(
        "SELECT * FROM migration_runs WHERE plan_id=? ORDER BY id DESC LIMIT 1",
        (plan["id"],),
    ).fetchone()
    plan["run"] = dict(run) if run else None
    if run:
        plan["failures"] = [dict(item) for item in connection.execute(
            """SELECT stage, error_code, message, source_relative, target_relative
               FROM migration_failures WHERE run_id=? ORDER BY id DESC LIMIT 50""",
            (run["id"],),
        )]
    else:
        plan["failures"] = []
    if run:
        plan["failure_csv_url"] = f"/api/reports/migration-failures-{run['id']}.csv"
        plan["failure_json_url"] = f"/api/reports/migration-failures-{run['id']}.json"
    plan["confirmation_phrase"] = f"COPY PLAN {plan['id']}"
    plan["switch_confirmation_phrase"] = (
        f"SWITCH TO ACTIVE LIBRARY PLAN {plan['id']}"
    )
    return {"plan": plan}


def _digest(path: Path, progress: Callable[[int], None] | None = None) -> str:
    result = sha256()
    with path.open("rb") as stream:
        while block := stream.read(COPY_BUFFER_SIZE):
            result.update(block)
            if progress:
                progress(len(block))
    return result.hexdigest()


def _item_paths(plan: sqlite3.Row, item: sqlite3.Row) -> tuple[Path, Path, Path]:
    source_root = Path(plan["source_root"]).resolve()
    target_root = Path(plan["target_root"]).resolve()
    source = (source_root / Path(item["source_relative"])).resolve()
    target = (target_root / Path(item["target_relative"])).resolve()
    if not source.is_relative_to(source_root) or not target.is_relative_to(target_root):
        raise ValueError("迁移项目路径越出已审核的图库根目录")
    temporary = target.with_name(f".{target.name}.tangerine-part-{item['id']}")
    return source, target, temporary


def migration_preflight(
    connection: sqlite3.Connection, plan_id: int,
) -> dict[str, Any]:
    plan = connection.execute("SELECT * FROM migration_plans WHERE id=?", (plan_id,)).fetchone()
    if plan is None:
        raise ValueError("迁移计划不存在")
    if plan["conflict_count"]:
        raise ValueError("迁移计划仍包含目标冲突")
    source_root = Path(plan["source_root"]).resolve()
    target_root = Path(plan["target_root"]).resolve()
    if target_root == source_root or target_root.is_relative_to(source_root):
        raise ValueError("迁移目标不能位于原始档案内部")
    missing: list[str] = []
    changed: list[str] = []
    conflicts: list[str] = []
    remaining_bytes = 0
    items = connection.execute(
        "SELECT * FROM migration_items WHERE plan_id=? ORDER BY id", (plan_id,)
    ).fetchall()
    if len(items) != plan["item_count"] or sum(row["size_bytes"] for row in items) != plan["total_bytes"]:
        raise ValueError("数据库中的迁移项目与计划汇总不一致")
    for item in items:
        source, target, _ = _item_paths(plan, item)
        try:
            stat = source.stat()
        except OSError:
            missing.append(item["source_relative"])
            continue
        if stat.st_size != item["size_bytes"] or stat.st_mtime_ns != item["modified_ns"]:
            changed.append(item["source_relative"])
        if target.exists():
            conflicts.append(item["target_relative"])
        remaining_bytes += item["size_bytes"]
    probe = target_root if target_root.exists() else target_root.parent
    available = shutil.disk_usage(probe).free
    return {
        "plan_id": plan_id,
        "item_count": len(items),
        "total_bytes": plan["total_bytes"],
        "available_bytes": available,
        "missing_count": len(missing),
        "changed_count": len(changed),
        "conflict_count": len(conflicts),
        "missing_samples": missing[:20],
        "changed_samples": changed[:20],
        "conflict_samples": conflicts[:20],
        "ready": not missing and not changed and not conflicts and available >= remaining_bytes,
    }


def prepare_migration_run(
    connection: sqlite3.Connection,
    plan_id: int,
    confirmation: str,
    *,
    batch_max_files: int | None = 2000,
    batch_max_bytes: int | None = 100 * 1024**3,
    batch_max_seconds: int | None = 4 * 60 * 60,
) -> dict[str, Any]:
    expected = f"COPY PLAN {plan_id}"
    if confirmation != expected:
        raise ValueError(f"确认文字不匹配；必须完整输入 {expected}")
    limits = {
        "batch_max_files": batch_max_files,
        "batch_max_bytes": batch_max_bytes,
        "batch_max_seconds": batch_max_seconds,
    }
    if any(value is not None and value <= 0 for value in limits.values()):
        raise ValueError("批次文件数、数据量和运行时长必须为正数")
    if all(value is None for value in limits.values()):
        raise ValueError("至少需要设置一种批次上限")
    preflight = migration_preflight(connection, plan_id)
    if not preflight["ready"]:
        raise ValueError("迁移预检查未通过，未创建执行任务")
    existing = connection.execute(
        "SELECT id, status FROM migration_runs WHERE plan_id=? ORDER BY id DESC LIMIT 1",
        (plan_id,),
    ).fetchone()
    if existing and existing["status"] not in {"failed", "cancelled"}:
        raise ValueError("该计划已有迁移任务；请暂停、继续或审计现有任务")
    with transaction(connection):
        cursor = connection.execute(
            """INSERT INTO migration_runs(
                   plan_id, created_at, status, total_bytes, confirmation,
                   batch_max_files, batch_max_bytes, batch_max_seconds
               ) VALUES (?, ?, 'prepared', ?, ?, ?, ?, ?)""",
            (
                plan_id, utc_now(), preflight["total_bytes"], confirmation,
                batch_max_files, batch_max_bytes, batch_max_seconds,
            ),
        )
        run_id = int(cursor.lastrowid)
        connection.execute(
            """UPDATE migration_items SET run_id=?, status='planned', copied_bytes=0,
                   target_sha256=NULL, verified_at=NULL, last_error=NULL
               WHERE plan_id=?""",
            (run_id, plan_id),
        )
        connection.execute(
            "UPDATE migration_plans SET status='prepared', note=? WHERE id=?",
            ("已明确确认；等待安全复制任务启动", plan_id),
        )
    return {"run_id": run_id, **preflight, **limits}


def _record_failure(
    connection: sqlite3.Connection, run_id: int, item: sqlite3.Row,
    stage: str, code: str, message: str,
) -> None:
    connection.execute(
        """INSERT INTO migration_failures(
               run_id, item_id, occurred_at, stage, error_code, message,
               source_relative, target_relative
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, item["id"], utc_now(), stage, code, message,
            item["source_relative"], item["target_relative"],
        ),
    )
    connection.execute(
        "UPDATE migration_items SET status='failed', last_error=? WHERE id=?",
        (message, item["id"]),
    )
    connection.commit()


def _write_failure_report(
    connection: sqlite3.Connection, run_id: int, plan: sqlite3.Row
) -> None:
    reports = Path(plan["target_root"]).parent / "Reports"
    reports.mkdir(parents=True, exist_ok=True)
    rows = [dict(row) for row in connection.execute(
        """SELECT occurred_at, stage, error_code, message,
                  source_relative, target_relative
           FROM migration_failures WHERE run_id=? ORDER BY id""",
        (run_id,),
    )]
    csv_path = reports / f"migration-failures-{run_id}.csv"
    json_path = reports / f"migration-failures-{run_id}.json"
    fields = [
        "occurred_at", "stage", "error_code", "message",
        "source_relative", "target_relative",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(
        json.dumps({"run_id": run_id, "failure_count": len(rows), "items": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _refresh_run_totals(connection: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    row = connection.execute(
        """SELECT COUNT(*) FILTER (WHERE status='verified') AS verified,
                  COUNT(*) FILTER (WHERE status='failed') AS failed,
                  COUNT(*) FILTER (WHERE copied_bytes>0) AS copied,
                  COALESCE(SUM(copied_bytes), 0) AS bytes
           FROM migration_items WHERE run_id=?""",
        (run_id,),
    ).fetchone()
    connection.execute(
        """UPDATE migration_runs SET copied_count=?, verified_count=?, failed_count=?,
               copied_bytes=? WHERE id=?""",
        (row["copied"], row["verified"], row["failed"], row["bytes"], run_id),
    )
    connection.commit()
    return dict(row)


def execute_migration_run(
    connection: sqlite3.Connection,
    run_id: int,
    *,
    pause_requested: Callable[[], bool] = lambda: False,
    cancel_requested: Callable[[], bool] = lambda: False,
    progress: Callable[[dict[str, Any]], None] | None = None,
    auto_audit: bool = True,
) -> dict[str, Any]:
    run = connection.execute("SELECT * FROM migration_runs WHERE id=?", (run_id,)).fetchone()
    if run is None or run["status"] not in {
        "prepared", "running", "paused", "cancelled", "failed", "auditing"
    }:
        raise ValueError("迁移任务不存在或当前状态不可继续")
    plan = connection.execute("SELECT * FROM migration_plans WHERE id=?", (run["plan_id"],)).fetchone()
    assert plan is not None
    connection.execute(
        "UPDATE migration_runs SET status='running', started_at=COALESCE(started_at, ?) WHERE id=?",
        (utc_now(), run_id),
    )
    connection.execute("UPDATE migration_plans SET status='copying' WHERE id=?", (plan["id"],))
    connection.commit()
    session_start = time.monotonic()
    session_bytes = 0
    batch_files = 0
    batch_bytes = 0

    def batch_limit_reason() -> str | None:
        if run["batch_max_files"] and batch_files >= run["batch_max_files"]:
            return "files"
        if run["batch_max_bytes"] and batch_bytes >= run["batch_max_bytes"]:
            return "bytes"
        if (
            run["batch_max_seconds"]
            and time.monotonic() - session_start >= run["batch_max_seconds"]
        ):
            return "time"
        return None

    def control() -> None:
        if cancel_requested():
            raise MigrationStopped("迁移任务已取消，可从临时文件断点继续")
        if pause_requested():
            connection.execute("UPDATE migration_runs SET status='paused' WHERE id=?", (run_id,))
            connection.commit()
            if progress:
                progress({"status": "paused", "run_id": run_id})
            while pause_requested():
                if cancel_requested():
                    raise MigrationStopped("迁移任务已取消，可从临时文件断点继续")
                time.sleep(0.1)
            connection.execute("UPDATE migration_runs SET status='running' WHERE id=?", (run_id,))
            connection.commit()

    items = connection.execute(
        "SELECT * FROM migration_items WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    try:
        for item in items:
            if item["status"] in {"verified", "audited"}:
                continue
            limit_reason = batch_limit_reason()
            if limit_reason:
                totals = _refresh_run_totals(connection, run_id)
                connection.execute(
                    """UPDATE migration_runs SET status='paused', completed_batches=completed_batches+1,
                           speed_bytes_per_second=NULL, eta_seconds=NULL, error=NULL WHERE id=?""",
                    (run_id,),
                )
                connection.execute(
                    "UPDATE migration_plans SET status='paused', note=? WHERE id=?",
                    (f"批次达到{limit_reason}上限后自动暂停；可安全继续下一批", plan["id"]),
                )
                connection.commit()
                return {
                    "run_id": run_id, "status": "paused", "reason": limit_reason,
                    "batch_files": batch_files, "batch_bytes": batch_bytes, **totals,
                }
            control()
            source, target, temporary = _item_paths(plan, item)
            stage = "preflight"
            try:
                source_stat = source.stat()
                if (
                    source_stat.st_size != item["size_bytes"]
                    or source_stat.st_mtime_ns != item["modified_ns"]
                ):
                    raise RuntimeError("源文件大小或修改时间已变化")
                if target.exists():
                    raise FileExistsError("目标文件已存在，禁止覆盖")
                target.parent.mkdir(parents=True, exist_ok=True)
                offset = temporary.stat().st_size if temporary.exists() else 0
                if offset > item["size_bytes"]:
                    raise RuntimeError("断点临时文件大于源文件")
                if shutil.disk_usage(target.parent).free < item["size_bytes"] - offset:
                    raise OSError("目标磁盘剩余空间不足，未开始当前文件")
                connection.execute(
                    "UPDATE migration_items SET status='copying', copied_bytes=?, last_error=NULL WHERE id=?",
                    (offset, item["id"]),
                )
                connection.commit()
                stage = "copy"
                with source.open("rb") as src, temporary.open("ab") as dst:
                    src.seek(offset)
                    while block := src.read(COPY_BUFFER_SIZE):
                        control()
                        dst.write(block)
                        offset += len(block)
                        session_bytes += len(block)
                        connection.execute(
                            "UPDATE migration_items SET copied_bytes=? WHERE id=?",
                            (offset, item["id"]),
                        )
                        elapsed = max(time.monotonic() - session_start, 0.001)
                        speed = session_bytes / elapsed
                        totals_now = _refresh_run_totals(connection, run_id)
                        remaining = max(run["total_bytes"] - totals_now["bytes"], 0)
                        eta = remaining / speed if speed else None
                        connection.execute(
                            "UPDATE migration_runs SET speed_bytes_per_second=?, eta_seconds=? WHERE id=?",
                            (speed, eta, run_id),
                        )
                        connection.commit()
                        if progress:
                            progress({
                                "status": "running", "run_id": run_id,
                                "source_relative": item["source_relative"],
                                "copied_bytes": totals_now["bytes"], "total_bytes": run["total_bytes"],
                                "speed_bytes_per_second": speed, "eta_seconds": eta,
                            })
                    dst.flush()
                    os.fsync(dst.fileno())
                after = source.stat()
                if after.st_size != source_stat.st_size or after.st_mtime_ns != source_stat.st_mtime_ns:
                    raise RuntimeError("复制过程中源文件发生变化")
                stage = "hash"
                source_hash = _digest(source)
                target_hash = _digest(temporary)
                if item["source_sha256"] and item["source_sha256"] != source_hash:
                    raise RuntimeError("源文件SHA-256与已审核计划不一致")
                if source_hash != target_hash:
                    temporary.unlink(missing_ok=True)
                    connection.execute(
                        "UPDATE migration_items SET copied_bytes=0 WHERE id=?", (item["id"],)
                    )
                    connection.commit()
                    raise RuntimeError("源文件与临时目标SHA-256不一致")
                stage = "rename"
                if target.exists():
                    raise FileExistsError("原子改名前目标文件已出现，禁止覆盖")
                os.utime(temporary, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
                temporary.rename(target)
                connection.execute(
                    """UPDATE migration_items SET status='verified', copied_bytes=size_bytes,
                           source_sha256=?, target_sha256=?, verified_at=?, last_error=NULL
                       WHERE id=?""",
                    (source_hash, target_hash, utc_now(), item["id"]),
                )
                connection.commit()
                _refresh_run_totals(connection, run_id)
                batch_files += 1
                batch_bytes += item["size_bytes"]
            except MigrationStopped:
                raise
            except Exception as exc:
                code = type(exc).__name__
                _record_failure(connection, run_id, item, stage, code, str(exc))
                _refresh_run_totals(connection, run_id)
                continue
    except MigrationStopped as exc:
        connection.execute(
            "UPDATE migration_runs SET status='cancelled', error=? WHERE id=?",
            (str(exc), run_id),
        )
        connection.execute("UPDATE migration_plans SET status='paused' WHERE id=?", (plan["id"],))
        connection.commit()
        return {"run_id": run_id, "status": "cancelled", "message": str(exc)}

    totals = _refresh_run_totals(connection, run_id)
    if totals["failed"]:
        connection.execute(
            "UPDATE migration_runs SET status='failed', finished_at=?, error=? WHERE id=?",
            (utc_now(), f"{totals['failed']} 个文件失败", run_id),
        )
        connection.execute("UPDATE migration_plans SET status='failed' WHERE id=?", (plan["id"],))
        connection.commit()
        _write_failure_report(connection, run_id, plan)
        return {"run_id": run_id, "status": "failed", **totals}
    connection.execute(
        "UPDATE migration_runs SET status='copied', finished_at=?, error=NULL WHERE id=?",
        (utc_now(), run_id),
    )
    connection.execute("UPDATE migration_plans SET status='copied' WHERE id=?", (plan["id"],))
    connection.commit()
    return audit_migration_run(connection, run_id, progress=progress) if auto_audit else {
        "run_id": run_id, "status": "copied", **totals,
    }


def audit_migration_run(
    connection: sqlite3.Connection, run_id: int,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    run = connection.execute("SELECT * FROM migration_runs WHERE id=?", (run_id,)).fetchone()
    if run is None or run["status"] not in {"copied", "audit_failed"}:
        raise ValueError("只有复制完成的任务才能执行全库审计")
    plan = connection.execute("SELECT * FROM migration_plans WHERE id=?", (run["plan_id"],)).fetchone()
    assert plan is not None
    connection.execute(
        "UPDATE migration_runs SET status='auditing', audit_status='running', audit_started_at=? WHERE id=?",
        (utc_now(), run_id),
    )
    connection.commit()
    failed = 0
    items = connection.execute(
        "SELECT * FROM migration_items WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    for index, item in enumerate(items, 1):
        source, target, _ = _item_paths(plan, item)
        try:
            source_stat = source.stat()
            target_stat = target.stat()
            if source_stat.st_size != item["size_bytes"] or source_stat.st_mtime_ns != item["modified_ns"]:
                raise RuntimeError("审计时源文件状态与计划不一致")
            if target_stat.st_size != item["size_bytes"]:
                raise RuntimeError("审计时目标文件大小不一致")
            source_hash = _digest(source)
            target_hash = _digest(target)
            if source_hash != item["source_sha256"] or target_hash != source_hash:
                raise RuntimeError("全库审计SHA-256不一致")
            connection.execute(
                "UPDATE migration_items SET status='audited', target_sha256=? WHERE id=?",
                (target_hash, item["id"]),
            )
        except Exception as exc:
            failed += 1
            _record_failure(connection, run_id, item, "audit", type(exc).__name__, str(exc))
        if progress:
            progress({"status": "auditing", "current": index, "total": len(items)})
    status = "audited" if failed == 0 else "audit_failed"
    connection.execute(
        """UPDATE migration_runs SET status=?, audit_status=?, audit_finished_at=?,
               failed_count=failed_count+? WHERE id=?""",
        (status, "passed" if not failed else "failed", utc_now(), failed, run_id),
    )
    connection.execute(
        "UPDATE migration_plans SET status=? WHERE id=?",
        (status, plan["id"]),
    )
    connection.commit()
    _write_failure_report(connection, run_id, plan)
    return {"run_id": run_id, "status": status, "audit_failed": failed, "total": len(items)}


def active_library_root(connection: sqlite3.Connection, default: Path) -> Path:
    row = connection.execute("SELECT active_root FROM library_state WHERE id=1").fetchone()
    return Path(row["active_root"]) if row else default


def finalize_active_library_membership(
    connection: sqlite3.Connection, run_id: int
) -> dict[str, int]:
    run = connection.execute(
        "SELECT id, plan_id, status FROM migration_runs WHERE id=?", (run_id,)
    ).fetchone()
    if run is None or run["status"] not in {"audited", "switched"}:
        raise ValueError("只有审计通过或已切换的迁移任务才能收尾活动索引")
    migrated_count = connection.execute(
        "SELECT COUNT(file_id) FROM migration_items WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    if not migrated_count:
        raise ValueError("迁移任务没有可切换的活动文件")
    excluded = connection.execute(
        """UPDATE files SET present=0 WHERE present=1 AND id NOT IN (
               SELECT file_id FROM migration_items WHERE run_id=? AND file_id IS NOT NULL
           )""",
        (run_id,),
    ).rowcount
    connection.execute(
        "DELETE FROM capture_files WHERE file_id IN (SELECT id FROM files WHERE present=0)"
    )
    protected = {
        row[0]
        for table in ("visual_fingerprints", "quality_metrics", "capture_reviews", "ai_analyses")
        for row in connection.execute(f"SELECT DISTINCT capture_id FROM {table}")
    }
    orphan_ids = {
        row[0]
        for row in connection.execute(
            """SELECT c.id FROM captures c
               WHERE NOT EXISTS (
                   SELECT 1 FROM capture_files cf WHERE cf.capture_id=c.id
               )"""
        )
    }
    removable = sorted(orphan_ids - protected)
    if removable:
        connection.executemany(
            "DELETE FROM captures WHERE id=?", ((capture_id,) for capture_id in removable)
        )
    return {
        "excluded_archive_files": excluded,
        "removed_empty_captures": len(removable),
        "preserved_protected_captures": len(orphan_ids & protected),
    }


def switch_active_library(
    connection: sqlite3.Connection, run_id: int, confirmation: str,
) -> dict[str, Any]:
    run = connection.execute("SELECT * FROM migration_runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise ValueError("迁移任务不存在")
    plan = connection.execute("SELECT * FROM migration_plans WHERE id=?", (run["plan_id"],)).fetchone()
    assert plan is not None
    expected = f"SWITCH TO ACTIVE LIBRARY PLAN {plan['id']}"
    if confirmation != expected:
        raise ValueError(f"切换确认文字不匹配；必须完整输入 {expected}")
    if run["status"] != "audited" or run["audit_status"] != "passed":
        raise ValueError("只有全库审计通过的迁移任务才能切换活动图库")
    counts = connection.execute(
        """SELECT COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE status='audited') AS audited
           FROM migration_items WHERE run_id=?""",
        (run_id,),
    ).fetchone()
    if counts["total"] != plan["item_count"] or counts["audited"] != counts["total"]:
        raise ValueError("并非所有迁移项目都已通过审计")
    target_root = Path(plan["target_root"]).resolve()
    if not target_root.is_dir():
        raise ValueError("已审计的目标图库目录不存在")

    items = connection.execute(
        "SELECT * FROM migration_items WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    with transaction(connection):
        for item in items:
            if item["file_id"] is None:
                continue
            target = (target_root / Path(item["target_relative"])).resolve()
            if not target.is_file() or not target.is_relative_to(target_root):
                raise ValueError(f"切换前目标文件不可用：{item['target_relative']}")
            relative = str(PureWindowsPath(item["target_relative"]))
            windows = PureWindowsPath(relative)
            connection.execute(
                """UPDATE files SET path=?, relative_path=?, parent_relative=?,
                       file_name=?, stem=?, extension=?, size_bytes=?, modified_ns=?
                   WHERE id=?""",
                (
                    str(target), relative, str(windows.parent), windows.name,
                    windows.stem, windows.suffix.lower(), target.stat().st_size,
                    target.stat().st_mtime_ns, item["file_id"],
                ),
            )

        finalize_active_library_membership(connection, run_id)

        marker = f"switch:{run_id}:"
        connection.execute("UPDATE captures SET capture_key=? || id", (marker,))
        captures = connection.execute(
            """SELECT c.id, MIN(f.parent_relative) AS parent_relative, MIN(f.stem) AS stem
               FROM captures c JOIN capture_files cf ON cf.capture_id=c.id
               JOIN files f ON f.id=cf.file_id GROUP BY c.id"""
        ).fetchall()
        for capture in captures:
            parent = capture["parent_relative"]
            stem = capture["stem"]
            connection.execute(
                """UPDATE captures SET parent_relative=?, stem=?, capture_key=? WHERE id=?""",
                (parent, stem, f"{parent.casefold()}/{stem.casefold()}", capture["id"]),
            )
        connection.execute(
            """INSERT INTO library_state(
                   id, archive_root, active_root, switched_at, migration_run_id, status
               ) VALUES (1, ?, ?, ?, ?, 'active')
               ON CONFLICT(id) DO UPDATE SET active_root=excluded.active_root,
                   switched_at=excluded.switched_at,
                   migration_run_id=excluded.migration_run_id, status='active'""",
            (plan["source_root"], plan["target_root"], utc_now(), run_id),
        )
        connection.execute(
            "UPDATE migration_runs SET status='switched', finished_at=? WHERE id=?",
            (utc_now(), run_id),
        )
        connection.execute(
            "UPDATE migration_plans SET status='switched', note=? WHERE id=?",
            ("全库审计通过并经再次确认；活动图库已切换，旧档案仍保留", plan["id"]),
        )
    return {
        "run_id": run_id,
        "plan_id": plan["id"],
        "archive_root": plan["source_root"],
        "active_root": plan["target_root"],
        "status": "switched",
        "stable_file_ids": counts["total"],
    }


def create_migration_plan(
    connection: sqlite3.Connection,
    source_root: Path,
    target_root: Path,
    reports_path: Path,
) -> dict[str, Any]:
    source = source_root.resolve()
    target = target_root.resolve()
    if target == source or target.is_relative_to(source):
        raise ValueError("新图库不能与原始档案相同，也不能位于原始档案内部")

    candidates: list[dict[str, Any]] = []
    excluded_count = 0
    excluded_bytes = 0
    unassigned_count = 0
    for row in _rows(connection):
        parts = PureWindowsPath(row["relative_path"]).parts
        if parts and parts[0].casefold() in {item.casefold() for item in EXCLUDED_TOP_LEVEL}:
            excluded_count += 1
            excluded_bytes += row["size_bytes"]
            continue
        target_relative, reason = _target_for(row)
        if reason == "unassigned":
            unassigned_count += 1
        candidates.append({
            "file_id": row["file_id"],
            "event_id": row["event_id"],
            "source_relative": row["relative_path"],
            "target_relative": target_relative,
            "size_bytes": row["size_bytes"],
            "modified_ns": row["modified_ns"],
            "source_sha256": row["source_sha256"],
            "status": "planned",
            "reason": reason,
        })

    by_target: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        by_target.setdefault(item["target_relative"].casefold(), []).append(item)
    for items in by_target.values():
        if len(items) > 1:
            for item in items:
                original = PureWindowsPath(item["source_relative"])
                item["target_relative"] = str(PureWindowsPath(
                    "待整理", "同名冲突", *original.parts
                ))
                item["reason"] = "duplicate_target_routed"
                unassigned_count += 1

    for item in candidates:
        if (target / Path(item["target_relative"])).exists():
            item["status"] = "conflict"
            item["reason"] = "target_exists"

    total_bytes = sum(item["size_bytes"] for item in candidates)
    conflict_count = sum(item["status"] == "conflict" for item in candidates)
    available_bytes = shutil.disk_usage(target.parent if not target.exists() else target).free
    with transaction(connection):
        cursor = connection.execute(
            """
            INSERT INTO migration_plans(
                created_at, source_root, target_root, status, item_count,
                total_bytes, excluded_count, excluded_bytes, conflict_count,
                unassigned_count, available_bytes, note
            ) VALUES (?, ?, ?, 'review', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now(), str(source), str(target), len(candidates), total_bytes,
                excluded_count, excluded_bytes, conflict_count, unassigned_count,
                available_bytes, "只读复制计划；尚未创建目录或复制照片",
            ),
        )
        plan_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO migration_items(
                plan_id, file_id, event_id, source_relative, target_relative,
                size_bytes, modified_ns, source_sha256, status, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    plan_id, item["file_id"], item["event_id"],
                    item["source_relative"], item["target_relative"],
                    item["size_bytes"], item["modified_ns"], item["source_sha256"],
                    item["status"], item["reason"],
                )
                for item in candidates
            ),
        )

    reports_path.mkdir(parents=True, exist_ok=True)
    csv_name = f"migration-plan-{plan_id}.csv"
    json_name = f"migration-plan-{plan_id}.json"
    csv_path = reports_path / csv_name
    json_path = reports_path / json_name
    fields = [
        "source_relative", "target_relative", "size_bytes", "source_sha256",
        "status", "reason", "event_id",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "safety": {
            "source_library_mutated": False,
            "directories_created": False,
            "files_copied": False,
            "files_moved": False,
            "files_deleted": False,
        },
        "plan": {
            "id": plan_id,
            "source_root": str(source),
            "target_root": str(target),
            "item_count": len(candidates),
            "total_bytes": total_bytes,
            "excluded_count": excluded_count,
            "excluded_bytes": excluded_bytes,
            "conflict_count": conflict_count,
            "unassigned_count": unassigned_count,
            "available_bytes": available_bytes,
        },
        "items": candidates,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return migration_status(connection)
