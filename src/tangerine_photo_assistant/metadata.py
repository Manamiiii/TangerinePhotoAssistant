from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol

from PIL import Image, UnidentifiedImageError

METADATA_PROFILE_VERSION = 2

# Intentionally useful metadata only. Hardware/internal serial numbers, face
# coordinates and low-level RAW calibration matrices are excluded.
EXIF_TAGS = (
    "DateTimeOriginal",
    "CreateDate",
    "Make",
    "Model",
    "LensModel",
    "LensID",
    "ExposureTime",
    "FNumber",
    "ISO",
    "FocalLength",
    "FocalLengthIn35mmFormat",
    "ExposureCompensation",
    "ExposureProgram",
    "ExposureMode",
    "ShutterType",
    "MeteringMode",
    "WhiteBalance",
    "Flash",
    "FocusMode",
    "FilmMode",
    "DynamicRange",
    "DynamicRangeSetting",
    "Orientation",
    "OffsetTimeOriginal",
    "SubSecDateTimeOriginal",
    "ColorSpace",
    "BitsPerSample",
    "Quality",
    "ImageStabilization",
    "DriveMode",
    "DriveSpeed",
    "SequenceNumber",
    "AutoBracketing",
    "AFMode",
    "AFAreaMode",
    "FocusPixel",
    "BlurWarning",
    "FocusWarning",
    "ExposureWarning",
    "FacesDetected",
    "RollAngle",
    "CameraElevationAngle",
    "WhiteBalanceFineTune",
    "HighlightTone",
    "ShadowTone",
    "Saturation",
    "Sharpness",
    "NoiseReduction",
    "Clarity",
    "ColorChromeEffect",
    "ColorChromeFXBlue",
    "GrainEffectRoughness",
    "GrainEffectSize",
    "LensModulationOptimizer",
    "AutoDynamicRange",
    "RAFCompression",
    "ImageWidth",
    "ImageHeight",
    "ExifImageWidth",
    "ExifImageHeight",
    "GPSLatitude",
    "GPSLongitude",
)

NUMERIC_EXIF_TAGS = frozenset({
    "ExposureTime", "FNumber", "ISO", "FocalLength",
    "FocalLengthIn35mmFormat", "ExposureCompensation",
    "ImageWidth", "ImageHeight", "ExifImageWidth", "ExifImageHeight",
    "GPSLatitude", "GPSLongitude",
})


@dataclass(frozen=True)
class MetadataResult:
    path: Path
    values: dict[str, Any] | None
    error: str | None = None


class MetadataReader(Protocol):
    def read(self, paths: Iterable[Path]) -> Iterator[MetadataResult]: ...


class UnavailableMetadataReader:
    def read(self, paths: Iterable[Path]) -> Iterator[MetadataResult]:
        for path in paths:
            yield MetadataResult(path=path, values=None, error="ExifTool is not available")


class PillowMetadataReader:
    """Read the common photographic EXIF fields from formats Pillow supports.

    This is a small, read-only fallback for test environments without ExifTool.
    ExifTool remains the preferred reader for RAW, video, maker notes, and GPS.
    """

    _TOP_LEVEL_TAGS: ClassVar[dict[int, str]] = {
        271: "Make",
        272: "Model",
        306: "CreateDate",
    }
    _EXIF_IFD_TAGS: ClassVar[dict[int, str]] = {
        33434: "ExposureTime",
        33437: "FNumber",
        34855: "ISO",
        36867: "DateTimeOriginal",
        36868: "CreateDate",
        37380: "ExposureCompensation",
        37386: "FocalLength",
        41989: "FocalLengthIn35mmFormat",
        42036: "LensModel",
    }

    def read(self, paths: Iterable[Path]) -> Iterator[MetadataResult]:
        for path in paths:
            try:
                with Image.open(path) as image:
                    exif = image.getexif()
                    values: dict[str, Any] = {
                        "ImageWidth": image.width,
                        "ImageHeight": image.height,
                    }
                    for tag, name in self._TOP_LEVEL_TAGS.items():
                        value = exif.get(tag)
                        if value is not None:
                            values[name] = value
                    exif_ifd = exif.get_ifd(34665) if exif.get(34665) is not None else {}
                    for tag, name in self._EXIF_IFD_TAGS.items():
                        value = exif_ifd.get(tag)
                        if value is not None:
                            values[name] = _plain_exif_value(value)
                yield MetadataResult(path=path, values=values)
            except (OSError, UnidentifiedImageError, ValueError) as exc:
                yield MetadataResult(path=path, values=None, error=str(exc))


def _plain_exif_value(value: Any) -> Any:
    """Convert Pillow rational values to JSON-safe scalar numbers."""
    if isinstance(value, (str, bytes, int, float)) or value is None:
        return value
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return str(value)


