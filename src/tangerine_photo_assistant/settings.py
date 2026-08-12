from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass
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

    @classmethod
    def load(cls, path: Path) -> Settings:
        with path.open("rb") as file:
            data = tomllib.load(file)

        tools = data.get("tools", {})
        models = data.get("models", {})
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
