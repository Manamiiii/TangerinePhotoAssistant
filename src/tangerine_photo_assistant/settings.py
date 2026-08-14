from __future__ import annotations

import json
import os
import shutil
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    originals: Path
    workspace: Path
    cache_root: Path
    cache_max_size_gb: int
    offline_only: bool
    read_only: bool
    allow_move: bool
    allow_delete: bool
    allow_original_metadata_write: bool
    raw_extensions: tuple[str, ...]
    exiftool: Path | None
    metadata_batch_size: int
    burst_time_gap_seconds: float
    ai_model_path: Path | None = None
    ai_python: Path | None = None
    ai_quantization: str = "none"
    ai_gpu_memory_limit_gb: int = 14
    ai_max_new_tokens: int = 768
    ai_image_max_edge: int = 960
    ai_json_retry_count: int = 1
    thumbnail_max_size_gb: int = 8
    lightroom_catalog_root: Path | None = None
    lightroom_catalog_backup_root: Path | None = None
    lightroom_write_xmp: bool = False

    @classmethod
    def load(cls, path: Path) -> Settings:
        with path.open("rb") as file:
            data = tomllib.load(file)

        tools = data.get("tools", {})
        models = data.get("models", {})
        lightroom = data.get("lightroom", {})
        exiftool_value = str(tools.get("exiftool", "")).strip()
        return cls(
            originals=Path(data["library"]["originals"]),
            workspace=Path(data["library"]["workspace"]),
            cache_root=Path(data["cache"]["root"]),
            cache_max_size_gb=int(data["cache"]["max_size_gb"]),
            offline_only=bool(data["analysis"]["offline_only"]),
            read_only=bool(data["library"]["read_only"]),
            allow_move=bool(data["safety"]["allow_move"]),
            allow_delete=bool(data["safety"]["allow_delete"]),
            allow_original_metadata_write=bool(
                data["safety"]["allow_original_metadata_write"]
            ),
            raw_extensions=tuple(
                str(extension).lower() for extension in data["analysis"]["raw_extensions"]
            ),
            exiftool=Path(exiftool_value) if exiftool_value else None,
            metadata_batch_size=int(data["analysis"].get("metadata_batch_size", 32)),
            burst_time_gap_seconds=float(
                data["analysis"].get("burst_time_gap_seconds", 3.0)
            ),
            ai_model_path=(
                Path(str(models["vision_language_model"]))
                if models.get("vision_language_model") else None
            ),
            ai_python=(
                Path(str(models["python"])) if models.get("python") else None
            ),
            ai_quantization=str(models.get("quantization", "none")).strip().lower(),
            ai_gpu_memory_limit_gb=int(models.get("gpu_memory_limit_gb", 14)),
            ai_max_new_tokens=int(models.get("max_new_tokens", 768)),
            ai_image_max_edge=int(models.get("image_max_edge", 960)),
            ai_json_retry_count=int(models.get("json_retry_count", 1)),
            thumbnail_max_size_gb=int(data["cache"].get("thumbnail_max_size_gb", 8)),
            lightroom_catalog_root=(
                Path(str(lightroom["catalog_root"]))
                if str(lightroom.get("catalog_root", "")).strip() else None
            ),
            lightroom_catalog_backup_root=(
                Path(str(lightroom["catalog_backup_root"]))
                if str(lightroom.get("catalog_backup_root", "")).strip() else None
            ),
            lightroom_write_xmp=bool(lightroom.get("write_xmp", False)),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        resolved = {
            "originals": self.originals.resolve(),
            "workspace": self.workspace.resolve(),
            "cache": self.cache_root.resolve(),
        }
        if not self.originals.is_dir():
            errors.append(f"Photo library does not exist: {self.originals}")
        if len(set(resolved.values())) != len(resolved):
            errors.append("Originals, workspace, and cache paths must be different")
        if resolved["workspace"].is_relative_to(resolved["originals"]):
            errors.append("Workspace must not be inside the photo library")
        if resolved["cache"].is_relative_to(resolved["originals"]):
            errors.append("Cache must not be inside the photo library")
        if self.cache_max_size_gb <= 0:
            errors.append("Cache size ceiling must be positive")
        if self.thumbnail_max_size_gb <= 0:
            errors.append("Thumbnail cache size ceiling must be positive")
        if self.thumbnail_max_size_gb > self.cache_max_size_gb:
            errors.append("Thumbnail cache ceiling cannot exceed the total cache ceiling")
        if not self.offline_only:
            errors.append("Offline-only analysis must remain enabled")
        if not self.read_only:
            errors.append("The photo library must remain read-only during inventory")
        if self.allow_move or self.allow_delete or self.allow_original_metadata_write:
            errors.append("All photo mutation switches must remain disabled during inventory")
        if self.lightroom_write_xmp:
            errors.append("Automatic Lightroom XMP writing must remain disabled")
        if self.metadata_batch_size <= 0:
            errors.append("Metadata batch size must be positive")
        if self.burst_time_gap_seconds <= 0:
            errors.append("Burst time gap must be positive")
        if self.ai_max_new_tokens <= 0:
            errors.append("AI max output tokens must be positive")
        if not 512 <= self.ai_image_max_edge <= 2048:
            errors.append("AI image maximum edge must be between 512 and 2048 pixels")
        if self.ai_quantization not in {"none", "int8"}:
            errors.append("AI quantization must be either none or int8")
        if self.ai_gpu_memory_limit_gb <= 0:
            errors.append("AI GPU memory limit must be positive")
        if not 0 <= self.ai_json_retry_count <= 3:
            errors.append("AI JSON retry count must be between 0 and 3")
        return errors

    def ai_runtime_status(self) -> tuple[bool, str]:
        if self.ai_model_path is None or not self.ai_model_path.is_dir():
            return False, "本地视觉语言模型目录不可用"
        if self.ai_python is None or not self.ai_python.is_file():
            return False, "本地模型 Python 环境不可用"
        return True, "本地模型运行环境已就绪"

    @property
    def database_path(self) -> Path:
        return self.workspace / "AnalysisDatabase" / "catalog.sqlite3"

    @property
    def reports_path(self) -> Path:
        return self.workspace / "Reports"

    def find_exiftool(self) -> Path | None:
        if self.exiftool is not None:
            return self.exiftool if self.exiftool.is_file() else None
        discovered = shutil.which("exiftool")
        return Path(discovered) if discovered else None


def write_safe_config(
    path: Path,
    originals: Path,
    workspace: Path,
    cache_root: Path,
) -> Path:
    """Create a portable, conservative config without touching the photo library."""
    if path.exists():
        raise FileExistsError(f"Configuration already exists: {path}")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Configuration directory does not exist: {path.parent}")

    def quote(value: Path) -> str:
        return json.dumps(str(value.resolve()), ensure_ascii=False)

    content = f"""[library]
originals = {quote(originals)}
workspace = {quote(workspace)}
read_only = true

[cache]
root = {quote(cache_root)}
max_size_gb = 20
thumbnail_max_size_gb = 4

[lightroom]
catalog_root = ""
catalog_backup_root = ""
write_xmp = false

[analysis]
offline_only = true
pair_jpeg_raw = true
raw_extensions = [".raf", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".rw2", ".orf"]
burst_time_gap_seconds = 3.0
generate_full_resolution_previews = false
metadata_batch_size = 32

[tools]
exiftool = ""

[models]
python = ""
vision_language_model = ""
quantization = "none"
gpu_memory_limit_gb = 8
max_new_tokens = 512
image_max_edge = 960
json_retry_count = 1

[safety]
allow_move = false
allow_delete = false
allow_original_metadata_write = false
require_reviewed_manifest = true
"""
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def editable_config(path: Path) -> dict[str, object]:
    with path.open("rb") as file:
        data = tomllib.load(file)
    return {
        "library": {
            "originals": str(data["library"]["originals"]),
            "workspace": str(data["library"]["workspace"]),
        },
        "cache": {
            "root": str(data["cache"]["root"]),
            "max_size_gb": int(data["cache"]["max_size_gb"]),
            "thumbnail_max_size_gb": int(data["cache"].get("thumbnail_max_size_gb", 8)),
        },
        "lightroom": {
            "catalog_root": str(data.get("lightroom", {}).get("catalog_root", "")),
            "catalog_backup_root": str(
                data.get("lightroom", {}).get("catalog_backup_root", "")
            ),
        },
        "analysis": {
            "raw_extensions": [str(value) for value in data["analysis"]["raw_extensions"]],
            "burst_time_gap_seconds": float(data["analysis"].get("burst_time_gap_seconds", 3.0)),
            "metadata_batch_size": int(data["analysis"].get("metadata_batch_size", 32)),
        },
        "tools": {"exiftool": str(data.get("tools", {}).get("exiftool", ""))},
        "models": {
            "python": str(data.get("models", {}).get("python", "")),
            "vision_language_model": str(
                data.get("models", {}).get("vision_language_model", "")
            ),
            "quantization": str(data.get("models", {}).get("quantization", "none")),
            "gpu_memory_limit_gb": int(
                data.get("models", {}).get("gpu_memory_limit_gb", 8)
            ),
            "max_new_tokens": int(data.get("models", {}).get("max_new_tokens", 512)),
            "image_max_edge": int(data.get("models", {}).get("image_max_edge", 960)),
        },
    }


def _toml_string(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def save_editable_config(path: Path, changes: dict[str, object]) -> Path:
    """Validate and atomically save editable settings, preserving safe fixed defaults."""
    with path.open("rb") as file:
        existing = tomllib.load(file)
    library = changes["library"]
    cache = changes["cache"]
    lightroom = changes["lightroom"]
    analysis = changes["analysis"]
    tools = changes["tools"]
    models = changes["models"]
    assert isinstance(library, dict)
    assert isinstance(cache, dict)
    assert isinstance(lightroom, dict)
    assert isinstance(analysis, dict)
    assert isinstance(tools, dict)
    assert isinstance(models, dict)
    for label, value in (
        ("Photo library", library["originals"]),
        ("Workspace", library["workspace"]),
        ("Cache", cache["root"]),
    ):
        if not Path(str(value)).is_absolute():
            raise ValueError(f"{label} path must be absolute")
    for label, value in (
        ("Lightroom catalog", lightroom.get("catalog_root", "")),
        ("Lightroom catalog backup", lightroom.get("catalog_backup_root", "")),
    ):
        if str(value).strip() and not Path(str(value)).is_absolute():
            raise ValueError(f"{label} path must be absolute when configured")
    raw_extensions = [str(item).strip().lower() for item in analysis["raw_extensions"]]
    if not raw_extensions or any(not item.startswith(".") for item in raw_extensions):
        raise ValueError("RAW extensions must be a non-empty list such as .raf and .dng")

    text = f"""[library]
originals = {_toml_string(library["originals"])}
workspace = {_toml_string(library["workspace"])}
read_only = true

[cache]
root = {_toml_string(cache["root"])}
max_size_gb = {int(cache["max_size_gb"])}
thumbnail_max_size_gb = {int(cache["thumbnail_max_size_gb"])}

[lightroom]
catalog_root = {_toml_string(lightroom.get("catalog_root", ""))}
catalog_backup_root = {_toml_string(lightroom.get("catalog_backup_root", ""))}
write_xmp = false

[analysis]
offline_only = true
pair_jpeg_raw = true
raw_extensions = [{", ".join(_toml_string(item) for item in raw_extensions)}]
burst_time_gap_seconds = {float(analysis["burst_time_gap_seconds"])}
generate_full_resolution_previews = false
metadata_batch_size = {int(analysis["metadata_batch_size"])}

[tools]
exiftool = {_toml_string(tools.get("exiftool", ""))}

[models]
python = {_toml_string(models.get("python", ""))}
vision_language_model = {_toml_string(models.get("vision_language_model", ""))}
quantization = {_toml_string(models.get("quantization", "none"))}
gpu_memory_limit_gb = {int(models["gpu_memory_limit_gb"])}
max_new_tokens = {int(models["max_new_tokens"])}
image_max_edge = {int(models["image_max_edge"])}
json_retry_count = {int(existing.get("models", {}).get("json_retry_count", 1))}

[safety]
allow_move = false
allow_delete = false
allow_original_metadata_write = false
require_reviewed_manifest = true
"""
    temporary = path.with_name(f".{path.name}.pending")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    try:
        candidate = Settings.load(temporary)
        errors = candidate.validate()
        if errors:
            raise ValueError("; ".join(errors))
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        backup = path.with_name(f"{path.name}.backup-{stamp}")
        shutil.copy2(path, backup)
        os.replace(temporary, path)
        return backup
    finally:
        if temporary.exists():
            temporary.unlink()
