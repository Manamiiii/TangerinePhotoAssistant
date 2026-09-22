from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import album_archive
from .albums import (
    AlbumConflictError,
    AlbumError,
    AlbumNotFoundError,
    assign_captures_to_album,
    rename_album_type,
)
from .albums import (
    create_album as create_album_record,
)
from .albums import (
    create_album_type as create_album_type_record,
)
from .albums import (
    delete_album_type as delete_album_type_record,
)
from .albums import (
    update_album as update_album_record,
)
from .app_paths import resource_root
from .database import connect, connect_readonly
from .equipment import build_equipment_catalog
from .queries.albums import query_albums
from .settings import Settings
from .structure import rebuild_structure


class AlbumTaskManager(Protocol):
    def snapshot(self) -> dict[str, Any]: ...
    def start(self, album_id: int) -> dict[str, Any]: ...
    def preview_album_archive(self, album_id: int) -> dict[str, Any]: ...
    def start_album_archive(self, plan_id: str, confirmation: str) -> dict[str, Any]: ...


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


class AlbumArchiveRequest(BaseModel):
    plan_id: str = Field(min_length=32, max_length=32)
    confirmation: str = Field(min_length=1, max_length=200)


def query_album_listing(settings: Settings, limit: int, offset: int) -> dict[str, Any]:
    try:
        unfinished = album_archive.pending(settings)
    except album_archive.ArchiveRecordError:
        result = query_albums(settings.database_path, limit, offset)
        for item in result["items"]:
            item["archive_state"] = "unknown"
        return result
    return query_albums(
        settings.database_path, limit, offset, unfinished["album_id"] if unfinished else None
    )


def create_album_router(
    get_settings: Callable[[], Settings],
    manager: AlbumTaskManager,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/albums")
    def albums(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        settings = get_settings()
        return query_album_listing(settings, limit, offset)

    @router.post("/api/structure/rebuild")
    def rebuild_event_structure() -> dict[str, int]:
        settings = get_settings()
        if manager.snapshot()["status"] == "running":
            raise HTTPException(status_code=409, detail="扫描运行时不能重新整理相册建议")
        connection = connect(settings.database_path)
        try:
            return rebuild_structure(connection, settings.burst_time_gap_seconds)
        finally:
            connection.close()

    def save_album(album_id: int, request: EventUpdateRequest) -> dict[str, Any]:
        settings = get_settings()
        connection = connect(settings.database_path)
        try:
            if request.accessory_keys is not None:
                project_root = resource_root()
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
                connection,
                album_id,
                request.proposed_name,
                request.category,
                request.status,
                request.accessory_keys,
            )
        except AlbumNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlbumError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @router.put("/api/albums/{album_id}")
    def update_album(album_id: int, request: EventUpdateRequest) -> dict[str, Any]:
        return save_album(album_id, request)

    @router.post("/api/albums", status_code=201)
    def create_album(request: AlbumCreateRequest) -> dict[str, Any]:
        settings = get_settings()
        connection = connect(settings.database_path)
        try:
            return create_album_record(connection, request.name, request.category)
        except AlbumError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @router.get("/api/albums/{album_id}/archive/status")
    def album_archive_status(album_id: int) -> dict[str, Any]:
        settings = get_settings()
        with closing(connect_readonly(settings.database_path)) as connection:
            paths = [
                row[0]
                for row in connection.execute(
                    """SELECT DISTINCT f.path FROM files f
                JOIN capture_files cf ON cf.file_id=f.id
                JOIN event_captures ec ON ec.capture_id=cf.capture_id
                WHERE ec.event_id=?""",
                    (album_id,),
                )
            ]
        try:
            unfinished = album_archive.pending(settings)
        except album_archive.ArchiveRecordError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "file_count": len(paths),
            "inbox_count": sum(
                Path(p).is_relative_to(settings.originals / "待整理") for p in paths
            ),
            "pending": bool(unfinished and unfinished["album_id"] == album_id),
        }

    @router.post("/api/albums/{album_id}/archive/preview")
    def preview_album_archive(album_id: int) -> dict[str, Any]:
        try:
            return manager.preview_album_archive(album_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/api/albums/{album_id}/archive/execute", status_code=202)
    def execute_album_archive(album_id: int, request: AlbumArchiveRequest) -> dict[str, Any]:
        settings = get_settings()
        try:
            plan = album_archive.load(settings, request.plan_id)
            if plan["album_id"] != album_id:
                raise ValueError("归档计划不属于当前相册")
            return manager.start_album_archive(request.plan_id, request.confirmation)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/api/album-types", status_code=201)
    def create_album_type(request: AlbumTypeCreateRequest) -> dict[str, Any]:
        settings = get_settings()
        connection = connect(settings.database_path)
        try:
            return create_album_type_record(connection, request.name)
        except AlbumConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AlbumError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            connection.close()

    @router.put("/api/album-types/{name}")
    def update_album_type(name: str, request: AlbumTypeUpdateRequest) -> dict[str, Any]:
        settings = get_settings()
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

    @router.delete("/api/album-types/{name}")
    def delete_album_type(name: str) -> dict[str, Any]:
        settings = get_settings()
        connection = connect(settings.database_path)
        try:
            return delete_album_type_record(connection, name)
        except AlbumNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlbumConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        finally:
            connection.close()

    @router.put("/api/albums/{album_id}/captures")
    def assign_album_captures(album_id: int, request: AlbumAssignmentRequest) -> dict[str, Any]:
        settings = get_settings()
        connection = connect(settings.database_path)
        try:
            try:
                assigned = assign_captures_to_album(connection, album_id, request.capture_ids)
            except AlbumError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {"album_id": album_id, "assigned_count": assigned}
        finally:
            connection.close()

    @router.post("/api/scan", status_code=202)
    def start_scan(request: ScanStartRequest) -> dict[str, Any]:
        try:
            return manager.start(request.album_id)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
