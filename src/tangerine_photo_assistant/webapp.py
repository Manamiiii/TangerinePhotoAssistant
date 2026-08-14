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
from fastapi.responses import FileResponse, Response
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
    create_ai_failure_retry_run,
    create_ai_run,
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
from .albums import (
    AlbumConflictError,
    AlbumError,
    AlbumNotFoundError,
    assign_captures_to_album,
    create_album as create_album_record,
    create_album_type as create_album_type_record,
    delete_album_type as delete_album_type_record,
    rename_album_type,
    update_album as update_album_record,
)
from .database import SCHEMA_VERSION, connect, connect_readonly
from .equipment import (
    build_equipment_catalog,
    delete_equipment_item,
    equipment_album_reference_count,
    save_equipment_item,
    save_equipment_ownership,
    set_equipment_visibility,
)
from .editing import (
    EditRecipeError,
    render_edit_preview,
    restore_edit_recipe,
    save_edit_recipe,
)
from .exports import ALLOWED_SHARE_EDGES, write_phone_share_export
from .grouping import (
    SimilarityCaptureNotFoundError,
    SimilarityGroupingError,
    list_similarity_group_revisions,
    restore_similarity_grouping,
    restore_similarity_group_revision,
    save_manual_similarity_grouping,
    set_similarity_override,
)
from .inventory import enrich_metadata, refresh_metadata_profile, scan_library, utc_now
from .lightroom import lightroom_preflight, lightroom_status, write_lightroom_manifest
from .metadata import ExifToolMetadataReader, PillowMetadataReader
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
from .reviews import CaptureReviewError, CaptureReviewNotFoundError, save_capture_review
from .tags import (
    analysis_subject_tag_status,
    clear_analysis_subject_tags,
    CaptureTagError,
    CaptureTagNotFoundError,
    replace_manual_capture_tags,
    sync_analysis_subject_tags,
    update_manual_tag_for_captures,
)
from .queries.albums import query_albums
from .queries.analysis import query_analysis_overview
from .queries.details import query_capture_detail
from .queries.quality import query_quality
from .queries.library import query_library_captures, query_library_filters
from .queries.overview import query_inbox, query_overview
from .queries.similarity import query_similarity_group, query_similarity_groups
from .reporting import build_report, write_report
from .settings import Settings, editable_config, save_editable_config
from .statistics import build_statistics
from .structure import rebuild_structure
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
    selection_reasons: list[str] | None = Field(default=None, max_length=5)


class CaptureTagInput(BaseModel):
    dimension: Literal["subject", "status", "problem", "location"]
    name: str = Field(min_length=1, max_length=40)


class CaptureTagsRequest(BaseModel):
    tags: list[CaptureTagInput] = Field(default_factory=list, max_length=64)


class BatchCaptureTagRequest(CaptureTagInput):
    capture_ids: list[int] = Field(min_length=1, max_length=500)
    action: Literal["add", "remove"] = "add"


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


class EditRecipeRequest(BaseModel):
    parameters: dict[str, float]
    status: Literal["draft", "accepted", "dismissed"] = "draft"
    note: str | None = Field(default=None, max_length=1000)
    source_analysis_id: int | None = Field(default=None, ge=1)


class ArchiveBaselineRequest(BaseModel):
    name: str | None = None
    note: str | None = "永久保留的原始档案库逻辑基线"


class EventUpdateRequest(BaseModel):
    proposed_name: str
    category: str
    status: str
    accessory_keys: list[str] | None = Field(default=None, max_length=100)


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


class LightroomSettingsRequest(BaseModel):
    catalog_root: str = Field(default="", max_length=1000)
    catalog_backup_root: str = Field(default="", max_length=1000)


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
    lightroom: LightroomSettingsRequest
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
            assigned_count = assign_captures_to_album(
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
    return query_overview(settings.database_path)


def _query_inbox(settings: Settings, limit: int) -> dict[str, Any]:
    return query_inbox(settings.database_path, limit)


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
    tag_subject: str | None = None,
    tag_status: str | None = None,
    tag_problem: str | None = None,
    tag_location: str | None = None,
    selection_reason: str | None = None,
    model_problem: str | None = None,
    review_condition: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    sort: str = "newest",
    collapse_groups: bool = False,
) -> dict[str, Any]:
    return query_library_captures(
        settings.database_path,
        limit,
        offset,
        album_id=album_id,
        unassigned_only=unassigned_only,
        category=category,
        camera_model=camera_model,
        lens_model=lens_model,
        rating=rating,
        selection=selection,
        quality=quality,
        tag_subject=tag_subject,
        tag_status=tag_status,
        tag_problem=tag_problem,
        tag_location=tag_location,
        selection_reason=selection_reason,
        model_problem=model_problem,
        review_condition=review_condition,
        date_from=date_from,
        date_to=date_to,
        search=search,
        sort=sort,
        collapse_groups=collapse_groups,
    )