class ExifToolMetadataReader:
    profile_version = METADATA_PROFILE_VERSION

    def __init__(self, executable: Path, batch_size: int = 32) -> None:
        self.executable = executable
        self.batch_size = batch_size

    def read(self, paths: Iterable[Path]) -> Iterator[MetadataResult]:
        iterator = iter(paths)
        try:
            process = subprocess.Popen(
                [str(self.executable), "-stay_open", "True", "-@", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            for path in iterator:
                yield MetadataResult(path=path, values=None, error=str(exc))
            return

        batch_number = 0
        try:
            while True:
                batch: list[Path] = []
                for _ in range(self.batch_size):
                    try:
                        batch.append(next(iterator))
                    except StopIteration:
                        break
                if not batch:
                    break
                batch_number += 1
                yield from self._read_batch(process, batch, batch_number)
        finally:
            if process.stdin is not None and process.poll() is None:
                try:
                    process.stdin.write("-stay_open\nFalse\n")
                    process.stdin.flush()
                    process.wait(timeout=10)
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    process.kill()

    def _read_batch(
        self,
        process: subprocess.Popen[str],
        paths: list[Path],
        batch_number: int,
    ) -> Iterator[MetadataResult]:
        if process.stdin is None or process.stdout is None or process.poll() is not None:
            for path in paths:
                yield MetadataResult(path=path, values=None, error="ExifTool process stopped")
            return

        arguments = [
            "-json",
            "-q",
            "-q",
            "-charset",
            "filename=UTF8",
            *[
                f"-{tag}#" if tag in NUMERIC_EXIF_TAGS else f"-{tag}"
                for tag in EXIF_TAGS
            ],
            *[str(path) for path in paths],
            f"-execute{batch_number}",
        ]
        try:
            process.stdin.write("\n".join(arguments) + "\n")
            process.stdin.flush()
            ready_marker = f"{{ready{batch_number}}}"
            output: list[str] = []
            while True:
                line = process.stdout.readline()
                if line == "":
                    raise RuntimeError("ExifTool closed before returning metadata")
                if line.strip() == ready_marker:
                    break
                output.append(line)
            records = json.loads("".join(output))
        except (BrokenPipeError, OSError, RuntimeError, json.JSONDecodeError) as exc:
            for path in paths:
                yield MetadataResult(path=path, values=None, error=str(exc))
            return

        # The Windows ExifTool executable may render non-ASCII SourceFile characters
        # with the active console code page in non-stay-open mode. ExifTool preserves
        # input order in JSON, so prefer positional matching for a complete batch.
        if len(records) == len(paths):
            for path, record in zip(paths, records, strict=True):
                record.pop("SourceFile", None)
                error = record.pop("Error", None)
                yield MetadataResult(
                    path=path,
                    values=record if error is None else None,
                    error=str(error) if error is not None else None,
                )
            return

        by_path = {
            _path_key(Path(str(record.get("SourceFile", "")))): record for record in records
        }
        for path in paths:
            record = by_path.get(_path_key(path))
            if record is None:
                yield MetadataResult(path=path, values=None, error="No ExifTool result")
            else:
                record.pop("SourceFile", None)
                yield MetadataResult(path=path, values=record)


def _path_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def number(value: Any, target: type[int | float]) -> int | float | None:
    if value is None or value == "":
        return None
    try:
        return target(value)
    except (TypeError, ValueError):
        return None


EXIF_DATETIME = re.compile(
    r"^(?P<year>\d{4}):(?P<month>\d{2}):(?P<day>\d{2}) "
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
)


def normalize_datetime(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = EXIF_DATETIME.match(value.strip())
    if match is None or match.group("year") == "0000":
        return None
    parts = match.groupdict()
    return (
        f"{parts['year']}-{parts['month']}-{parts['day']}T"
        f"{parts['hour']}:{parts['minute']}:{parts['second']}"
    )


def database_fields(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "exif_json": json.dumps(values, ensure_ascii=False, sort_keys=True),
        "captured_at": normalize_datetime(
            values.get("DateTimeOriginal") or values.get("CreateDate")
        ),
        "camera_make": values.get("Make"),
        "camera_model": values.get("Model"),
        "lens_model": values.get("LensModel") or values.get("LensID"),
        "exposure_time": number(values.get("ExposureTime"), float),
        "f_number": number(values.get("FNumber"), float),
        "iso": number(values.get("ISO"), int),
        "focal_length_mm": number(values.get("FocalLength"), float),
        "focal_length_35mm": number(values.get("FocalLengthIn35mmFormat"), float),
        "exposure_compensation": number(values.get("ExposureCompensation"), float),
        "width": number(values.get("ExifImageWidth") or values.get("ImageWidth"), int),
        "height": number(values.get("ExifImageHeight") or values.get("ImageHeight"), int),
        "gps_latitude": number(values.get("GPSLatitude"), float),
        "gps_longitude": number(values.get("GPSLongitude"), float),
    }
