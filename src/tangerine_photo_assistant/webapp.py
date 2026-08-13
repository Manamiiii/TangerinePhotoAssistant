from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import time
import tomllib
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai_analysis import (
    PROMPT_VERSION,
    _decorate_ai_run,
    _process_exists,
    ai_results_page,
    ai_run_failures,
    ai_run_history,
    ai_run_status,
    ai_summary,
    create_ai_failure_retry_run,
    create_ai_run,
    quality_summary,
    recover_interrupted_ai_runs,
    resume_ai_run,
    update_ai_review,
    write_ai_run_report,
)
from .ai_safety import (
    ai_preflight,
    create_pre_ai_database_backup,
    discover_pre_ai_database_backups,
    gpu_status,
)
from .archive import (
    create_archive_baseline,
    recorded_active_library_status,
    recorded_archive_status,
    run_integrity_check,
)
from .database import SCHEMA_VERSION, connect, connect_readonly
from .equipment import (
    build_equipment_catalog,
    delete_equipment_item,
    save_equipment_item,
    save_equipment_ownership,
    set_equipment_visibility,
)
from .exports import ALLOWED_SHARE_EDGES, write_phone_share_export
from .grouping import (
    SimilarityGroupingError,
    list_similarity_group_revisions,
    restore_similarity_grouping,
    restore_similarity_group_revision,
    save_manual_similarity_grouping,
)
from .inventory import enrich_metadata, refresh_metadata_profile, scan_library, utc_now
from .lightroom import lightroom_status, write_lightroom_manifest
from .metadata import METADATA_PROFILE_VERSION, ExifToolMetadataReader, PillowMetadataReader
from .migration import (
    active_library_root,
    create_migration_plan,
    execute_migration_run,
    migration_preflight,
    migration_status,
    prepare_migration_run,
    switch_active_library,
)
from .pairing import rebuild_captures
from .quality import (
    analyze_quality,
    backfill_histograms,
    measure_image,
    measure_luminance_histogram,
    rebuild_group_recommendations,
)
from .reporting import build_report, write_report
from .settings import Settings, editable_config, save_editable_config
from .statistics import build_statistics
from .structure import rebuild_structure, structure_summary
from .thumbnails import ThumbnailCache
from .visual import analyze_visuals, rebuild_similarity_groups


@dataclass
class TaskState:
    id: str | None = None
    status: str = "idle"
    stage: str = "idle"
    message: str = "等待扫描"
    current: int = 0
    total: int | None = None
    error: str | None = None
    bytes_current: int = 0
    bytes_total: int | None = None
    speed_bytes_per_second: float | None = None
    items_per_second: float | None = None
    eta_seconds: float | None = None
    failure_count: int = 0
    pausable: bool = False
    result: dict[str, Any] | None = None


class AiStartRequest(BaseModel):
    mode: Literal["benchmark", "recommended"] = "benchmark"
    limit: int = Field(default=100, ge=1, le=5000)


class ReviewUpdateRequest(BaseModel):
    user_rating: int | None = None
    user_pick: bool | None = None
    user_reject: bool = False
    user_note: str | None = None


class EquipmentOwnershipRequest(BaseModel):
    kind: Literal["camera", "lens", "accessory"]
    key: str = Field(min_length=1, max_length=300)
    owned: bool


class EquipmentItemRequest(BaseModel):
    kind: Literal["camera", "lens", "accessory"]
    key: str | None = Field(default=None, max_length=300)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=50)
    section: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)
    filter_thread_mm: int | None = Field(default=None, ge=1, le=300)
    thread_mm: int | None = Field(default=None, ge=1, le=300)
    owned: bool = True


class EquipmentDeleteRequest(BaseModel):
    kind: Literal["camera", "lens", "accessory"]
    key: str = Field(min_length=1, max_length=300)


class EquipmentVisibilityRequest(EquipmentDeleteRequest):
    visible: bool


class PhoneShareExportRequest(BaseModel):
    capture_ids: list[int] = Field(min_length=1, max_length=100)
    max_edge: int = 2048
    quality: int = Field(default=90, ge=70, le=95)


class LightroomManifestRequest(BaseModel):
    scope: Literal["all", "picked", "rated", "album"] = "picked"
    album_id: int | None = Field(default=None, ge=1)


class AiReviewUpdateRequest(BaseModel):
    user_verdict: Literal["accurate", "partial", "inaccurate"] | None = None
    user_note: str | None = Field(default=None, max_length=2000)


class ArchiveBaselineRequest(BaseModel):
    name: str | None = None
    note: str | None = "永久保留的原始档案库逻辑基线"


class EventUpdateRequest(BaseModel):
    proposed_name: str
    category: str
    status: str


class AlbumCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    category: str = Field(min_length=1, max_length=40)


class AlbumTypeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class AlbumTypeUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class AlbumAssignmentRequest(BaseModel):
    capture_ids: list[int] = Field(min_length=1, max_length=500)


class ScanStartRequest(BaseModel):
    album_id: int = Field(ge=1)


class SimilarityOverrideRequest(BaseModel):
    action: Literal["exclude", "split_before", "auto"]


class SimilarityGroupEditRequest(BaseModel):
    source_group_id: int = Field(ge=1)
    groups: list[list[int]] = Field(max_length=20)
    excluded_ids: list[int] = Field(default_factory=list, max_length=500)


class SimilarityRevisionRestoreRequest(BaseModel):
    use_before: bool = False


class MigrationStartRequest(BaseModel):
    plan_id: int
    confirmation: str
    batch_max_files: int = 2000
    batch_max_gb: float = 100.0
    batch_max_minutes: int = 240


class MigrationSwitchRequest(BaseModel):
    run_id: int
    confirmation: str


class LibrarySettingsRequest(BaseModel):
    originals: str = Field(min_length=1, max_length=1000)
    workspace: str = Field(min_length=1, max_length=1000)


class CacheSettingsRequest(BaseModel):
    root: str = Field(min_length=1, max_length=1000)
    max_size_gb: int = Field(ge=1, le=4096)
    thumbnail_max_size_gb: int = Field(ge=1, le=4096)


class AnalysisSettingsRequest(BaseModel):
    raw_extensions: list[str] = Field(min_length=1, max_length=40)
    burst_time_gap_seconds: float = Field(gt=0, le=60)
    metadata_batch_size: int = Field(ge=1, le=1000)


class ToolSettingsRequest(BaseModel):
    exiftool: str = Field(default="", max_length=1000)


class ModelSettingsRequest(BaseModel):
    python: str = Field(default="", max_length=1000)
    vision_language_model: str = Field(default="", max_length=1000)
    quantization: Literal["none", "int8"] = "none"
    gpu_memory_limit_gb: int = Field(ge=1, le=256)
    max_new_tokens: int = Field(ge=1, le=8192)
    image_max_edge: int = Field(ge=512, le=2048)


class AppSettingsRequest(BaseModel):
    library: LibrarySettingsRequest
    cache: CacheSettingsRequest
    analysis: AnalysisSettingsRequest
    tools: ToolSettingsRequest
    models: ModelSettingsRequest


class TaskCancelled(RuntimeError):
    pass


class ScanTaskManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._state = TaskState()
        self._cancel = Event()
        self._pause = Event()
        self._process: subprocess.Popen[Any] | None = None
        self._migration_thread_active = False
        self._migration_run_id: int | None = None
        self._ai_run_id: int | None = None

    def attach_ai_run(self, run_id: int) -> None:
        connection = connect_readonly(self.settings.database_path)
        try:
            run = ai_run_status(connection, run_id)
        finally:
            connection.close()
        if run["status"] not in {
            "queued", "running", "pause_requested", "cancel_requested"
        }:
            return
        processed = run["completed_count"] + run["failed_count"]
        with self._lock:
            self._ai_run_id = run_id
            self._state = TaskState(
                id=f"reattached-ai-{run_id}", status="running", stage="ai-analysis",
                message=f"已重新连接模型任务：{processed:,} / {run['requested_count']:,}",
                current=processed, total=run["requested_count"],
                failure_count=run["failed_count"], pausable=True,
            )
        Thread(target=self._monitor_attached_ai, args=(run_id,), daemon=True).start()

    def _monitor_attached_ai(self, run_id: int) -> None:
        connection = connect(self.settings.database_path)
        try:
            while True:
                row = connection.execute(
                    "SELECT * FROM ai_runs WHERE id=?", (run_id,)
                ).fetchone()
                if row is None:
                    self._update(
                        status="failed", stage="failed", pausable=False,
                        error="重新连接的模型任务不存在",
                    )
                    return
                run = _decorate_ai_run(connection, row)
                processed = run["processed_count"]
                status = run["status"]
                if status in {"queued", "running", "pause_requested", "cancel_requested"}:
                    if not _process_exists(run["worker_pid"]):
                        recover_interrupted_ai_runs(connection)
                        continue
                    self._update(
                        status="running", stage="ai-analysis", current=processed,
                        total=run["requested_count"], failure_count=run["failed_count"],
                        items_per_second=(
                            1.0 / run["average_seconds_per_photo"]
                            if run["average_seconds_per_photo"] else None
                        ),
                        eta_seconds=run["estimated_remaining_seconds"],
                        pausable=status not in {"pause_requested", "cancel_requested"},
                        message=(
                            "将在当前照片完成后安全暂停模型任务…"
                            if status == "pause_requested" else
                            "将在当前照片完成后安全取消模型任务…"
                            if status == "cancel_requested" else
                            f"本地大模型分析：{processed:,} / {run['requested_count']:,}"
                        ),
                    )
                    time.sleep(1.0)
                    continue
                messages = {
                    "complete": f"本地大模型分析完成：{run['completed_count']:,} 成功，{run['failed_count']:,} 失败",
                    "paused": f"模型任务已安全暂停：{run['completed_count']:,} 张完成，可继续",
                    "cancelled": "模型任务已安全取消；已完成结果保留",
                    "failed": "本地大模型分析失败",
                }
                self._update(
                    status=status, stage=f"ai-{status}", current=processed,
                    total=run["requested_count"], failure_count=run["failed_count"],
                    eta_seconds=0.0 if status == "complete" else None,
                    pausable=False, message=messages.get(status, f"模型任务：{status}"),
                    error=run["error"],
                )
                return
        finally:
            if self._state.status != "paused":
                self._ai_run_id = None
            connection.close()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._state)

    def _update(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._state, key, value)

    def _progress(self, **changes: Any) -> None:
        if self._cancel.is_set():
            raise TaskCancelled("任务已由用户取消")
        self._update(**changes)

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            ai_run_id = (
                self._ai_run_id
                if self._state.stage.startswith("ai-")
                and self._state.status in {"running", "paused"}
                else None
            )
            ai_was_paused = self._state.status == "paused"
        if ai_run_id is not None:
            connection = connect(self.settings.database_path)
            try:
                if ai_was_paused:
                    connection.execute(
                        """
                        UPDATE ai_analyses SET status='cancelled', finished_at=?
                        WHERE run_id=? AND status != 'complete'
                        """,
                        (utc_now(), ai_run_id),
                    )
                    connection.execute(
                        "UPDATE ai_runs SET status='cancelled', finished_at=? WHERE id=?",
                        (utc_now(), ai_run_id),
                    )
                    connection.commit()
                    self._update(
                        status="cancelled", stage="ai-cancelled", pausable=False,
                        message="模型任务已取消；已完成结果保留",
                    )
                else:
                    connection.execute(
                        "UPDATE ai_runs SET status='cancel_requested' WHERE id=?",
                        (ai_run_id,),
                    )
                    connection.commit()
                    self._update(message="将在当前照片完成后安全取消模型任务…")
            finally:
                connection.close()
            return self.snapshot()
        inactive_migration_run: int | None = None
        with self._lock:
            if self._state.status not in {"running", "paused"}:
                raise RuntimeError("当前没有正在运行的任务")
            if (
                self._state.status == "paused"
                and self._state.stage.startswith("migration")
                and not self._migration_thread_active
            ):
                inactive_migration_run = self._migration_run_id
                self._state.status = "cancelled"
                self._state.stage = "migration-cancelled"
                self._state.pausable = False
                self._state.message = "已取消自动暂停的迁移任务；断点仍保留"
            else:
                self._cancel.set()
                self._state.status = "running"
                self._state.message = "正在安全停止任务…"
        if inactive_migration_run is not None:
            connection = connect(self.settings.database_path)
            try:
                connection.execute(
                    "UPDATE migration_runs SET status='cancelled', error=? WHERE id=?",
                    ("用户在批次间取消；可继续", inactive_migration_run),
                )
                connection.execute(
                    """UPDATE migration_plans SET status='paused'
                       WHERE id=(SELECT plan_id FROM migration_runs WHERE id=?)""",
                    (inactive_migration_run,),
                )
                connection.commit()
            finally:
                connection.close()
        return self.snapshot()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            ai_run_id = (
                self._ai_run_id
                if self._state.status == "running"
                and self._state.stage.startswith("ai-")
                and self._state.pausable
                else None
            )
        if ai_run_id is not None:
            connection = connect(self.settings.database_path)
            try:
                connection.execute(
                    "UPDATE ai_runs SET status='pause_requested' WHERE id=?", (ai_run_id,)
                )
                connection.commit()
            finally:
                connection.close()
            self._update(message="将在当前照片完成后安全暂停模型任务…")
            return self.snapshot()
        with self._lock:
            if self._state.status != "running" or not self._state.pausable:
                raise RuntimeError("当前任务不支持暂停")
            self._pause.set()
            self._state.message = (
                "正在暂停详情数据补全…"
                if self._state.stage.startswith("detail-")
                else "正在安全暂停迁移任务…"
            )
        return self.snapshot()

    def resume_detail_backfill(self) -> dict[str, Any]:
        with self._lock:
            if self._state.status != "paused" or not self._state.stage.startswith("detail-"):
                raise RuntimeError("当前没有已暂停的详情数据补全任务")
            self._pause.clear()
            self._state.status = "running"
            self._state.message = "正在继续补全详情数据…"
        return self.snapshot()

    def start_migration(
        self, plan_id: int, confirmation: str,
        batch_max_files: int, batch_max_gb: float, batch_max_minutes: int,
    ) -> dict[str, Any]:
        with self._lock:
            if self._state.status in {"running", "paused"}:
                raise RuntimeError("已有后台任务正在运行")
        connection = connect(self.settings.database_path)
        try:
            prepared = prepare_migration_run(
                connection, plan_id, confirmation,
                batch_max_files=batch_max_files,
                batch_max_bytes=int(batch_max_gb * 1024**3),
                batch_max_seconds=batch_max_minutes * 60,
            )
        finally:
            connection.close()
        return self._launch_migration(int(prepared["run_id"]), int(prepared["total_bytes"]))

    def resume_migration(self, run_id: int) -> dict[str, Any]:
        with self._lock:
            if (
                self._state.status == "paused"
                and self._migration_thread_active
                and self._pause.is_set()
            ):
                self._pause.clear()
                self._state.status = "running"
                self._state.message = "正在继续安全复制…"
                return asdict(self._state)
            if self._state.status == "running":
                raise RuntimeError("已有后台任务正在运行")
        connection = connect(self.settings.database_path)
        try:
            run = connection.execute(
                "SELECT total_bytes FROM migration_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError("迁移任务不存在")
            total_bytes = int(run["total_bytes"])
        finally:
            connection.close()
        return self._launch_migration(run_id, total_bytes)

    def _launch_migration(self, run_id: int, total_bytes: int) -> dict[str, Any]:
        with self._lock:
            task_id = uuid4().hex
            self._state = TaskState(
                id=task_id, status="running", stage="migration-copy",
                message="正在执行安全复制与逐文件校验…", bytes_total=total_bytes,
                pausable=True,
            )
            self._cancel.clear()
            self._pause.clear()
            self._migration_thread_active = True
            self._migration_run_id = run_id
        Thread(target=self._run_migration, args=(run_id,), daemon=True).start()
        return self.snapshot()

    def _run_migration(self, run_id: int) -> None:
        connection = connect(self.settings.database_path)
        try:
            def update(values: dict[str, Any]) -> None:
                if values.get("status") == "paused":
                    self._update(status="paused", message="迁移已暂停；临时文件保留用于续传")
                    return
                if values.get("status") == "auditing":
                    self._update(
                        status="running", stage="migration-audit",
                        current=int(values.get("current", 0)), total=values.get("total"),
                        message=f"正在执行全库审计：{values.get('current', 0):,} / {values.get('total', 0):,}",
                    )
                    return
                self._update(
                    status="running", stage="migration-copy",
                    bytes_current=int(values.get("copied_bytes", self._state.bytes_current)),
                    speed_bytes_per_second=values.get("speed_bytes_per_second"),
                    eta_seconds=values.get("eta_seconds"),
                    message=f"正在复制：{values.get('source_relative', '')}",
                )

            result = execute_migration_run(
                connection, run_id,
                pause_requested=self._pause.is_set,
                cancel_requested=self._cancel.is_set,
                progress=update,
            )
            if result["status"] == "audited":
                self._update(
                    status="complete", stage="migration-audited", pausable=False,
                    current=result["total"], total=result["total"],
                    message="迁移复制与全库审计已通过；尚未切换活动图库",
                )
            elif result["status"] == "cancelled":
                self._update(
                    status="cancelled", stage="migration-cancelled", pausable=False,
                    message=result["message"],
                )
            elif result["status"] == "paused":
                labels = {"files": "文件数", "bytes": "数据量", "time": "运行时长"}
                with self._lock:
                    self._migration_thread_active = False
                self._update(
                    status="paused", stage="migration-batch-paused", pausable=False,
                    message=(
                        f"本批已安全完成 {result['batch_files']:,} 个文件，"
                        f"达到{labels.get(result['reason'], '批次')}上限"
                    ),
                )
            else:
                self._update(
                    status="failed", stage="migration-failed", pausable=False,
                    failure_count=int(result.get("failed", result.get("audit_failed", 0))),
                    message="迁移任务存在失败文件，已保留失败清单与断点",
                )
        except Exception as exc:
            self._update(
                status="failed", stage="migration-failed", pausable=False,
                message="迁移任务失败", error=str(exc),
            )
        finally:
            with self._lock:
                if self._state.status != "running":
                    self._migration_thread_active = False
            connection.close()

    def start(self, album_id: int) -> dict[str, Any]:
        with self._lock:
            if self._state.status == "running":
                raise RuntimeError("已有扫描任务正在运行")
            connection = connect_readonly(self.settings.database_path)
            try:
                if connection.execute(
                    "SELECT 1 FROM events WHERE id=? AND status!='archived'", (album_id,)
                ).fetchone() is None:
                    raise ValueError("目标相册不存在")
            finally:
                connection.close()
            task_id = uuid4().hex
            self._state = TaskState(
                id=task_id,
                status="running",
                stage="indexing",
                message="正在核对文件…",
            )
            self._cancel.clear()
        Thread(target=self._run, args=(task_id, album_id), daemon=True).start()
        return self.snapshot()

    def start_visual(self) -> dict[str, Any]:
        with self._lock:
            if self._state.status == "running":
                raise RuntimeError("已有后台任务正在运行")
            task_id = uuid4().hex
            self._state = TaskState(
                id=task_id,
                status="running",
                stage="duplicates",
                message="正在核对精确重复候选…",
            )
            self._cancel.clear()
        Thread(target=self._run_visual, args=(task_id,), daemon=True).start()
        return self.snapshot()

    def _run_visual(self, task_id: str) -> None:
        connection = connect(self.settings.database_path)
        try:
            def update(stage: str, current: int, total: int) -> None:
                label = "执行图库完整性核对" if stage == "duplicates" else "生成画面指纹"
                self._progress(
                    stage=stage, current=current, total=total,
                    message=f"{label}：{current:,} / {total:,}",
                )

            result = analyze_visuals(
                connection, progress=update,
                exiftool=self.settings.find_exiftool(),
                metadata_batch_size=self.settings.metadata_batch_size,
            )
            self._update(
                status="complete", stage="complete", current=1, total=1,
                message=(
                    f"视觉预筛完成：{result['duplicate_groups']:,} 组精确重复，"
                    f"{result['similarity_groups']:,} 组相似连拍"
                ),
            )
        except TaskCancelled:
            self._update(status="cancelled", stage="cancelled", message="视觉预筛已取消")
        except Exception as exc:
            self._update(
                status="failed", stage="failed", message="视觉预筛失败", error=str(exc)
            )
        finally:
            connection.close()

    def start_quality(self) -> dict[str, Any]:
        with self._lock:
            if self._state.status == "running":
                raise RuntimeError("已有后台任务正在运行")
            task_id = uuid4().hex
            self._state = TaskState(
                id=task_id, status="running", stage="quality",
                message="正在准备技术质量分析…",
            )
            self._cancel.clear()
        Thread(target=self._run_quality, args=(task_id,), daemon=True).start()
        return self.snapshot()

    def _run_quality(self, task_id: str) -> None:
        connection = connect(self.settings.database_path)
        try:
            result = analyze_quality(
                connection,
                progress=lambda current, total: self._progress(
                    stage="quality", current=current, total=total,
                    message=f"技术质量分析：{current:,} / {total:,}",
                ),
            )
            self._update(
                status="complete", stage="complete", current=1, total=1,
                message=(
                    f"技术质量分析完成：{result['quality_updated']:,} 张更新，"
                    f"{result['recommended_picks']:,} 张组内推荐"
                ),
            )
        except TaskCancelled:
            self._update(status="cancelled", stage="cancelled", message="技术质量分析已取消")
        except Exception as exc:
            self._update(
                status="failed", stage="failed", message="技术质量分析失败", error=str(exc)
            )
        finally:
            connection.close()

    def start_detail_backfill(self) -> dict[str, Any]:
        exiftool = self.settings.find_exiftool()
        if exiftool is None:
            raise RuntimeError("扩展元数据补全需要 ExifTool")
        with self._lock:
            if self._state.status in {"running", "paused"}:
                raise RuntimeError("已有后台任务正在运行")
            task_id = uuid4().hex
            self._state = TaskState(
                id=task_id, status="running", stage="detail-metadata",
                message="正在准备扩展拍摄信息补全…", pausable=True,
            )
            self._cancel.clear()
            self._pause.clear()
        Thread(
            target=self._run_detail_backfill, args=(task_id, exiftool), daemon=True
        ).start()
        return self.snapshot()

    def _detail_progress(self, stage: str, current: int, total: int) -> None:
        if self._cancel.is_set():
            raise TaskCancelled("详情数据补全已由用户取消")
        while self._pause.is_set():
            self._update(
                status="paused", stage=stage, current=current, total=total,
                message=f"详情数据补全已暂停：{current:,} / {total:,}",
            )
            if self._cancel.wait(0.2):
                raise TaskCancelled("详情数据补全已由用户取消")
        self._update(
            status="running", stage=stage, current=current, total=total,
            message=f"详情数据补全：{current:,} / {total:,}",
        )

    def _run_detail_backfill(self, task_id: str, exiftool: Path) -> None:
        connection = connect(self.settings.database_path)
        try:
            metadata = refresh_metadata_profile(
                connection,
                ExifToolMetadataReader(exiftool, self.settings.metadata_batch_size),
                progress=lambda current, total: self._detail_progress(
                    "detail-metadata", current, total
                ),
            )
            self._update(
                stage="detail-histograms", current=0, total=None,
                message="扩展拍摄信息已完成，正在补全 JPG 亮度直方图…",
            )
            histograms = backfill_histograms(
                connection,
                progress=lambda current, total: self._detail_progress(
                    "detail-histograms", current, total
                ),
                exiftool=exiftool,
                batch_size=self.settings.metadata_batch_size,
            )
            result = {**metadata, **histograms}
            self._update(
                status="complete", stage="complete", pausable=False,
                current=1, total=1, result=result,
                message=(
                    f"详情数据补全完成：{metadata['metadata_updated']:,} 个文件元数据，"
                    f"{histograms['histograms_updated']:,} 张直方图"
                ),
            )
        except TaskCancelled:
            self._update(
                status="cancelled", stage="cancelled", pausable=False,
                message="详情数据补全已取消；已完成的数据已保留",
            )
        except Exception as exc:
            self._update(
                status="failed", stage="failed", pausable=False,
                message="详情数据补全失败", error=str(exc),
            )
        finally:
            connection.close()

    def start_ai(self, mode: str, limit: int, config_path: Path) -> dict[str, Any]:
        preflight = ai_preflight(self.settings)
        if not preflight["ready"]:
            raise RuntimeError("；".join(preflight["blockers"]))
        with self._lock:
            if self._state.status == "running":
                raise RuntimeError("已有后台任务正在运行")
            task_id = uuid4().hex
            self._state = TaskState(
                id=task_id, status="running", stage="ai-preparing",
                message="正在创建本地大模型任务…", pausable=True,
            )
            self._cancel.clear()
        Thread(
            target=self._run_ai,
            args=(task_id, mode, limit, config_path, None), daemon=True,
        ).start()
        return self.snapshot()

    def resume_ai(self, run_id: int, config_path: Path) -> dict[str, Any]:
        preflight = ai_preflight(self.settings)
        if not preflight["ready"]:
            raise RuntimeError("；".join(preflight["blockers"]))
        with self._lock:
            if self._state.status == "running":
                raise RuntimeError("已有后台任务正在运行")
            task_id = uuid4().hex
            self._state = TaskState(
                id=task_id, status="running", stage="ai-preparing",
                message=f"正在继续模型任务 {run_id}…", pausable=True,
            )
            self._cancel.clear()
        Thread(
            target=self._run_ai,
            args=(task_id, "benchmark", 1, config_path, run_id), daemon=True,
        ).start()
        return self.snapshot()

    def retry_ai_failures(self, run_id: int, config_path: Path) -> dict[str, Any]:
        preflight = ai_preflight(self.settings)
        if not preflight["ready"]:
            raise RuntimeError("；".join(preflight["blockers"]))
        with self._lock:
            if self._state.status == "running":
                raise RuntimeError("已有后台任务正在运行")
            task_id = uuid4().hex
            self._state = TaskState(
                id=task_id, status="running", stage="ai-preparing",
                message=f"正在为任务 {run_id} 创建失败项重试…", pausable=True,
            )
            self._cancel.clear()
        Thread(
            target=self._run_ai,
            args=(task_id, "retry", 1, config_path, None, run_id), daemon=True,
        ).start()
        return self.snapshot()

    def _run_ai(
        self, task_id: str, mode: str, limit: int,
        config_path: Path, existing_run_id: int | None,
        failed_source_run_id: int | None = None,
    ) -> None:
        connection = connect(self.settings.database_path)
        try:
            if existing_run_id is not None:
                run = resume_ai_run(connection, existing_run_id)
            elif failed_source_run_id is not None:
                run = create_ai_failure_retry_run(
                    connection, failed_source_run_id,
                    self.settings.ai_model_path,  # type: ignore[arg-type]
                    self.settings.ai_quantization,
                )
            else:
                run = create_ai_run(
                    connection, self.settings.ai_model_path, mode, limit,  # type: ignore[arg-type]
                    self.settings.ai_quantization,
                )
            run_id = int(run["run_id"])
            self._ai_run_id = run_id
            total = int(run["requested_count"])
            self._update(
                stage="ai-backup", current=0, total=total,
                message="正在创建分析前数据库备份…",
            )
            backup_path = create_pre_ai_database_backup(self.settings, run_id)
            connection.execute(
                """
                INSERT INTO ai_run_backups(
                    run_id, created_at, path, size_bytes, integrity_status
                ) VALUES (?, ?, ?, ?, 'ok')
                """,
                (run_id, utc_now(), str(backup_path), backup_path.stat().st_size),
            )
            connection.commit()
            self._update(
                stage="ai-loading", current=0, total=total,
                message=(
                    f"数据库已备份到 {backup_path.name}；正在加载本地 Qwen3-VL，"
                    f"计划分析 {total:,} 张…"
                ),
            )
            project_root = Path(__file__).resolve().parents[2]
            environment = os.environ.copy()
            existing_path = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = str(project_root / "src") + (
                os.pathsep + existing_path if existing_path else ""
            )
            environment["HF_HUB_OFFLINE"] = "1"
            environment["TRANSFORMERS_OFFLINE"] = "1"
            environment["PYTHONUTF8"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
            command = [
                str(self.settings.ai_python), "-m", "tangerine_photo_assistant.ai_worker",
                "--config", str(config_path.resolve()), "--run-id", str(run_id),
            ]
            log_path = self.settings.reports_path / f"ai-run-{run_id}.log"
            error_path = self.settings.reports_path / f"ai-run-{run_id}-error.log"
            self.settings.reports_path.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as output, error_path.open(
                "a", encoding="utf-8"
            ) as errors:
                marker = f"\n=== worker start {utc_now()} ===\n"
                output.write(marker)
                errors.write(marker)
                output.flush()
                errors.flush()
                process = subprocess.Popen(
                    command, cwd=project_root, env=environment,
                    stdout=output, stderr=errors,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._process = process
                while process.poll() is None:
                    if self._cancel.is_set():
                        process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        connection.execute(
                            """
                            UPDATE ai_analyses SET status='cancelled', finished_at=?
                            WHERE run_id=? AND status IN ('queued', 'running')
                            """,
                            (utc_now(), run_id),
                        )
                        connection.execute(
                            "UPDATE ai_runs SET status='cancelled', finished_at=? WHERE id=?",
                            (utc_now(), run_id),
                        )
                        connection.commit()
                        raise TaskCancelled("模型任务已由用户取消")
                    status = connection.execute(
                        """
                        SELECT ar.status, ar.completed_count, ar.failed_count,
                               AVG(
                                   CASE WHEN aa.started_at IS NOT NULL
                                             AND aa.finished_at IS NOT NULL
                                        THEN (julianday(aa.finished_at) -
                                              julianday(aa.started_at)) * 86400.0
                                   END
                               ) AS average_seconds
                        FROM ai_runs ar
                        LEFT JOIN ai_analyses aa ON aa.run_id = ar.id
                        WHERE ar.id=?
                        GROUP BY ar.id
                        """,
                        (run_id,),
                    ).fetchone()
                    completed = (status["completed_count"] + status["failed_count"]) if status else 0
                    average_seconds = status["average_seconds"] if status else None
                    self._update(
                        stage="ai-analysis", current=completed, total=total,
                        failure_count=(status["failed_count"] if status else 0),
                        items_per_second=(
                            1.0 / average_seconds if average_seconds else None
                        ),
                        eta_seconds=(
                            max(0, total - completed) * average_seconds
                            if average_seconds else None
                        ),
                        message=f"本地大模型分析：{completed:,} / {total:,}",
                    )
                    time.sleep(1.0)
                self._process = None
            final = connection.execute(
                "SELECT status, completed_count, failed_count, error FROM ai_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if final is not None and final["status"] == "paused":
                self._update(
                    status="paused", stage="ai-paused", pausable=False,
                    failure_count=final["failed_count"], eta_seconds=None,
                    message=(
                        f"模型任务已安全暂停：{final['completed_count']:,} 张完成，"
                        "可从历史任务继续"
                    ),
                )
                return
            if final is not None and final["status"] == "cancelled":
                self._update(
                    status="cancelled", stage="ai-cancelled", pausable=False,
                    failure_count=final["failed_count"], eta_seconds=None,
                    message="模型任务已安全取消；已完成结果保留",
                )
                return
            if process.returncode not in (0, 2) or final is None or final["status"] == "failed":
                raise RuntimeError(final["error"] if final and final["error"] else "模型进程异常退出")
            self._update(
                status="complete", stage="complete", current=total, total=total,
                failure_count=final["failed_count"], eta_seconds=0.0, pausable=False,
                message=(
                    f"本地大模型分析完成：{final['completed_count']:,} 成功，"
                    f"{final['failed_count']:,} 失败"
                ),
            )
        except TaskCancelled:
            self._update(status="cancelled", stage="cancelled", message="本地大模型任务已取消")
        except Exception as exc:
            self._update(
                status="failed", stage="failed", message="本地大模型分析失败", error=str(exc)
            )
        finally:
            self._process = None
            if self._state.status != "paused":
                self._ai_run_id = None
            connection.close()

    def _run(self, task_id: str, album_id: int) -> None:
        connection = connect(self.settings.database_path)
        try:
            run_id = scan_library(
                connection,
                self.settings,
                metadata_reader=None,
                progress=lambda count: self._progress(
                    current=count, message=f"已核对 {count:,} 个文件"
                ),
            )
            exiftool = self.settings.find_exiftool()
            self._update(
                stage="metadata",
                current=0,
                total=None,
                message="正在读取新增照片的拍摄参数…",
            )
            metadata_reader = (
                ExifToolMetadataReader(exiftool, self.settings.metadata_batch_size)
                if exiftool is not None else PillowMetadataReader()
            )
            enrich_metadata(
                connection,
                self.settings,
                metadata_reader,
                progress=lambda current, total: self._progress(
                    current=current,
                    total=total,
                    message=f"已读取 {current:,} / {total:,} 个新增文件",
                ),
            )
            self._update(stage="pairing", message="正在配对 JPG 与 RAW…")
            rebuild_captures(connection)
            self._update(stage="structure", message="正在更新相册建议与连拍候选…")
            rebuild_structure(connection, self.settings.burst_time_gap_seconds)
            self._update(stage="album", message="正在把新增照片归入目标相册…")
            capture_ids = [
                row[0] for row in connection.execute(
                    """SELECT DISTINCT cf.capture_id FROM capture_files cf
                       JOIN files f ON f.id=cf.file_id
                       WHERE f.first_seen_run_id=? AND f.present=1""",
                    (run_id,),
                )
            ]
            assigned_count = _assign_captures_to_album(
                connection, album_id, capture_ids
            ) if capture_ids else 0
            self._update(stage="reporting", message="正在更新审计报告…")
            write_report(build_report(connection), self.settings.reports_path)
            self._update(
                status="complete",
                stage="complete",
                message=f"图库更新完成：{assigned_count:,} 张新增照片已归入相册",
                result={
                    "scan_run_id": run_id,
                    "album_id": album_id,
                    "assigned_count": assigned_count,
                },
            )
        except TaskCancelled:
            self._update(status="cancelled", stage="cancelled", message="扫描已取消")
        except Exception as exc:
            self._update(
                status="failed",
                stage="failed",
                message="扫描失败",
                error=str(exc),
            )
        finally:
            connection.close()


def _query_overview(settings: Settings) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        report = build_report(connection)
        latest = connection.execute(
            """
            SELECT id, started_at, finished_at, status, files_seen
            FROM scan_runs ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        capture_total = connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
        dated_captures = connection.execute(
            "SELECT COUNT(*) FROM captures WHERE captured_at IS NOT NULL"
        ).fetchone()[0]
        return {
            **report,
            "capture_total": capture_total,
            "dated_captures": dated_captures,
            "latest_scan": dict(latest) if latest else None,
            "cameras": report["cameras"][:6],
            "lenses": report["lenses"][:8],
            "structure": structure_summary(connection),
            "visual": _visual_summary(connection),
        }
    finally:
        connection.close()


def _query_inbox(settings: Settings, limit: int) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        # Keep showing the most recent batch that actually introduced files.
        # A no-op incremental scan should not make the inbox appear empty.
        latest_run = connection.execute(
            "SELECT MAX(first_seen_run_id) FROM files WHERE present = 1"
        ).fetchone()[0]
        if latest_run is None:
            return {"scan_run_id": None, "count": 0, "items": []}
        count = connection.execute(
            """
            SELECT COUNT(DISTINCT cf.capture_id)
            FROM capture_files cf
            JOIN files f ON f.id = cf.file_id
            WHERE f.present = 1 AND f.first_seen_run_id = ?
            """,
            (latest_run,),
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT
                c.id, c.parent_relative, c.stem, c.captured_at, c.pairing_status,
                MAX(f.camera_model) AS camera_model,
                MAX(f.lens_model) AS lens_model,
                COUNT(cf.file_id) AS file_count
            FROM captures c
            JOIN capture_files cf ON cf.capture_id = c.id
            JOIN files f ON f.id = cf.file_id
            WHERE f.present = 1 AND f.first_seen_run_id = ?
            GROUP BY c.id
            ORDER BY COALESCE(c.captured_at, '') DESC, c.id DESC
            LIMIT ?
            """,
            (latest_run, limit),
        ).fetchall()
        return {
            "scan_run_id": latest_run,
            "count": count,
            "items": [dict(row) for row in rows],
        }
    finally:
        connection.close()


def _query_library_captures(
    settings: Settings,
    limit: int,
    offset: int,
    *,
    album_id: int | None = None,
    unassigned_only: bool = False,
    category: str | None = None,
    camera_model: str | None = None,
    lens_model: str | None = None,
    rating: int | None = None,
    selection: str | None = None,
    quality: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    sort: str = "newest",
    collapse_groups: bool = False,
) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        conditions = [
            "f.present = 1",
            "cf.file_id = (SELECT MIN(cf2.file_id) FROM capture_files cf2 JOIN files f2 ON f2.id = cf2.file_id WHERE cf2.capture_id = c.id AND cf2.role = 'jpeg' AND f2.present = 1)",
        ]
        parameters: list[Any] = []
        if album_id is not None:
            conditions.append("e.id = ?")
            parameters.append(album_id)
        elif unassigned_only:
            conditions.append("e.id IS NULL")
        if category:
            conditions.append("e.category = ?")
            parameters.append(category)
        if camera_model:
            conditions.append("f.camera_model = ?")
            parameters.append(camera_model)
        if lens_model:
            conditions.append("f.lens_model = ?")
            parameters.append(lens_model)
        if rating is not None:
            conditions.append("cr.user_rating = ?")
            parameters.append(rating)
        if selection == "picked":
            conditions.append("COALESCE(cr.user_pick, 0) = 1")
        elif selection == "rejected":
            conditions.append("COALESCE(cr.user_reject, 0) = 1")
        elif selection == "unreviewed":
            conditions.append("cr.user_rating IS NULL AND COALESCE(cr.user_pick, 0) = 0 AND COALESCE(cr.user_reject, 0) = 0")
        if quality == "problems":
            conditions.append(
                "qm.issue_json IS NOT NULL AND qm.issue_json NOT IN ('', '[]')"
            )
        elif quality == "low":
            conditions.append("qm.technical_score < 70")
        elif quality == "high":
            conditions.append("qm.technical_score >= 85")
        elif quality == "unanalyzed":
            conditions.append("qm.technical_score IS NULL")
        if date_from:
            conditions.append("substr(c.captured_at, 1, 10) >= ?")
            parameters.append(date_from)
        if date_to:
            conditions.append("substr(c.captured_at, 1, 10) <= ?")
            parameters.append(date_to)
        if search:
            conditions.append("(c.stem LIKE ? OR e.proposed_name LIKE ? OR c.parent_relative LIKE ?)")
            term = f"%{search.strip()}%"
            parameters.extend((term, term, term))
        where_sql = " AND ".join(conditions)
        from_sql = """
            FROM captures c
            JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
            JOIN files f ON f.id = cf.file_id
            LEFT JOIN event_captures ec ON ec.capture_id = c.id
            LEFT JOIN events e ON e.id = ec.event_id
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            LEFT JOIN similarity_group_captures sgc ON sgc.capture_id = c.id
            LEFT JOIN similarity_groups sg ON sg.id = sgc.group_id
            LEFT JOIN quality_metrics qm ON qm.capture_id = c.id
            LEFT JOIN similarity_group_overrides sgo ON sgo.capture_id = c.id
            LEFT JOIN (
                SELECT members.group_id,
                       SUM(CASE WHEN COALESCE(reviews.user_pick, 0)=1 THEN 1 ELSE 0 END) AS pick_count,
                       SUM(CASE WHEN COALESCE(reviews.user_reject, 0)=1 THEN 1 ELSE 0 END) AS reject_count,
                       SUM(CASE WHEN reviews.user_rating IS NULL
                                     AND COALESCE(reviews.user_pick, 0)=0
                                     AND COALESCE(reviews.user_reject, 0)=0 THEN 1 ELSE 0 END) AS unreviewed_count
                FROM similarity_group_captures members
                LEFT JOIN capture_reviews reviews ON reviews.capture_id=members.capture_id
                GROUP BY members.group_id
            ) group_stats ON group_stats.group_id=sg.id
        """
        ordering = {
            "oldest": "c.captured_at IS NULL, c.captured_at ASC, c.id ASC",
            "name": "c.stem COLLATE NOCASE ASC, c.id ASC",
            "rating": "cr.user_rating IS NULL, cr.user_rating DESC, c.captured_at DESC",
        }.get(sort, "c.captured_at IS NULL, c.captured_at DESC, c.id DESC")
        row_sql = f"""
            SELECT c.id, c.stem, c.captured_at, c.pairing_status,
                   f.camera_model, f.lens_model, e.id AS album_id,
                   e.proposed_name AS album_name, e.category,
                   cr.user_rating, cr.user_pick, cr.user_reject, cr.user_note,
                   cr.auto_pick, qm.technical_score,
                   sgo.action AS grouping_override, sgo.manual_batch_key,
                   COALESCE((
                       SELECT SUM(member_file.size_bytes)
                       FROM capture_files member_cf
                       JOIN files member_file ON member_file.id=member_cf.file_id
                       WHERE member_cf.capture_id=c.id AND member_file.present=1
                   ), 0) AS size_bytes,
                   MAX(sg.id) AS similarity_group_id,
                   MAX(sg.capture_count) AS similarity_group_size,
                   MAX(group_stats.pick_count) AS group_pick_count,
                   MAX(group_stats.reject_count) AS group_reject_count,
                   MAX(group_stats.unreviewed_count) AS group_unreviewed_count
            {from_sql}
            WHERE {where_sql}
            GROUP BY c.id
            ORDER BY {ordering}
            """
        if collapse_groups:
            rows = connection.execute(row_sql, parameters).fetchall()
        else:
            rows = connection.execute(
                f"{row_sql} LIMIT ? OFFSET ?", (*parameters, limit, offset)
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["thumbnail_url"] = f"/api/thumbnails/{item['id']}?size=640"
            item["item_type"] = "photo"
            item["selection_capture_ids"] = [item["id"]]
            items.append(item)
        if collapse_groups:
            folded: list[dict[str, Any]] = []
            positions: dict[int, int] = {}
            members: dict[int, list[dict[str, Any]]] = {}
            for item in items:
                group_id = item["similarity_group_id"]
                if group_id is None:
                    folded.append(item)
                    continue
                members.setdefault(group_id, []).append(item)
                if group_id not in positions:
                    positions[group_id] = len(folded)
                    group_item = dict(item)
                    group_item["item_type"] = "group"
                    folded.append(group_item)
                    continue
                current = folded[positions[group_id]]
                candidate_rank = (
                    int(bool(item["user_pick"])), item["user_rating"] or 0,
                    int(bool(item["auto_pick"])), item["technical_score"] or -1,
                )
                current_rank = (
                    int(bool(current["user_pick"])), current["user_rating"] or 0,
                    int(bool(current["auto_pick"])), current["technical_score"] or -1,
                )
                if candidate_rank > current_rank:
                    replacement = dict(item)
                    replacement["item_type"] = "group"
                    folded[positions[group_id]] = replacement
            for group_id, group_members in members.items():
                group_item = folded[positions[group_id]]
                group_item["selection_capture_ids"] = [item["id"] for item in group_members]
                group_item["size_bytes"] = sum(item["size_bytes"] for item in group_members)
            total = len(folded)
            return {
                "count": total, "limit": limit, "offset": offset,
                "items": folded[offset:offset + limit], "collapsed": True,
            }
        total = connection.execute(
            f"SELECT COUNT(DISTINCT c.id) {from_sql} WHERE {where_sql}",
            parameters,
        ).fetchone()[0]
        return {"count": total, "limit": limit, "offset": offset, "items": items,
                "collapsed": False}
    finally:
        connection.close()


def _query_library_filters(settings: Settings) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        albums = connection.execute(
            """SELECT id, proposed_name AS name, category, capture_count, status
               FROM events WHERE status != 'archived'
               ORDER BY start_at IS NULL, start_at DESC, proposed_name"""
        ).fetchall()
        types = connection.execute(
            "SELECT name, built_in FROM album_types ORDER BY sort_order, name"
        ).fetchall()
        cameras = connection.execute(
            """SELECT DISTINCT camera_model FROM files
               WHERE present=1 AND camera_model IS NOT NULL AND camera_model!=''
               ORDER BY camera_model"""
        ).fetchall()
        lenses = connection.execute(
            """SELECT DISTINCT lens_model FROM files
               WHERE present=1 AND lens_model IS NOT NULL AND lens_model!=''
               ORDER BY lens_model"""
        ).fetchall()
        return {
            "albums": [dict(row) for row in albums],
            "album_types": [dict(row) for row in types],
            "cameras": [row[0] for row in cameras],
            "lenses": [row[0] for row in lenses],
        }
    finally:
        connection.close()


def _assign_captures_to_album(
    connection: sqlite3.Connection, album_id: int, capture_ids: list[int]
) -> int:
    capture_ids = sorted(set(capture_ids))
    if not capture_ids:
        return 0
    if connection.execute(
        "SELECT 1 FROM events WHERE id=? AND status!='archived'", (album_id,)
    ).fetchone() is None:
        raise ValueError("目标相册不存在")
    placeholders = ",".join("?" for _ in capture_ids)
    existing_ids = {
        row[0] for row in connection.execute(
            f"SELECT id FROM captures WHERE id IN ({placeholders})", capture_ids
        )
    }
    if len(existing_ids) != len(capture_ids):
        raise ValueError("选择中包含不存在的照片")
    affected = {
        row[0] for row in connection.execute(
            f"SELECT DISTINCT event_id FROM event_captures WHERE capture_id IN ({placeholders})",
            capture_ids,
        )
    }
    connection.execute(
        f"DELETE FROM event_captures WHERE capture_id IN ({placeholders})", capture_ids
    )
    next_sequence = connection.execute(
        "SELECT COALESCE(MAX(sequence_index), -1) + 1 FROM event_captures WHERE event_id=?",
        (album_id,),
    ).fetchone()[0]
    connection.executemany(
        "INSERT INTO event_captures(event_id, capture_id, sequence_index) VALUES (?, ?, ?)",
        (
            (album_id, capture_id, next_sequence + index)
            for index, capture_id in enumerate(capture_ids)
        ),
    )
    affected.add(album_id)
    for affected_id in affected:
        connection.execute("DELETE FROM event_sources WHERE event_id=?", (affected_id,))
        connection.execute(
            """INSERT INTO event_sources(event_id, parent_relative)
               SELECT ?, c.parent_relative FROM event_captures ec
               JOIN captures c ON c.id=ec.capture_id
               WHERE ec.event_id=? GROUP BY c.parent_relative""",
            (affected_id, affected_id),
        )
        connection.execute(
            """UPDATE events SET
                   capture_count=(SELECT COUNT(*) FROM event_captures WHERE event_id=?),
                   start_at=(SELECT MIN(c.captured_at) FROM event_captures ec JOIN captures c ON c.id=ec.capture_id WHERE ec.event_id=?),
                   end_at=(SELECT MAX(c.captured_at) FROM event_captures ec JOIN captures c ON c.id=ec.capture_id WHERE ec.event_id=?),
                   status=CASE WHEN id=? THEN 'confirmed' ELSE status END,
                   updated_at=? WHERE id=?""",
            (
                affected_id, affected_id, affected_id, album_id,
                utc_now(), affected_id,
            ),
        )
    connection.commit()
    return len(capture_ids)


def _query_events(settings: Settings, limit: int, offset: int) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        total = connection.execute(
            "SELECT COUNT(*) FROM events WHERE status != 'archived'"
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT
                e.id, e.proposed_name, e.category, e.date_label, e.start_at, e.end_at,
                e.capture_count, e.status, e.confidence, e.reason_json,
                COUNT(DISTINCT es.parent_relative) AS source_count,
                COUNT(DISTINCT b.id) AS burst_count,
                COALESCE(MAX(b.capture_count), 0) AS largest_burst
            FROM events e
            LEFT JOIN event_sources es ON es.event_id = e.id
            LEFT JOIN bursts b ON b.event_id = e.id
            WHERE e.status != 'archived'
            GROUP BY e.id
            ORDER BY e.start_at IS NULL, e.start_at DESC, e.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["reason"] = json.loads(item.pop("reason_json"))
            item["sources"] = [
                source[0]
                for source in connection.execute(
                    """
                    SELECT parent_relative FROM event_sources
                    WHERE event_id = ? ORDER BY parent_relative
                    """,
                    (row["id"],),
                )
            ]
            items.append(item)
        return {"count": total, "limit": limit, "offset": offset, "items": items}
    finally:
        connection.close()


def _query_bursts(settings: Settings, limit: int, offset: int) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        total = connection.execute("SELECT COUNT(*) FROM bursts").fetchone()[0]
        rows = connection.execute(
            """
            SELECT
                b.id, b.start_at, b.end_at, b.capture_count, b.camera_model,
                b.grouping_method, b.status,
                e.id AS event_id, e.proposed_name AS event_name, e.category,
                MIN(c.stem) AS first_stem, MAX(c.stem) AS last_stem,
                COUNT(DISTINCT sg.id) AS similarity_group_count,
                COALESCE(MAX(sg.capture_count), 0) AS largest_similarity_group
            FROM bursts b
            JOIN events e ON e.id = b.event_id
            JOIN burst_captures bc ON bc.burst_id = b.id
            JOIN captures c ON c.id = bc.capture_id
            LEFT JOIN similarity_groups sg ON sg.burst_id = b.id
            GROUP BY b.id
            ORDER BY b.capture_count DESC, b.start_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return {
            "count": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(row) for row in rows],
        }
    finally:
        connection.close()


def _visual_summary(connection: Any) -> dict[str, int]:
    duplicate = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(file_count), 0), COALESCE(SUM(total_bytes), 0) "
        "FROM duplicate_groups"
    ).fetchone()
    similarity = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(capture_count), 0), "
        "COALESCE(MAX(capture_count), 0) FROM similarity_groups"
    ).fetchone()
    fingerprints = connection.execute(
        "SELECT COUNT(*), SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM visual_fingerprints"
    ).fetchone()
    return {
        "duplicate_group_count": duplicate[0],
        "duplicate_file_count": duplicate[1],
        "duplicate_total_bytes": duplicate[2],
        "similarity_group_count": similarity[0],
        "captures_in_similarity_groups": similarity[1],
        "largest_similarity_group": similarity[2],
        "fingerprint_count": fingerprints[0],
        "fingerprint_error_count": fingerprints[1] or 0,
    }


def _query_duplicates(settings: Settings, limit: int, offset: int) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        total = connection.execute("SELECT COUNT(*) FROM duplicate_groups").fetchone()[0]
        rows = connection.execute(
            """
            SELECT dg.id, dg.file_count, dg.total_bytes, dg.status,
                   MIN(f.file_name) AS file_name
            FROM duplicate_groups dg
            JOIN duplicate_group_files dgf ON dgf.group_id = dg.id
            JOIN files f ON f.id = dgf.file_id
            GROUP BY dg.id
            ORDER BY dg.total_bytes DESC, dg.file_count DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["paths"] = [r[0] for r in connection.execute(
                """SELECT f.path FROM duplicate_group_files dgf
                   JOIN files f ON f.id = dgf.file_id
                   WHERE dgf.group_id = ? ORDER BY f.path""", (row["id"],)
            )]
            items.append(item)
        return {"count": total, "limit": limit, "offset": offset, "items": items}
    finally:
        connection.close()


def _query_analysis_overview(settings: Settings) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        ready, runtime_message = settings.ai_runtime_status()
        return {
            "quality": quality_summary(connection),
            "ai": ai_summary(
                connection, settings.ai_model_path, settings.ai_quantization
            ),
            "runtime": {"ready": ready, "message": runtime_message},
            "detail_data": {
                "metadata_profile_version": METADATA_PROFILE_VERSION,
                "metadata_pending": connection.execute(
                    """SELECT COUNT(*) FROM files f
                       JOIN capture_files cf ON cf.file_id=f.id
                       WHERE f.present=1 AND COALESCE(f.metadata_profile_version, 0) < ?
                         AND (cf.role='jpeg' OR (cf.role='raw' AND NOT EXISTS (
                           SELECT 1 FROM capture_files jpeg_cf
                           JOIN files jpeg_f ON jpeg_f.id=jpeg_cf.file_id
                           WHERE jpeg_cf.capture_id=cf.capture_id
                             AND jpeg_cf.role='jpeg' AND jpeg_f.present=1
                         )))""",
                    (METADATA_PROFILE_VERSION,),
                ).fetchone()[0],
                "histograms_pending": connection.execute(
                    """SELECT COUNT(*) FROM quality_metrics qm
                       JOIN files f ON f.id=qm.source_file_id
                       WHERE qm.error IS NULL AND qm.histogram_json IS NULL
                         AND f.present=1"""
                ).fetchone()[0],
            },
        }
    finally:
        connection.close()


def _query_quality(
    settings: Settings,
    limit: int,
    offset: int,
    review_filter: str = "all",
    search: str | None = None,
) -> dict[str, Any]:
    connection = connect(settings.database_path)
    try:
        conditions = ["1=1"]
        parameters: list[Any] = []
        if review_filter == "problems":
            conditions.append("qm.issue_json <> '[]'")
        elif review_filter == "low_score":
            conditions.append("qm.technical_score < 70")
        elif review_filter == "with_model":
            conditions.append("aa.id IS NOT NULL")
        elif review_filter == "without_model":
            conditions.append("aa.id IS NULL")
        elif review_filter == "unrated":
            conditions.append("cr.user_rating IS NULL")
        if search:
            conditions.append("(c.stem LIKE ? OR e.proposed_name LIKE ?)")
            term = f"%{search.strip()}%"
            parameters.extend((term, term))
        from_sql = """
            FROM quality_metrics qm
            JOIN captures c ON c.id = qm.capture_id
            JOIN event_captures ec ON ec.capture_id = c.id
            JOIN events e ON e.id = ec.event_id
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            LEFT JOIN ai_analyses aa ON aa.id = (
                SELECT aa2.id FROM ai_analyses aa2
                WHERE aa2.capture_id = c.id AND aa2.status = 'complete'
                ORDER BY aa2.id DESC LIMIT 1
            )
        """
        where_sql = " AND ".join(conditions)
        total = connection.execute(
            f"SELECT COUNT(*) {from_sql} WHERE {where_sql}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT qm.capture_id, c.stem, c.captured_at, e.proposed_name AS event_name,
                   e.category, qm.technical_score, qm.exposure_score, qm.sharpness_score,
                   qm.exif_score, qm.highlight_clip_pct, qm.shadow_clip_pct,
                   qm.issue_json, qm.error, cr.auto_rating, cr.auto_pick,
                   cr.similarity_rank, cr.user_rating, cr.user_pick,
                   cr.user_reject, cr.user_note, aa.result_json AS ai_result_json
            {from_sql}
            WHERE {where_sql}
            ORDER BY qm.error IS NOT NULL, qm.technical_score ASC, qm.capture_id
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["issues"] = json.loads(item.pop("issue_json"))
            raw_ai = item.pop("ai_result_json")
            item["ai_result"] = json.loads(raw_ai) if raw_ai else None
            item["thumbnail_url"] = f"/api/thumbnails/{item['capture_id']}?size=320"
            items.append(item)
        return {"count": total, "limit": limit, "offset": offset, "items": items}
    finally:
        connection.close()


def _query_similarity_groups(
    settings: Settings, limit: int, offset: int, review_filter: str = "all",
    album_id: int | None = None,
) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        album_filter = " AND b.event_id=?" if album_id is not None else ""
        count_parameters = (album_id,) if album_id is not None else ()
        pending_condition = """
            NOT EXISTS (
                SELECT 1 FROM similarity_group_captures psgc
                JOIN capture_reviews pcr ON pcr.capture_id = psgc.capture_id
                WHERE psgc.group_id = sg.id AND COALESCE(pcr.user_pick, 0) = 1
            ) AND EXISTS (
                SELECT 1 FROM similarity_group_captures rsgc
                LEFT JOIN capture_reviews rcr ON rcr.capture_id = rsgc.capture_id
                WHERE rsgc.group_id = sg.id AND COALESCE(rcr.user_reject, 0) = 0
            )
        """
        completed_condition = f"NOT ({pending_condition})"
        adjusted_condition = """
            EXISTS (
                SELECT 1 FROM similarity_group_captures asgc
                JOIN similarity_group_overrides aso ON aso.capture_id = asgc.capture_id
                WHERE asgc.group_id = sg.id
            )
        """
        review_condition = {
            "pending": pending_condition,
            "completed": completed_condition,
            "adjusted": adjusted_condition,
        }.get(review_filter, "1=1")
        total = connection.execute(
            f"""SELECT COUNT(*) FROM similarity_groups sg
                JOIN bursts b ON b.id=sg.burst_id WHERE 1=1{album_filter}""",
            count_parameters,
        ).fetchone()[0]
        pending_count = connection.execute(
            f"""
            SELECT COUNT(*) FROM similarity_groups sg
            JOIN bursts b ON b.id=sg.burst_id
            WHERE {pending_condition}
            {album_filter}
            """,
            count_parameters,
        ).fetchone()[0]
        album_rows = connection.execute(
            """
            SELECT e.id, e.proposed_name AS name, e.category,
                   COUNT(*) AS total_count,
                   SUM(CASE WHEN NOT EXISTS (
                       SELECT 1 FROM similarity_group_captures psgc
                       JOIN capture_reviews pcr ON pcr.capture_id=psgc.capture_id
                       WHERE psgc.group_id=sg.id AND COALESCE(pcr.user_pick, 0)=1
                   ) AND EXISTS (
                       SELECT 1 FROM similarity_group_captures rsgc
                       LEFT JOIN capture_reviews rcr ON rcr.capture_id=rsgc.capture_id
                       WHERE rsgc.group_id=sg.id AND COALESCE(rcr.user_reject, 0)=0
                   ) THEN 1 ELSE 0 END) AS pending_count
              FROM similarity_groups sg
              JOIN bursts b ON b.id=sg.burst_id
              JOIN events e ON e.id=b.event_id
             GROUP BY e.id
             ORDER BY pending_count DESC, total_count DESC, e.start_at DESC
            """
        ).fetchall()
        filtered_count = connection.execute(
            f"""SELECT COUNT(*) FROM similarity_groups sg
                JOIN bursts b ON b.id=sg.burst_id
                WHERE {review_condition}{album_filter}""",
            count_parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT sg.id, sg.capture_count, sg.max_adjacent_hamming,
                   b.start_at, b.end_at, e.id AS event_id,
                   e.proposed_name AS event_name, e.category,
                   ROUND(AVG(qm.technical_score), 1) AS average_score,
                   MAX(CASE WHEN cr.auto_pick = 1 THEN c.id END) AS recommended_capture_id,
                   MAX(CASE WHEN cr.auto_pick = 1 THEN c.stem END) AS recommended_stem,
                   MIN(CASE WHEN sgc.sequence_index = 0 THEN c.id END) AS cover_capture_id,
                   SUM(CASE WHEN COALESCE(cr.user_pick, 0)=1 THEN 1 ELSE 0 END) AS pick_count,
                   SUM(CASE WHEN COALESCE(cr.user_reject, 0)=1 THEN 1 ELSE 0 END) AS reject_count
            FROM similarity_groups sg
            JOIN bursts b ON b.id = sg.burst_id
            JOIN events e ON e.id = b.event_id
            JOIN similarity_group_captures sgc ON sgc.group_id = sg.id
            JOIN captures c ON c.id = sgc.capture_id
            LEFT JOIN quality_metrics qm ON qm.capture_id = c.id AND qm.error IS NULL
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            WHERE {review_condition} {album_filter}
            GROUP BY sg.id
            ORDER BY sg.capture_count DESC, b.start_at DESC
            LIMIT ? OFFSET ?
            """,
            (*count_parameters, limit, offset),
        ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["thumbnail_url"] = f"/api/thumbnails/{item['cover_capture_id']}?size=320"
            item["review_status"] = (
                "picked" if item["pick_count"] else
                "skipped" if item["reject_count"] >= item["capture_count"] else "pending"
            )
        return {
            "count": filtered_count, "limit": limit, "offset": offset, "items": items,
            "total_count": total, "pending_count": pending_count,
            "albums": [dict(row) for row in album_rows],
        }
    finally:
        connection.close()


def _query_similarity_group(settings: Settings, group_id: int) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        group = connection.execute(
            """
            SELECT sg.id, sg.capture_count, sg.max_adjacent_hamming,
                   b.start_at, b.end_at, e.proposed_name AS event_name, e.category
            FROM similarity_groups sg
            JOIN bursts b ON b.id = sg.burst_id
            JOIN events e ON e.id = b.event_id
            WHERE sg.id = ?
            """,
            (group_id,),
        ).fetchone()
        if group is None:
            raise ValueError("相似组不存在")
        rows = connection.execute(
            """
            SELECT c.id AS capture_id, c.stem, c.captured_at, sgc.sequence_index,
                   sgc.distance_from_previous, qm.technical_score,
                   qm.exposure_score, qm.sharpness_score, qm.exif_score,
                   qm.issue_json, cr.auto_rating, cr.auto_pick, cr.similarity_rank,
                   cr.user_rating, cr.user_pick, cr.user_reject, cr.user_note,
                   sgo.action AS grouping_override, sgo.manual_batch_key,
                   f.exposure_time, f.f_number, f.iso, f.focal_length_mm,
                   f.focal_length_35mm, f.camera_model, f.lens_model
            FROM similarity_group_captures sgc
            JOIN captures c ON c.id = sgc.capture_id
            JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
              AND cf.file_id = (SELECT MIN(cf2.file_id) FROM capture_files cf2
                                JOIN files f2 ON f2.id = cf2.file_id
                                WHERE cf2.capture_id=c.id AND cf2.role='jpeg' AND f2.present=1)
            JOIN files f ON f.id = cf.file_id
            LEFT JOIN quality_metrics qm ON qm.capture_id = c.id
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            LEFT JOIN similarity_group_overrides sgo ON sgo.capture_id = c.id
            WHERE sgc.group_id = ? ORDER BY sgc.sequence_index
            """,
            (group_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            raw_issues = item.pop("issue_json")
            item["issues"] = json.loads(raw_issues) if raw_issues else []
            item["thumbnail_url"] = f"/api/thumbnails/{item['capture_id']}?size=640"
            items.append(item)
        return {**dict(group), "items": items}
    finally:
        connection.close()


METERING_MODE_LABELS = {
    0: "未知", 1: "平均", 2: "中央重点", 3: "点测光",
    4: "多点", 5: "评价测光", 6: "局部", 255: "其他",
}
WHITE_BALANCE_LABELS = {0: "自动", 1: "手动"}
FILM_MODE_LABELS = {
    0x000: "PROVIA / 标准", 0x100: "彩色高饱和", 0x110: "彩色柔和",
    0x120: "ASTIA / 柔和", 0x200: "Velvia / 鲜艳", 0x300: "PRO Neg. Std",
    0x310: "PRO Neg. Hi", 0x400: "CLASSIC CHROME", 0x500: "ETERNA / 影院",
    0x510: "CLASSIC Neg.", 0x520: "ETERNA 漂白", 0x530: "NOSTALGIC Neg.",
    0x600: "REALA ACE",
}
DYNAMIC_RANGE_LABELS = {0x000: "自动", 0x001: "手动", 0x100: "DR100", 0x200: "DR200", 0x400: "DR400"}


def _exif_label(value: Any, labels: dict[int, str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
        return value
    try:
        code = int(value)
    except (TypeError, ValueError):
        return str(value)
    return labels.get(code, str(value))


def _exif_extras(exif_json: str | None) -> dict[str, Any]:
    if not exif_json:
        return {}
    try:
        values = json.loads(exif_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    flash = values.get("Flash")
    flash_label = None
    if flash is not None:
        try:
            flash_label = "已闪光" if int(flash) & 0x1 else "未闪光"
        except (TypeError, ValueError):
            flash_label = str(flash)
    return {
        "metering_mode": _exif_label(values.get("MeteringMode"), METERING_MODE_LABELS),
        "white_balance": _exif_label(values.get("WhiteBalance"), WHITE_BALANCE_LABELS),
        "flash": flash_label,
        "focus_mode": values.get("FocusMode"),
        "film_simulation": _exif_label(values.get("FilmMode"), FILM_MODE_LABELS),
        "dynamic_range": _exif_label(
            values.get("DynamicRangeSetting", values.get("DynamicRange")),
            DYNAMIC_RANGE_LABELS,
        ),
        "exposure_program": values.get("ExposureProgram"),
        "exposure_mode": values.get("ExposureMode"),
        "shutter_type": values.get("ShutterType"),
        "orientation": values.get("Orientation"),
        "captured_at_precise": values.get("SubSecDateTimeOriginal"),
        "timezone_offset": values.get("OffsetTimeOriginal"),
        "color_space": values.get("ColorSpace"),
        "bits_per_sample": values.get("BitsPerSample"),
        "image_quality": values.get("Quality"),
        "image_stabilization": values.get("ImageStabilization"),
        "drive_mode": values.get("DriveMode"),
        "drive_speed": values.get("DriveSpeed"),
        "sequence_number": values.get("SequenceNumber"),
        "auto_bracketing": values.get("AutoBracketing"),
        "af_mode": values.get("AFMode"),
        "af_area_mode": values.get("AFAreaMode"),
        "focus_pixel": values.get("FocusPixel"),
        "blur_warning": values.get("BlurWarning"),
        "focus_warning": values.get("FocusWarning"),
        "exposure_warning": values.get("ExposureWarning"),
        "faces_detected": values.get("FacesDetected"),
        "roll_angle": values.get("RollAngle"),
        "camera_elevation_angle": values.get("CameraElevationAngle"),
        "white_balance_fine_tune": values.get("WhiteBalanceFineTune"),
        "highlight_tone": values.get("HighlightTone"),
        "shadow_tone": values.get("ShadowTone"),
        "saturation": values.get("Saturation"),
        "camera_sharpness": values.get("Sharpness"),
        "noise_reduction": values.get("NoiseReduction"),
        "clarity": values.get("Clarity"),
        "color_chrome_effect": values.get("ColorChromeEffect"),
        "color_chrome_fx_blue": values.get("ColorChromeFXBlue"),
        "grain_effect_roughness": values.get("GrainEffectRoughness"),
        "grain_effect_size": values.get("GrainEffectSize"),
        "lens_modulation_optimizer": values.get("LensModulationOptimizer"),
        "auto_dynamic_range": values.get("AutoDynamicRange"),
        "raw_compression": values.get("RAFCompression"),
    }


def _query_capture_detail(settings: Settings, capture_id: int) -> dict[str, Any]:
    connection = connect_readonly(settings.database_path)
    try:
        row = connection.execute(
            """
            SELECT c.id, c.stem, c.parent_relative, c.captured_at, c.pairing_status,
                   e.id AS event_id, e.proposed_name AS event_name, e.category,
                   qm.luminance_mean, qm.shadow_clip_pct, qm.highlight_clip_pct,
                   qm.edge_strength, qm.exposure_score, qm.sharpness_score,
                   qm.exif_score, qm.technical_score, qm.issue_json,
                   qm.histogram_json, qm.error,
                   cr.auto_rating, cr.auto_pick, cr.similarity_rank,
                   cr.user_rating, cr.user_pick, cr.user_reject, cr.user_note
            FROM captures c
            LEFT JOIN event_captures ec ON ec.capture_id = c.id
            LEFT JOIN events e ON e.id = ec.event_id
            LEFT JOIN quality_metrics qm ON qm.capture_id = c.id
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            WHERE c.id = ?
            """,
            (capture_id,),
        ).fetchone()
        if row is None:
            raise ValueError("拍摄单元不存在")
        item = dict(row)
        raw_issues = item.pop("issue_json")
        item["issues"] = json.loads(raw_issues) if raw_issues else []
        raw_histogram = item.pop("histogram_json")
        item["histogram"] = json.loads(raw_histogram) if raw_histogram else None
        item["files"] = [dict(file) for file in connection.execute(
            """
            SELECT f.id, f.file_name, f.path, f.extension, f.media_kind, f.size_bytes,
                   cf.role, f.camera_make, f.camera_model, f.lens_model,
                   f.exposure_time, f.f_number, f.iso, f.focal_length_mm,
                   f.focal_length_35mm, f.exposure_compensation, f.width, f.height,
                   f.gps_latitude, f.gps_longitude, f.exif_json
            FROM capture_files cf JOIN files f ON f.id = cf.file_id
            WHERE cf.capture_id = ? AND f.present = 1 ORDER BY cf.role, f.id
            """,
            (capture_id,),
        )]
        for file in item["files"]:
            file.update(_exif_extras(file.pop("exif_json")))
        analyses = connection.execute(
            """
            SELECT id, model_id, prompt_version, result_json, finished_at,
                   user_verdict, user_note, reviewed_at
            FROM ai_analyses WHERE capture_id=? AND status='complete'
            ORDER BY id DESC
            """,
            (capture_id,),
        ).fetchall()
        item["ai_analyses"] = [
            {
                **dict(analysis),
                "result": json.loads(analysis["result_json"])
                if analysis["result_json"] else {},
            }
            for analysis in analyses
        ]
        for analysis in item["ai_analyses"]:
            analysis.pop("result_json", None)
        item["thumbnail_url"] = f"/api/thumbnails/{capture_id}?size=1280"
    finally:
        connection.close()
    if item["histogram"] is None and item["error"] is None:
        item["histogram"] = _ensure_capture_histogram(settings, capture_id)
    return item


def _can_open_folder() -> bool:
    return (
        os.name == "nt"
        or platform.system() == "Darwin"
        or shutil.which("xdg-open") is not None
    )


def _open_folder(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(path)])
    elif shutil.which("xdg-open") is not None:
        subprocess.Popen(["xdg-open", str(path)])
    else:
        raise OSError("No supported desktop folder opener is available")


def _runtime_capabilities(settings: Settings) -> dict[str, Any]:
    exiftool = settings.find_exiftool()
    ai_ready, ai_message = settings.ai_runtime_status()
    return {
        "platform": platform.system().lower(),
        "library_root": str(settings.originals),
        "workspace_root": str(settings.workspace),
        "metadata": {
            "level": "full" if exiftool else "basic",
            "exiftool": bool(exiftool),
            "message": (
                "ExifTool 已就绪，可读取 RAW 和厂商扩展信息"
                if exiftool else "使用内置读取器提供常用 JPEG EXIF；完整元数据为可选能力"
            ),
        },
        "ai": {"ready": ai_ready, "message": ai_message},
        "features": {
            "open_folder": _can_open_folder(),
            "raw_pairing": bool(settings.raw_extensions),
            "lightroom_manifest": True,
            "phone_share_export": True,
        },
        "safety": {
            "offline_only": settings.offline_only,
            "library_read_only": settings.read_only,
            "allow_move": settings.allow_move,
            "allow_delete": settings.allow_delete,
            "allow_original_metadata_write": settings.allow_original_metadata_write,
        },
    }


def _ensure_capture_histogram(
    settings: Settings, capture_id: int
) -> list[int] | None:
    """Lazily fill a missing histogram without changing existing scores."""
    connection = connect_readonly(settings.database_path)
    try:
        row = connection.execute(
            """
            SELECT qm.histogram_json, f.path
            FROM quality_metrics qm
            JOIN files f ON f.id = qm.source_file_id
            WHERE qm.capture_id = ? AND qm.error IS NULL AND f.present = 1
            """,
            (capture_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None or row["histogram_json"]:
        return json.loads(row["histogram_json"]) if row is not None else None
    try:
        histogram = measure_luminance_histogram(Path(row["path"]))
    except (OSError, ValueError):
        return None
    if not histogram:
        return None
    connection = connect(settings.database_path)
    try:
        connection.execute(
            """
            UPDATE quality_metrics SET histogram_json = ?
            WHERE capture_id = ? AND histogram_json IS NULL
            """,
            (json.dumps(list(histogram)), capture_id),
        )
        connection.commit()
    finally:
        connection.close()
    return list(histogram)


def create_app(config_path: Path, static_directory: Path | None = None) -> FastAPI:
    config_path = config_path.resolve()
    settings = Settings.load(config_path)
    bootstrap = connect(settings.database_path)
    try:
        active_root = active_library_root(bootstrap, settings.originals)
        discover_pre_ai_database_backups(settings, bootstrap)
        recovery = recover_interrupted_ai_runs(bootstrap)
    finally:
        bootstrap.close()
    if active_root != settings.originals:
        settings = replace(settings, originals=active_root)
    errors = settings.validate()
    if errors:
        raise ValueError("; ".join(errors))
    manager = ScanTaskManager(settings)
    if recovery["still_running"]:
        manager.attach_ai_run(recovery["still_running"][0])
    thumbnail_cache = ThumbnailCache(settings)
    app = FastAPI(title="TangerinePhotoAssistant", docs_url=None, redoc_url=None)
    config_state = {"restart_required": False, "backup_path": None}

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "local-only",
            "offline_only": settings.offline_only,
            "schema_version": SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
        }

    @app.get("/api/system/capabilities")
    def system_capabilities() -> dict[str, Any]:
        return _runtime_capabilities(settings)

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return {
            "configured": editable_config(config_path),
            "effective": _runtime_capabilities(settings),
            "restart_required": config_state["restart_required"],
            "backup_path": config_state["backup_path"],
            "fixed_safety": {
                "offline_only": True,
                "library_read_only": True,
                "allow_move": False,
                "allow_delete": False,
                "allow_original_metadata_write": False,
            },
        }

    @app.put("/api/settings")
    def update_settings(request: AppSettingsRequest) -> dict[str, Any]:
        current = manager.snapshot()
        if current["status"] in {"running", "paused"}:
            raise HTTPException(
                status_code=409,
                detail="后台任务运行或暂停期间不能修改配置，请先完成或安全取消任务",
            )
        try:
            backup = save_editable_config(config_path, request.model_dump())
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        config_state["restart_required"] = True
        config_state["backup_path"] = str(backup)
        return {
            "configured": editable_config(config_path),
            "effective": _runtime_capabilities(settings),
            "restart_required": True,
            "backup_path": str(backup),
            "message": "配置已安全保存并备份；照片和数据库未移动，重启应用后生效",
        }

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        return _query_overview(settings)

    @app.get("/api/inbox")
    def inbox(limit: int = Query(default=24, ge=1, le=200)) -> dict[str, Any]:
        return _query_inbox(settings, limit)

    @app.get("/api/system/photo-inbox")
    def photo_inbox() -> dict[str, Any]:
        path = settings.originals / "待整理"
        return {
            "path": str(path),
            "exists": path.is_dir(),
            "can_open": _can_open_folder() and path.is_dir(),
        }

    @app.post("/api/system/photo-inbox/open")
    def open_photo_inbox() -> dict[str, Any]:
        path = settings.originals / "待整理"
        if not path.is_dir():
            raise HTTPException(status_code=404, detail=f"待整理目录不存在：{path}")
        try:
            _open_folder(path)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"无法打开系统文件管理器：{exc}"
            ) from exc
        return {"opened": True, "path": str(path)}

    @app.post("/api/system/folders/{folder_kind}/open")
    def open_configured_folder(folder_kind: str) -> dict[str, Any]:
        paths = {
            "library": settings.originals,
            "workspace": settings.workspace,
            "cache": settings.cache_root,
            "reports": settings.reports_path,
        }
        path = paths.get(folder_kind)
        if path is None:
            raise HTTPException(status_code=404, detail="不支持的目录类型")
        if not path.is_dir():
            raise HTTPException(status_code=404, detail=f"目录不存在：{path}")
        try:
            _open_folder(path)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"无法打开系统文件管理器：{exc}"
            ) from exc
        return {"opened": True, "path": str(path)}

    @app.get("/api/library/captures")
    def library_captures(
        limit: int = Query(default=60, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        album_id: int | None = Query(default=None, ge=1),
        unassigned: bool = False,
        category: str | None = Query(default=None, max_length=40),
        camera_model: str | None = Query(default=None, max_length=200),
        lens_model: str | None = Query(default=None, max_length=240),
        rating: int | None = Query(default=None, ge=1, le=5),
        selection: Literal["picked", "rejected", "unreviewed"] | None = None,
        quality: Literal["problems", "low", "high", "unanalyzed"] | None = None,
        date_from: str | None = Query(default=None, max_length=10),
        date_to: str | None = Query(default=None, max_length=10),
        search: str | None = Query(default=None, max_length=120),
        sort: Literal["newest", "oldest", "name", "rating"] = "newest",
        collapse_groups: bool = False,
    ) -> dict[str, Any]:
        return _query_library_captures(
            settings, limit, offset, album_id=album_id, category=category,
            camera_model=camera_model, lens_model=lens_model, rating=rating,
            selection=selection, quality=quality, date_from=date_from, date_to=date_to,
            search=search, sort=sort, collapse_groups=collapse_groups,
            unassigned_only=unassigned,
        )

    @app.get("/api/library/filters")
    def library_filters() -> dict[str, Any]:
        return _query_library_filters(settings)

    @app.get("/api/events")
    def events(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _query_events(settings, limit, offset)

    @app.get("/api/albums")
    def albums(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _query_events(settings, limit, offset)

    @app.get("/api/bursts")
    def bursts(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _query_bursts(settings, limit, offset)

    @app.get("/api/duplicates")
    def duplicates(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return _query_duplicates(settings, limit, offset)

    @app.get("/api/analysis/overview")
    def analysis_overview() -> dict[str, Any]:
        return _query_analysis_overview(settings)

    @app.get("/api/ai/preflight")
    def model_preflight() -> dict[str, Any]:
        return ai_preflight(settings)

    @app.get("/api/system/gpu")
    def system_gpu_status() -> dict[str, Any]:
        return gpu_status()

    @app.get("/api/ai/runs")
    def model_runs(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            return ai_run_history(connection, limit, offset)
        finally:
            connection.close()

    @app.get("/api/ai/results")
    def model_results(
        limit: int = Query(default=48, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        prompt_version: str | None = Query(default=None, max_length=100),
        verdict: Literal["accurate", "partial", "inaccurate", "unreviewed"] | None = None,
    ) -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            return ai_results_page(
                connection, limit, offset, prompt_version, verdict
            )
        finally:
            connection.close()

    @app.get("/api/ai/runs/{run_id}/failures")
    def model_run_failures(run_id: int) -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            return {"run_id": run_id, "items": ai_run_failures(connection, run_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.get("/api/ai/runs/{run_id}/report.csv")
    def ai_run_csv_report(run_id: int) -> FileResponse:
        connection = connect_readonly(settings.database_path)
        try:
            report = write_ai_run_report(connection, settings.reports_path, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            connection.close()
        return FileResponse(
            settings.reports_path / report["csv_name"],
            filename=report["csv_name"], media_type="text/csv",
        )

    @app.get("/api/ai/runs/{run_id}/report.json")
    def ai_run_json_report(run_id: int) -> FileResponse:
        connection = connect_readonly(settings.database_path)
        try:
            report = write_ai_run_report(connection, settings.reports_path, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            connection.close()
        return FileResponse(
            settings.reports_path / report["json_name"],
            filename=report["json_name"], media_type="application/json",
        )

    @app.get("/api/quality")
    def quality_results(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        review_filter: Literal[
            "all", "problems", "low_score", "with_model", "without_model", "unrated"
        ] = "all",
        search: str | None = Query(default=None, max_length=120),
    ) -> dict[str, Any]:
        return _query_quality(settings, limit, offset, review_filter, search)

    @app.get("/api/similarity-groups")
    def similarity_groups(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        review_filter: Literal["all", "pending", "completed", "adjusted"] = "all",
        album_id: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        return _query_similarity_groups(
            settings, limit, offset, review_filter=review_filter, album_id=album_id
        )

    @app.get("/api/similarity-groups/{group_id}")
    def similarity_group(group_id: int) -> dict[str, Any]:
        try:
            return _query_similarity_group(settings, group_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/captures/{capture_id}/similarity-override")
    def update_similarity_override(
        capture_id: int, request: SimilarityOverrideRequest
    ) -> dict[str, Any]:
        if manager.snapshot()["status"] == "running":
            raise HTTPException(status_code=409, detail="后台任务运行时不能调整相似分组")
        connection = connect(settings.database_path)
        try:
            if connection.execute(
                "SELECT 1 FROM captures WHERE id=?", (capture_id,)
            ).fetchone() is None:
                raise HTTPException(status_code=404, detail="照片不存在")
            if request.action == "auto":
                regrouped = restore_similarity_grouping(connection, capture_id)
                return {"capture_id": capture_id, "action": request.action, **regrouped}
            else:
                if connection.execute(
                    "SELECT 1 FROM burst_captures WHERE capture_id=? LIMIT 1",
                    (capture_id,),
                ).fetchone() is None:
                    raise HTTPException(status_code=422, detail="这张照片不属于连拍候选")
                now = utc_now()
                connection.execute(
                    """INSERT INTO similarity_group_overrides(
                           capture_id, action, created_at, updated_at
                       ) VALUES (?, ?, ?, ?)
                       ON CONFLICT(capture_id) DO UPDATE SET
                           action=excluded.action, updated_at=excluded.updated_at""",
                    (capture_id, request.action, now, now),
                )
            connection.commit()
            regrouped = rebuild_similarity_groups(connection)
            recommendations = rebuild_group_recommendations(connection)
            return {
                "capture_id": capture_id,
                "action": request.action,
                **regrouped,
                **recommendations,
            }
        finally:
            connection.close()

    @app.put("/api/similarity-groups/manual")
    def update_similarity_group_manual(request: SimilarityGroupEditRequest) -> dict[str, Any]:
        if manager.snapshot()["status"] == "running":
            raise HTTPException(status_code=409, detail="后台任务运行时不能调整相似分组")
        connection = connect(settings.database_path)
        try:
            try:
                return save_manual_similarity_grouping(
                    connection,
                    request.source_group_id,
                    request.groups,
                    request.excluded_ids,
                )
            except SimilarityGroupingError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.get("/api/similarity-group-revisions")
    def similarity_group_revisions(
        capture_id: int | None = Query(default=None, ge=1),
        album_id: int | None = Query(default=None, ge=1),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            return {
                "items": list_similarity_group_revisions(
                    connection, capture_id, limit, album_id=album_id
                ),
            }
        finally:
            connection.close()

    @app.post("/api/similarity-group-revisions/{revision_id}/restore")
    def restore_similarity_revision(
        revision_id: int, request: SimilarityRevisionRestoreRequest
    ) -> dict[str, Any]:
        if manager.snapshot()["status"] == "running":
            raise HTTPException(status_code=409, detail="后台任务运行时不能恢复分组历史")
        connection = connect(settings.database_path)
        try:
            try:
                return restore_similarity_group_revision(
                    connection, revision_id, use_before=request.use_before
                )
            except SimilarityGroupingError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.get("/api/captures/{capture_id}")
    def capture_detail(capture_id: int) -> dict[str, Any]:
        try:
            return _query_capture_detail(settings, capture_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/thumbnails/{capture_id}")
    def thumbnail(
        capture_id: int,
        size: int = Query(default=640),
    ) -> FileResponse:
        try:
            path = thumbnail_cache.get(capture_id, size)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            path, media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @app.get("/api/cache/thumbnails")
    def thumbnail_cache_summary() -> dict[str, int]:
        return thumbnail_cache.summary()

    @app.get("/api/statistics")
    def statistics() -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            return build_statistics(connection)
        finally:
            connection.close()

    @app.get("/api/equipment")
    def equipment() -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            project_root = Path(__file__).resolve().parents[2]
            return build_equipment_catalog(
                connection,
                project_root / "equipment" / "profile.toml",
                project_root / "equipment" / "catalogs" / "fujifilm-x.toml",
                settings.workspace / "Equipment" / "inventory.json",
            )
        except (FileNotFoundError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.put("/api/equipment/ownership")
    def update_equipment_ownership(request: EquipmentOwnershipRequest) -> dict[str, Any]:
        try:
            save_equipment_ownership(
                settings.workspace / "Equipment" / "inventory.json",
                request.kind,
                request.key,
                request.owned,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return equipment()

    @app.post("/api/equipment/items", status_code=201)
    def create_equipment_item(request: EquipmentItemRequest) -> dict[str, Any]:
        try:
            current = equipment()
            save_equipment_item(
                settings.workspace / "Equipment" / "inventory.json",
                request.kind,
                request.model_dump(exclude={"kind", "key"}),
                existing_items=current[{"camera": "cameras", "lens": "lenses", "accessory": "accessories"}[request.kind]],
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return equipment()

    @app.put("/api/equipment/items")
    def update_equipment_item(request: EquipmentItemRequest) -> dict[str, Any]:
        if not request.key:
            raise HTTPException(status_code=422, detail="编辑设备时缺少设备标识")
        try:
            current = equipment()
            save_equipment_item(
                settings.workspace / "Equipment" / "inventory.json",
                request.kind,
                request.model_dump(exclude={"kind", "key"}),
                request.key,
                current[{"camera": "cameras", "lens": "lenses", "accessory": "accessories"}[request.kind]],
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return equipment()

    @app.put("/api/equipment/visibility")
    def update_equipment_visibility(request: EquipmentVisibilityRequest) -> dict[str, Any]:
        try:
            set_equipment_visibility(
                settings.workspace / "Equipment" / "inventory.json",
                request.kind,
                request.key,
                request.visible,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return equipment()

    @app.delete("/api/equipment/items")
    def remove_equipment_item(request: EquipmentDeleteRequest) -> dict[str, Any]:
        try:
            delete_equipment_item(
                settings.workspace / "Equipment" / "inventory.json",
                request.kind,
                request.key,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return equipment()

    @app.get("/api/lightroom/status")
    def get_lightroom_status() -> dict[str, int]:
        connection = connect_readonly(settings.database_path)
        try:
            return lightroom_status(connection)
        finally:
            connection.close()

    @app.post("/api/lightroom/manifest", status_code=201)
    def generate_lightroom_manifest(request: LightroomManifestRequest) -> dict[str, Any]:
        if request.scope == "album" and request.album_id is None:
            raise HTTPException(status_code=422, detail="按相册生成时必须选择相册")
        connection = connect_readonly(settings.database_path)
        try:
            result = write_lightroom_manifest(
                connection, settings.reports_path, request.scope, request.album_id
            )
        finally:
            connection.close()
        return {
            **result,
            "csv_url": f"/api/reports/{result['csv_name']}",
            "json_url": f"/api/reports/{result['json_name']}",
        }

    @app.get("/api/migration/status")
    def get_migration_status() -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            return migration_status(connection)
        finally:
            connection.close()

    @app.post("/api/migration/plans", status_code=201)
    def generate_migration_plan() -> dict[str, Any]:
        if manager.snapshot()["status"] == "running":
            raise HTTPException(status_code=409, detail="后台任务运行时不能生成迁移计划")
        connection = connect(settings.database_path)
        try:
            try:
                return create_migration_plan(
                    connection,
                    settings.originals,
                    settings.workspace / "Photos",
                    settings.reports_path,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.get("/api/migration/plans/{plan_id}/preflight")
    def preflight_migration(plan_id: int) -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            return migration_preflight(connection, plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.post("/api/migration/runs", status_code=202)
    def start_migration(request: MigrationStartRequest) -> dict[str, Any]:
        try:
            return manager.start_migration(
                request.plan_id, request.confirmation,
                request.batch_max_files, request.batch_max_gb,
                request.batch_max_minutes,
            )
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/migration/runs/current/pause", status_code=202)
    def pause_migration() -> dict[str, Any]:
        try:
            return manager.pause()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/migration/runs/{run_id}/resume", status_code=202)
    def resume_migration(run_id: int) -> dict[str, Any]:
        try:
            return manager.resume_migration(run_id)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/migration/switch", status_code=200)
    def switch_migration(request: MigrationSwitchRequest) -> dict[str, Any]:
        nonlocal settings, thumbnail_cache
        if manager.snapshot()["status"] in {"running", "paused"}:
            raise HTTPException(status_code=409, detail="后台任务运行时不能切换活动图库")
        connection = connect(settings.database_path)
        try:
            try:
                result = switch_active_library(
                    connection, request.run_id, request.confirmation
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()
        settings = replace(settings, originals=Path(result["active_root"]))
        manager.settings = settings
        thumbnail_cache = ThumbnailCache(settings)
        return result

    @app.post("/api/exports/phone-share", status_code=201)
    def create_phone_share_export(request: PhoneShareExportRequest) -> dict[str, Any]:
        if request.max_edge not in ALLOWED_SHARE_EDGES:
            raise HTTPException(status_code=422, detail="不支持的导出尺寸")
        connection = connect_readonly(settings.database_path)
        try:
            try:
                result = write_phone_share_export(
                    connection,
                    settings.originals,
                    settings.reports_path,
                    request.capture_ids,
                    request.max_edge,
                    request.quality,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()
        return {**result, "download_url": f"/api/reports/{result['filename']}"}

    @app.get("/api/reports/{filename}")
    def download_report(filename: str) -> FileResponse:
        allowed = {
            "lightroom-import-plan-latest.csv",
            "lightroom-import-plan-latest.json",
        }
        is_migration_report = bool(
            re.fullmatch(r"migration-(?:plan|failures)-\d+\.(csv|json)", filename)
        )
        is_phone_share = bool(
            re.fullmatch(r"phone-share-\d{8}-\d{6}-[a-f0-9]{8}\.zip", filename)
        )
        if filename not in allowed and not is_migration_report and not is_phone_share:
            raise HTTPException(status_code=404, detail="报告不存在")
        path = (settings.reports_path / filename).resolve()
        if not path.is_file() or not path.is_relative_to(settings.reports_path.resolve()):
            raise HTTPException(status_code=404, detail="报告不存在")
        return FileResponse(path, filename=filename)

    @app.get("/api/archive/status")
    def archive_status() -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            return recorded_archive_status(connection)
        finally:
            connection.close()

    @app.post("/api/archive/baselines", status_code=201)
    def create_baseline(request: ArchiveBaselineRequest) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            name = request.name or f"original-archive-{utc_now()}"
            try:
                return create_archive_baseline(connection, name, request.note)
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="同名档案基线已经存在") from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.get("/api/active-library/baseline/status")
    def active_library_baseline_status() -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            return recorded_active_library_status(connection)
        finally:
            connection.close()

    @app.post("/api/integrity/check/{scope}")
    def check_library_integrity(scope: Literal["archive", "active"]) -> dict[str, Any]:
        if manager.snapshot()["status"] == "running":
            raise HTTPException(status_code=409, detail="后台任务运行时不能执行完整性检查")
        connection = connect(settings.database_path)
        try:
            try:
                return run_integrity_check(connection, scope)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.post("/api/active-library/baselines", status_code=201)
    def create_active_baseline(request: ArchiveBaselineRequest) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            name = request.name or f"active-library-{utc_now()}"
            try:
                return create_archive_baseline(
                    connection,
                    name,
                    request.note or "活动图库逻辑保护基线",
                    scope="active",
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="同名活动基线已经存在") from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.post("/api/structure/rebuild")
    def rebuild_event_structure() -> dict[str, int]:
        if manager.snapshot()["status"] == "running":
            raise HTTPException(status_code=409, detail="扫描运行时不能重新整理相册建议")
        connection = connect(settings.database_path)
        try:
            return rebuild_structure(connection, settings.burst_time_gap_seconds)
        finally:
            connection.close()

    def save_album(album_id: int, request: EventUpdateRequest) -> dict[str, Any]:
        name = request.proposed_name.strip()
        category = request.category.strip()
        if not name or len(name) > 180:
            raise HTTPException(status_code=422, detail="相册名称必须为1到180个字符")
        if request.status not in {"proposed", "confirmed"}:
            raise HTTPException(status_code=422, detail="相册状态不受支持")
        connection = connect(settings.database_path)
        try:
            if connection.execute(
                "SELECT 1 FROM album_types WHERE name=?", (category,)
            ).fetchone() is None:
                raise HTTPException(status_code=422, detail="相册类型不存在")
            cursor = connection.execute(
                """
                UPDATE events SET proposed_name=?, category=?, status=?, updated_at=?
                WHERE id=?
                """,
                (name, category, request.status, utc_now(), album_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="相册不存在")
            connection.commit()
            return {"id": album_id, "status": "saved"}
        finally:
            connection.close()

    @app.put("/api/events/{event_id}")
    def update_event(event_id: int, request: EventUpdateRequest) -> dict[str, Any]:
        return save_album(event_id, request)

    @app.put("/api/albums/{album_id}")
    def update_album(album_id: int, request: EventUpdateRequest) -> dict[str, Any]:
        return save_album(album_id, request)

    @app.post("/api/albums", status_code=201)
    def create_album(request: AlbumCreateRequest) -> dict[str, Any]:
        name = request.name.strip()
        category = request.category.strip()
        if not name:
            raise HTTPException(status_code=422, detail="相册名称不能为空")
        connection = connect(settings.database_path)
        try:
            if connection.execute(
                "SELECT 1 FROM album_types WHERE name=?", (category,)
            ).fetchone() is None:
                raise HTTPException(status_code=422, detail="相册类型不存在")
            now = utc_now()
            cursor = connection.execute(
                """INSERT INTO events(
                       event_key, proposed_name, category, date_label, start_at,
                       end_at, capture_count, status, confidence, reason_json,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, NULL, NULL, NULL, 0, 'confirmed', 1.0, ?, ?, ?)""",
                (
                    f"manual-album:{uuid4().hex}", name, category,
                    json.dumps({"method": "manual", "legacy_buckets": []}, ensure_ascii=False),
                    now, now,
                ),
            )
            connection.commit()
            return {"id": cursor.lastrowid, "name": name, "category": category}
        finally:
            connection.close()

    @app.post("/api/album-types", status_code=201)
    def create_album_type(request: AlbumTypeCreateRequest) -> dict[str, Any]:
        name = request.name.strip()
        connection = connect(settings.database_path)
        try:
            try:
                connection.execute(
                    """INSERT INTO album_types(name, sort_order, built_in, created_at)
                       VALUES (?, 100, 0, ?)""",
                    (name, utc_now()),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="同名相册类型已经存在") from exc
            return {"name": name, "built_in": 0}
        finally:
            connection.close()

    @app.put("/api/album-types/{name}")
    def update_album_type(name: str, request: AlbumTypeUpdateRequest) -> dict[str, Any]:
        next_name = request.name.strip()
        if not next_name:
            raise HTTPException(status_code=422, detail="相册类型名称不能为空")
        connection = connect(settings.database_path)
        try:
            row = connection.execute(
                "SELECT built_in FROM album_types WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="相册类型不存在")
            if row["built_in"]:
                raise HTTPException(status_code=409, detail="内置相册类型不能改名")
            if connection.execute(
                "SELECT 1 FROM album_types WHERE name=?", (next_name,)
            ).fetchone():
                raise HTTPException(status_code=409, detail="同名相册类型已经存在")
            connection.execute(
                "UPDATE events SET category=?, updated_at=? WHERE category=?",
                (next_name, utc_now(), name),
            )
            connection.execute(
                "UPDATE album_types SET name=? WHERE name=?", (next_name, name)
            )
            connection.commit()
            return {"name": next_name, "previous_name": name, "built_in": 0}
        finally:
            connection.close()

    @app.delete("/api/album-types/{name}")
    def delete_album_type(name: str) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            row = connection.execute(
                "SELECT built_in FROM album_types WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="相册类型不存在")
            if row["built_in"]:
                raise HTTPException(status_code=409, detail="内置相册类型不能删除")
            if connection.execute(
                "SELECT 1 FROM events WHERE category=? LIMIT 1", (name,)
            ).fetchone():
                raise HTTPException(status_code=409, detail="该类型仍被相册使用")
            connection.execute("DELETE FROM album_types WHERE name=?", (name,))
            connection.commit()
            return {"name": name, "status": "deleted"}
        finally:
            connection.close()

    @app.put("/api/albums/{album_id}/captures")
    def assign_album_captures(
        album_id: int, request: AlbumAssignmentRequest
    ) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            try:
                assigned = _assign_captures_to_album(
                    connection, album_id, request.capture_ids
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {"album_id": album_id, "assigned_count": assigned}
        finally:
            connection.close()

    @app.get("/api/tasks/current")
    def current_task() -> dict[str, Any]:
        return manager.snapshot()

    @app.post("/api/tasks/current/cancel", status_code=202)
    def cancel_current_task() -> dict[str, Any]:
        try:
            return manager.cancel()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/scan", status_code=202)
    def start_scan(request: ScanStartRequest) -> dict[str, Any]:
        try:
            return manager.start(request.album_id)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/visual/analyze", status_code=202)
    def start_visual_analysis() -> dict[str, Any]:
        try:
            return manager.start_visual()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/quality/analyze", status_code=202)
    def start_quality_analysis() -> dict[str, Any]:
        try:
            return manager.start_quality()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/detail-data/backfill", status_code=202)
    def start_detail_data_backfill() -> dict[str, Any]:
        try:
            return manager.start_detail_backfill()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/detail-data/backfill/resume", status_code=202)
    def resume_detail_data_backfill() -> dict[str, Any]:
        try:
            return manager.resume_detail_backfill()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/detail-data/backfill/pause", status_code=202)
    def pause_detail_data_backfill() -> dict[str, Any]:
        try:
            return manager.pause()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/ai/analyze", status_code=202)
    def start_ai_analysis(request: AiStartRequest) -> dict[str, Any]:
        try:
            return manager.start_ai(request.mode, request.limit, config_path)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/ai/runs/current/pause", status_code=202)
    def pause_ai_analysis() -> dict[str, Any]:
        try:
            return manager.pause()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/ai/runs/{run_id}/resume", status_code=202)
    def resume_ai_analysis(run_id: int) -> dict[str, Any]:
        try:
            return manager.resume_ai(run_id, config_path)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/ai/runs/{run_id}/retry-failures", status_code=202)
    def retry_ai_failures(run_id: int) -> dict[str, Any]:
        try:
            return manager.retry_ai_failures(run_id, config_path)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/api/reviews/{capture_id}")
    def update_review(capture_id: int, request: ReviewUpdateRequest) -> dict[str, Any]:
        if request.user_rating is not None and not 1 <= request.user_rating <= 5:
            raise HTTPException(status_code=422, detail="人工星级必须在 1 到 5 之间")
        if request.user_pick and request.user_reject:
            raise HTTPException(status_code=422, detail="同一照片不能同时标为保留和待淘汰")
        connection = connect(settings.database_path)
        try:
            exists = connection.execute(
                "SELECT 1 FROM captures WHERE id=?", (capture_id,)
            ).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="拍摄单元不存在")
            connection.execute(
                """
                INSERT INTO capture_reviews(
                    capture_id, user_rating, user_pick, user_reject, user_note, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(capture_id) DO UPDATE SET
                    user_rating=excluded.user_rating,
                    user_pick=excluded.user_pick,
                    user_reject=excluded.user_reject,
                    user_note=excluded.user_note,
                    updated_at=excluded.updated_at
                """,
                (
                    capture_id, request.user_rating,
                    int(request.user_pick) if request.user_pick is not None else None,
                    int(request.user_reject), request.user_note,
                    utc_now(),
                ),
            )
            connection.commit()
            return {"capture_id": capture_id, "status": "saved"}
        finally:
            connection.close()

    @app.put("/api/ai/analyses/{analysis_id}/review")
    def review_ai_analysis(
        analysis_id: int, request: AiReviewUpdateRequest
    ) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            return update_ai_review(
                connection, analysis_id, request.user_verdict, request.user_note
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            connection.close()

    if static_directory is not None and static_directory.is_dir():
        static_root = static_directory.resolve()
        assets = static_directory / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str) -> FileResponse:
            requested = (static_root / path).resolve()
            if path and requested.is_file() and requested.is_relative_to(static_root):
                return FileResponse(requested)
            return FileResponse(static_root / "index.html")

    return app