def _query_library_filters(settings: Settings) -> dict[str, Any]:
    return query_library_filters(settings.database_path)




def _query_events(settings: Settings, limit: int, offset: int) -> dict[str, Any]:
    return query_albums(settings.database_path, limit, offset)


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
    ready, runtime_message = settings.ai_runtime_status()
    return query_analysis_overview(
        settings.database_path,
        settings.ai_model_path,
        settings.ai_quantization,
        ready,
        runtime_message,
    )


def _query_quality(
    settings: Settings,
    limit: int,
    offset: int,
    review_filter: str = "all",
    search: str | None = None,
    album_id: int | None = None,
) -> dict[str, Any]:
    return query_quality(
        settings.database_path,
        limit,
        offset,
        review_filter,
        search,
        album_id,
    )


def _query_similarity_groups(
    settings: Settings, limit: int, offset: int, review_filter: str = "all",
    album_id: int | None = None,
) -> dict[str, Any]:
    return query_similarity_groups(
        settings.database_path, limit, offset, review_filter, album_id
    )


def _query_similarity_group(settings: Settings, group_id: int) -> dict[str, Any]:
    return query_similarity_group(settings.database_path, group_id)


def _query_capture_detail(settings: Settings, capture_id: int) -> dict[str, Any]:
    item = query_capture_detail(settings.database_path, capture_id)
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
        tag_subject: str | None = Query(default=None, max_length=40),
        tag_status: str | None = Query(default=None, max_length=40),
        tag_problem: str | None = Query(default=None, max_length=40),
        tag_location: str | None = Query(default=None, max_length=40),
        selection_reason: str | None = Query(default=None, max_length=30),
        model_problem: str | None = Query(default=None, max_length=80),
        review_condition: str | None = Query(default=None, max_length=280),
        date_from: str | None = Query(default=None, max_length=10),
        date_to: str | None = Query(default=None, max_length=10),
        search: str | None = Query(default=None, max_length=120),
        sort: Literal["newest", "oldest", "name", "rating"] = "newest",
        collapse_groups: bool = False,
    ) -> dict[str, Any]:
        try:
            return _query_library_captures(
                settings, limit, offset, album_id=album_id, category=category,
                camera_model=camera_model, lens_model=lens_model, rating=rating,
                selection=selection, quality=quality, date_from=date_from, date_to=date_to,
                tag_subject=tag_subject, tag_status=tag_status,
                tag_problem=tag_problem, tag_location=tag_location,
                selection_reason=selection_reason,
                model_problem=model_problem,
                review_condition=review_condition,
                search=search, sort=sort, collapse_groups=collapse_groups,
                unassigned_only=unassigned,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
        album_id: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        return _query_quality(settings, limit, offset, review_filter, search, album_id)

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
            if request.action == "auto":
                regrouped = restore_similarity_grouping(connection, capture_id)
                return {"capture_id": capture_id, "action": request.action, **regrouped}
            regrouped = set_similarity_override(connection, capture_id, request.action)
            return {"capture_id": capture_id, "action": request.action, **regrouped}
        except SimilarityCaptureNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SimilarityGroupingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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

    @app.put("/api/captures/{capture_id}/tags")
    def update_capture_tags(
        capture_id: int, request: CaptureTagsRequest
    ) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            tags = replace_manual_capture_tags(
                connection,
                capture_id,
                (tag.model_dump() for tag in request.tags),
            )
            return {"capture_id": capture_id, "tags": tags}
        except CaptureTagNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CaptureTagError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.put("/api/captures/{capture_id}/edit-recipe")
    def update_edit_recipe(
        capture_id: int, request: EditRecipeRequest
    ) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            return save_edit_recipe(
                connection,
                capture_id,
                request.parameters,
                status=request.status,
                note=request.note,
                source_analysis_id=request.source_analysis_id,
            )
        except EditRecipeError as exc:
            status_code = 404 if str(exc) == "拍摄单元不存在" else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.post("/api/captures/{capture_id}/edit-recipe/{revision_id}/restore")
    def restore_edit_recipe_revision(capture_id: int, revision_id: int) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            return restore_edit_recipe(connection, capture_id, revision_id)
        except EditRecipeError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.get("/api/captures/{capture_id}/edit-preview")
    def edit_preview(
        capture_id: int,
        exposure_ev: float = Query(default=0, ge=-2, le=2),
        contrast: float = Query(default=0, ge=-100, le=100),
        highlights: float = Query(default=0, ge=-100, le=100),
        shadows: float = Query(default=0, ge=-100, le=100),
        temperature: float = Query(default=0, ge=-100, le=100),
        tint: float = Query(default=0, ge=-100, le=100),
        saturation: float = Query(default=0, ge=-100, le=100),
        sharpness: float = Query(default=0, ge=0, le=100),
    ) -> Response:
        try:
            source = thumbnail_cache.get(capture_id, 1280)
            content = render_edit_preview(source, {
                "exposure_ev": exposure_ev,
                "contrast": contrast,
                "highlights": highlights,
                "shadows": shadows,
                "temperature": temperature,
                "tint": tint,
                "saturation": saturation,
                "sharpness": sharpness,
            })
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, no-store"},
        )

    @app.post("/api/captures/tags/batch")
    def batch_update_capture_tags(
        request: BatchCaptureTagRequest,
    ) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            affected = update_manual_tag_for_captures(
                connection,
                request.capture_ids,
                dimension=request.dimension,
                name=request.name,
                action=request.action,
            )
            return {"affected_count": affected, "status": "saved"}
        except CaptureTagNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CaptureTagError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.post("/api/analysis/subject-tags/sync")
    def sync_subject_tags() -> dict[str, Any]:
        if manager.snapshot()["status"] in {"running", "paused"}:
            raise HTTPException(status_code=409, detail="后台任务运行时不能同步分析题材")
        connection = connect(settings.database_path)
        try:
            return {**sync_analysis_subject_tags(connection), "status": "synchronized"}
        finally:
            connection.close()

    @app.delete("/api/analysis/subject-tags")
    def clear_subject_tags() -> dict[str, Any]:
        if manager.snapshot()["status"] in {"running", "paused"}:
            raise HTTPException(status_code=409, detail="后台任务运行时不能清除分析题材")
        connection = connect(settings.database_path)
        try:
            removed = clear_analysis_subject_tags(connection)
            return {"status": "cleared", "removed_links": removed, "recoverable": True}
        finally:
            connection.close()

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
        connection = connect_readonly(settings.database_path)
        try:
            reference_count = equipment_album_reference_count(
                connection, request.kind, request.key
            )
            if reference_count:
                raise HTTPException(
                    status_code=409,
                    detail=f"该设备仍被 {reference_count} 个相册引用，请先在相册中取消勾选",
                )
            delete_equipment_item(
                settings.workspace / "Equipment" / "inventory.json",
                request.kind,
                request.key,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()
        return equipment()

    @app.get("/api/lightroom/status")
    def get_lightroom_status() -> dict[str, Any]:
        connection = connect_readonly(settings.database_path)
        try:
            return {
                **lightroom_status(connection),
                "preflight": lightroom_preflight(settings),
            }
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
        connection = connect(settings.database_path)
        try:
            if request.accessory_keys is not None:
                project_root = Path(__file__).resolve().parents[2]
                catalog = build_equipment_catalog(
                    connection,
                    project_root / "equipment" / "profile.toml",
                    project_root / "equipment" / "catalogs" / "fujifilm-x.toml",
                    settings.workspace / "Equipment" / "inventory.json",
                )
                known_keys = {
                    item["inventory_key"]
                    for item in [*catalog["accessories"], *catalog["hidden"]["accessory"]]
                }
                if not set(request.accessory_keys).issubset(known_keys):
                    raise HTTPException(status_code=422, detail="选择中包含不存在的附件")
            return update_album_record(
                connection, album_id, request.proposed_name, request.category, request.status,
                request.accessory_keys,
            )
        except AlbumNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlbumError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
        connection = connect(settings.database_path)
        try:
            return create_album_record(connection, request.name, request.category)
        except AlbumError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.post("/api/album-types", status_code=201)
    def create_album_type(request: AlbumTypeCreateRequest) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            return create_album_type_record(connection, request.name)
        except AlbumConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AlbumError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.put("/api/album-types/{name}")
    def update_album_type(name: str, request: AlbumTypeUpdateRequest) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            return rename_album_type(connection, name, request.name)
        except AlbumNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlbumConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AlbumError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.delete("/api/album-types/{name}")
    def delete_album_type(name: str) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            return delete_album_type_record(connection, name)
        except AlbumNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlbumConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        finally:
            connection.close()

    @app.put("/api/albums/{album_id}/captures")
    def assign_album_captures(
        album_id: int, request: AlbumAssignmentRequest
    ) -> dict[str, Any]:
        connection = connect(settings.database_path)
        try:
            try:
                assigned = assign_captures_to_album(connection, album_id, request.capture_ids)
            except AlbumError as exc:
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
        connection = connect(settings.database_path)
        try:
            save_capture_review(
                connection,
                capture_id,
                user_rating=request.user_rating,
                user_pick=request.user_pick,
                user_reject=request.user_reject,
                user_note=request.user_note,
                selection_reasons=request.selection_reasons,
            )
            return {"capture_id": capture_id, "status": "saved"}
        except CaptureReviewNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CaptureReviewError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
