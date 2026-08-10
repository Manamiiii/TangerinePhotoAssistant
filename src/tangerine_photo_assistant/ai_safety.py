from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from typing import Any
from uuid import uuid4

from .settings import Settings


def _nearest_existing_directory(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.is_dir():
        raise FileNotFoundError(f"No existing parent directory for {path}")
    return candidate


def _competing_comfyui_processes() -> list[str]:
    if os.name != "nt":
        return []
    script = (
        "$self=$PID; Get-CimInstance Win32_Process | "
        "Where-Object { $_.ProcessId -ne $self -and "
        "($_.CommandLine -like '*Documents\\ComfyUI*' -or "
        "$_.ExecutablePath -like '*Documents\\ComfyUI*') } | "
        "ForEach-Object { \"$($_.ProcessId) $($_.Name)\" }"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def gpu_status() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"available": False, "message": "未检测到 NVIDIA GPU 状态"}
        fields = [field.strip() for field in result.stdout.splitlines()[0].split(",")]
        if len(fields) != 5:
            raise ValueError("Unexpected nvidia-smi output")
        return {
            "available": True,
            "name": fields[0],
            "utilization_percent": int(fields[1]),
            "memory_used_mb": int(fields[2]),
            "memory_total_mb": int(fields[3]),
            "temperature_c": int(fields[4]),
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"available": False, "message": "无法读取 NVIDIA GPU 状态"}


def ai_preflight(
    settings: Settings, *, check_competing_processes: bool = True
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    ready, runtime_message = settings.ai_runtime_status()
    if not ready:
        blockers.append(runtime_message)

    model_files: list[Path] = []
    incomplete: list[str] = []
    model_bytes = 0
    if settings.ai_model_path is not None and settings.ai_model_path.is_dir():
        model_files = [path for path in settings.ai_model_path.rglob("*") if path.is_file()]
        model_bytes = sum(path.stat().st_size for path in model_files)
        incomplete = [
            str(path.relative_to(settings.ai_model_path))
            for path in model_files
            if path.name.endswith((".incomplete", ".lock", ".part"))
        ]
        if incomplete:
            blockers.append(f"模型目录仍有 {len(incomplete)} 个未完成下载文件")
        if not (settings.ai_model_path / "config.json").is_file():
            blockers.append("模型目录缺少 config.json")
        if not any(path.suffix == ".safetensors" for path in model_files):
            blockers.append("模型目录缺少 Safetensors 权重")

    database_bytes = (
        settings.database_path.stat().st_size if settings.database_path.is_file() else 0
    )
    backup_root = settings.workspace / "Backups" / "AnalysisDatabase"
    try:
        free_bytes = shutil.disk_usage(
            _nearest_existing_directory(backup_root.parent)
        ).free
    except (FileNotFoundError, OSError):
        free_bytes = 0
    required_backup_bytes = max(database_bytes * 2, 256 * 1024**2)
    if not settings.database_path.is_file():
        blockers.append("分析数据库不存在")
    elif free_bytes < required_backup_bytes:
        blockers.append("数据库备份空间不足")

    competing = _competing_comfyui_processes() if check_competing_processes else []
    if competing:
        blockers.append("检测到 ComfyUI 环境进程，暂不允许启动模型任务")
    if settings.ai_quantization == "none" and model_bytes > 12 * 1024**3:
        warnings.append("大型 BF16 模型未启用量化，16GB 显存可能不足")

    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "model_path": str(settings.ai_model_path) if settings.ai_model_path else None,
        "model_file_count": len(model_files),
        "model_bytes": model_bytes,
        "incomplete_files": incomplete[:20],
        "quantization": settings.ai_quantization,
        "gpu_memory_limit_gb": settings.ai_gpu_memory_limit_gb,
        "image_max_edge": settings.ai_image_max_edge,
        "database_path": str(settings.database_path),
        "database_bytes": database_bytes,
        "backup_root": str(backup_root),
        "backup_free_bytes": free_bytes,
        "competing_processes": competing,
    }


def create_pre_ai_database_backup(settings: Settings, run_id: int) -> Path:
    if not settings.database_path.is_file():
        raise FileNotFoundError(f"Analysis database does not exist: {settings.database_path}")
    backup_root = settings.workspace / "Backups" / "AnalysisDatabase"
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_root / f"catalog-before-ai-run-{run_id}-{timestamp}.sqlite3"
    if target.exists():
        raise FileExistsError(f"Database backup already exists: {target}")
    temporary = backup_root / f".{target.name}.{uuid4().hex}.partial"
    source_uri = f"{settings.database_path.resolve().as_uri()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    destination = sqlite3.connect(temporary)
    try:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"Database backup integrity check failed: {integrity}")
    finally:
        destination.close()
        source.close()
    temporary.replace(target)
    return target


def discover_pre_ai_database_backups(
    settings: Settings, connection: sqlite3.Connection
) -> int:
    backup_root = settings.workspace / "Backups" / "AnalysisDatabase"
    if not backup_root.is_dir():
        return 0
    known_runs = {
        int(row[0]) for row in connection.execute("SELECT id FROM ai_runs")
    }
    discovered = 0
    for path in backup_root.glob("catalog-before-ai-run-*-*.sqlite3"):
        parts = path.stem.split("-")
        try:
            run_id = int(parts[4])
        except (IndexError, ValueError):
            continue
        if run_id not in known_runs:
            continue
        created_at = datetime.fromtimestamp(
            path.stat().st_mtime, timezone.utc
        ).replace(microsecond=0).isoformat()
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO ai_run_backups(
                run_id, created_at, path, size_bytes, integrity_status
            ) VALUES (?, ?, ?, ?, 'ok')
            """,
            (run_id, created_at, str(path), path.stat().st_size),
        )
        discovered += cursor.rowcount
    connection.commit()
    return discovered
