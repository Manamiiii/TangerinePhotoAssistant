"""Recover the inventory side of an interrupted human-data transaction."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4


def pending_restore_path(inventory_path: Path) -> Path:
    return inventory_path.with_name("inventory.restore-pending.json")


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _database_path(connection: sqlite3.Connection) -> str:
    return str(Path(connection.execute("PRAGMA database_list").fetchone()[2]).resolve())


def prepare_inventory_restore(
    connection: sqlite3.Connection,
    inventory_path: Path,
    previous: bytes | None,
    inventory: dict,
) -> None:
    path = pending_restore_path(inventory_path)
    if path.exists():
        raise ValueError(f"存在尚未完成的人工数据恢复记录，请重启应用核对：{path}")
    restore_id = uuid4().hex
    following = (json.dumps(inventory, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    record = {
        "version": 1,
        "restore_id": restore_id,
        "database": _database_path(connection),
        "previous": None if previous is None else base64.b64encode(previous).decode("ascii"),
        "following": base64.b64encode(following).decode("ascii"),
        "previous_sha256": None if previous is None else hashlib.sha256(previous).hexdigest(),
        "following_sha256": hashlib.sha256(following).hexdigest(),
    }
    # The witness commits with all human data, never in a separate transaction.
    connection.execute(
        "INSERT INTO human_restore_commits(restore_id,committed_at) VALUES (?,datetime('now'))",
        (restore_id,),
    )
    _atomic_bytes(path, json.dumps(record, ensure_ascii=False).encode("utf-8"))


def recover_inventory_restore(connection: sqlite3.Connection, inventory_path: Path) -> bool:
    path = pending_restore_path(inventory_path)
    if not path.exists():
        return False
    if connection.in_transaction:
        raise ValueError("人工恢复核对必须在数据库事务结束后执行")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("version") != 1:
            raise ValueError("未知恢复记录格式")
        restore_id = record["restore_id"]
        if (
            not isinstance(restore_id, str)
            or len(restore_id) != 32
            or any(c not in "0123456789abcdef" for c in restore_id)
        ):
            raise ValueError("恢复标识无效")
        if record["database"] != _database_path(connection):
            raise ValueError("恢复记录与当前数据库不匹配")
        previous = (
            None
            if record["previous"] is None
            else base64.b64decode(record["previous"], validate=True)
        )
        following = base64.b64decode(record["following"], validate=True)
        if (
            record["previous_sha256"]
            != (None if previous is None else hashlib.sha256(previous).hexdigest())
            or record["following_sha256"] != hashlib.sha256(following).hexdigest()
        ):
            raise ValueError("恢复内容校验失败")
        if not isinstance(json.loads(following), dict):
            raise TypeError("设备恢复内容无效")
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise ValueError(f"人工数据恢复记录无法核对，请保留记录及备份：{path}") from exc
    committed = (
        connection.execute(
            "SELECT 1 FROM human_restore_commits WHERE restore_id=?",
            (restore_id,),
        ).fetchone()
        is not None
    )
    current = inventory_path.read_bytes() if inventory_path.exists() else None
    if current not in (previous, following):
        raise ValueError(f"设备配置与恢复记录不一致，已暂停写入，请保留记录及备份：{path}")
    desired = following if committed else previous
    if desired != current:
        if desired is None:
            inventory_path.unlink(missing_ok=True)
        else:
            _atomic_bytes(inventory_path, desired)
    path.unlink()
    return True
