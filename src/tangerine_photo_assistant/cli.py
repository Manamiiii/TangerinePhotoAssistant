from __future__ import annotations

import argparse
import ipaddress
import os
import shutil
import subprocess
import webbrowser
from dataclasses import replace
from pathlib import Path
from threading import Timer

from . import __version__
from .ai_analysis import create_ai_run, write_ai_run_report
from .archive import (
    create_archive_baseline,
    run_integrity_check,
)
from .database import connect, connect_readonly
from .inventory import enrich_metadata, scan_library
from .lightroom import write_lightroom_manifest
from .metadata import ExifToolMetadataReader, PillowMetadataReader
from .migration import active_library_root
from .pairing import rebuild_captures
from .quality import analyze_quality
from .reporting import build_report, write_report
from .settings import Settings
from .structure import rebuild_structure
from .visual import analyze_visuals


def _drive_free_gb(path: Path) -> float | None:
    anchor = Path(path.anchor)
    if not anchor.exists():
        return None
    return shutil.disk_usage(anchor).free / (1024**3)


def doctor(config_path: Path) -> int:
    settings = Settings.load(config_path)
    errors = settings.validate()

    print(f"TangerinePhotoAssistant {__version__}")
    print(f"Originals: {settings.originals} (read-only={settings.read_only})")
    print(f"Workspace: {settings.workspace}")
    print(
        f"Fast cache: {settings.cache_root} "
        f"(ceiling={settings.cache_max_size_gb} GB)"
    )
    print(f"Offline only: {settings.offline_only}")
    exiftool = settings.find_exiftool()
    print(f"ExifTool: {exiftool if exiftool else 'not found (metadata will be deferred)'}")
    print(
        "Mutations: "
        f"move={settings.allow_move}, delete={settings.allow_delete}, "
        f"write-original-metadata={settings.allow_original_metadata_write}"
    )

    for label, path in (
        ("originals", settings.originals),
        ("workspace", settings.workspace),
        ("cache", settings.cache_root),
    ):
        free = _drive_free_gb(path)
        if free is not None:
            print(f"Free space for {label}: {free:.1f} GB")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("Configuration is safe for read-only inventory.")
    return 0


def _settings(config_path: Path) -> Settings:
    settings = Settings.load(config_path)
    errors = settings.validate()
    if errors:
        raise ValueError("; ".join(errors))
    if settings.database_path.is_file():
        connection = connect(settings.database_path)
        try:
            active_root = active_library_root(connection, settings.originals)
        finally:
            connection.close()
        if active_root != settings.originals:
            settings = replace(settings, originals=active_root)
    return settings


def scan(config_path: Path, metadata_mode: str) -> int:
    settings = _settings(config_path)
    exiftool = settings.find_exiftool()
    if metadata_mode == "required" and exiftool is None:
        raise ValueError("ExifTool is required but was not found")
    reader = (
        ExifToolMetadataReader(exiftool, settings.metadata_batch_size)
        if exiftool is not None and metadata_mode != "off"
        else PillowMetadataReader() if metadata_mode == "auto" else None
    )
    connection = connect(settings.database_path)
    try:
        run_id = scan_library(
            connection,
            settings,
            metadata_reader=reader,
            progress=lambda count: print(f"Indexed {count:,} files..."),
        )
        pairing = rebuild_captures(connection)
        report_paths = write_report(build_report(connection), settings.reports_path)
    finally:
        connection.close()
    print(f"Scan {run_id} complete")
    print("Pairing: " + ", ".join(f"{key}={value:,}" for key, value in sorted(pairing.items())))
    print(f"Reports: {report_paths[0]} and {report_paths[1]}")
    if exiftool is None and metadata_mode != "off":
        print("ExifTool was not found; Pillow read common EXIF fields from supported images.")
    return 0


def metadata(config_path: Path) -> int:
    settings = _settings(config_path)
    exiftool = settings.find_exiftool()
    if exiftool is None:
        raise ValueError("ExifTool was not found")
    connection = connect(settings.database_path)
    try:
        updated = enrich_metadata(
            connection,
            settings,
            ExifToolMetadataReader(exiftool, settings.metadata_batch_size),
        )
        rebuild_captures(connection)
        report_paths = write_report(build_report(connection), settings.reports_path)
    finally:
        connection.close()
    print(f"Metadata updated for {updated:,} files")
    print(f"Reports: {report_paths[0]} and {report_paths[1]}")
    return 0


def report(config_path: Path) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        pairing = rebuild_captures(connection)
        report_paths = write_report(build_report(connection), settings.reports_path)
    finally:
        connection.close()
    print("Pairing: " + ", ".join(f"{key}={value:,}" for key, value in sorted(pairing.items())))
    print(f"Reports: {report_paths[0]} and {report_paths[1]}")
    return 0


def structure(config_path: Path) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        result = rebuild_structure(connection, settings.burst_time_gap_seconds)
    finally:
        connection.close()
    print("Structure analysis complete")
    for key, value in result.items():
        print(f"{key}: {value:,}")
    return 0


def visual(config_path: Path, limit: int | None) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        result = analyze_visuals(
            connection,
            progress=lambda stage, current, total: print(
                f"{stage}: {current:,} / {total:,}"
            ),
            limit=limit,
            exiftool=settings.find_exiftool(),
            metadata_batch_size=settings.metadata_batch_size,
        )
    finally:
        connection.close()
    print("Read-only visual prefilter complete")
    for key, value in result.items():
        print(f"{key}: {value:,}")
    if limit is not None:
        print("Sample mode: similarity groups were not rebuilt.")
    return 0


def quality(config_path: Path, limit: int | None) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        result = analyze_quality(
            connection,
            progress=lambda current, total: print(f"quality: {current:,} / {total:,}"),
            limit=limit,
        )
    finally:
        connection.close()
    print("Technical quality analysis complete")
    for key, value in result.items():
        print(f"{key}: {value:,}")
    if limit is not None:
        print("Sample mode: similarity-group recommendations were not rebuilt.")
    return 0


def ai(config_path: Path, mode: str, limit: int) -> int:
    settings = _settings(config_path)
    ready, message = settings.ai_runtime_status()
    if not ready:
        raise ValueError(message)
    connection = connect(settings.database_path)
    try:
        run = create_ai_run(  # type: ignore[arg-type]
            connection, settings.ai_model_path, mode, limit,
            settings.ai_quantization,
        )
    finally:
        connection.close()
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
        str(settings.ai_python), "-m", "tangerine_photo_assistant.ai_worker",
        "--config", str(config_path.resolve()), "--run-id", str(run["run_id"]),
    ]
    print(f"AI run {run['run_id']} queued for {run['requested_count']:,} photos")
    return subprocess.run(command, cwd=project_root, env=environment, check=False).returncode


def ai_report(config_path: Path, run_id: int) -> int:
    settings = _settings(config_path)
    connection = connect_readonly(settings.database_path)
    try:
        result = write_ai_run_report(connection, settings.reports_path, run_id)
    finally:
        connection.close()
    print(f"AI run {run_id} report: {result['row_count']:,} rows")
    print(f"CSV: {settings.reports_path / result['csv_name']}")
    print(f"JSON: {settings.reports_path / result['json_name']}")
    print("No photos, XMP, or Lightroom catalogs were changed.")
    return 0


def archive_baseline(config_path: Path, name: str) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        result = create_archive_baseline(
            connection, name, "永久保留的原始档案库逻辑基线"
        )
    finally:
        connection.close()
    print(
        f"Archive baseline {result['name']} created: "
        f"{result['file_count']:,} files, {result['total_bytes'] / 1024**3:.2f} GB"
    )
    return 0


def archive_check(config_path: Path) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        result = run_integrity_check(connection, "archive")
        baseline = result["baseline"]
        if baseline is None:
            raise ValueError("No archive baseline exists")
    finally:
        connection.close()
    comparison = result["comparison"]
    print(f"Baseline: {baseline['name']}")
    print(f"Missing: {comparison['missing']:,}")
    print(f"Changed: {comparison['changed']:,}")
    print(f"New: {comparison['new']:,}")
    return 0 if comparison["healthy"] else 2


def active_baseline(config_path: Path, name: str) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        result = create_archive_baseline(
            connection, name, "活动图库逻辑保护基线", scope="active"
        )
    finally:
        connection.close()
    print(
        f"Active library baseline {result['name']} created: "
        f"{result['file_count']:,} files, {result['total_bytes'] / 1024**3:.2f} GB"
    )
    return 0


def active_check(config_path: Path) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        result = run_integrity_check(connection, "active")
        baseline = result["baseline"]
        if baseline is None:
            raise ValueError("No active library baseline exists")
        comparison = result["comparison"]
    finally:
        connection.close()
    print(f"Baseline: {baseline['name']}")
    print(f"Missing: {comparison['missing']:,}")
    print(f"Changed: {comparison['changed']:,}")
    print(f"New: {comparison['new']:,}")
    return 0 if comparison["healthy"] else 2


def lightroom_manifest(config_path: Path) -> int:
    settings = _settings(config_path)
    connection = connect(settings.database_path)
    try:
        result = write_lightroom_manifest(connection, settings.reports_path)
    finally:
        connection.close()
    print(f"Lightroom preparation manifest: {result['capture_count']:,} captures")
    print(f"CSV: {settings.reports_path / result['csv_name']}")
    print(f"JSON: {settings.reports_path / result['json_name']}")
    print("No source files, XMP, copies, or Lightroom catalogs were changed.")
    return 0


def serve(config_path: Path, host: str, port: int, open_browser: bool) -> int:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("Local server host must be a loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("Local server may only bind to a loopback IP address")

    from uvicorn import run

    from .webapp import create_app

    project_root = Path(__file__).resolve().parents[2]
    static_directory = project_root / "web" / "dist"
    app = create_app(config_path.resolve(), static_directory)
    url = f"http://{host}:{port}"
    if open_browser:
        Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"TangerinePhotoAssistant is available at {url}")
    run(app, host=host, port=port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-first photo curation assistant")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Validate paths and safety settings")
    doctor_parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to TOML configuration",
    )

    scan_parser = subparsers.add_parser("scan", help="Run a read-only incremental inventory")
    scan_parser.add_argument("--config", type=Path, default=Path("config.toml"))
    scan_parser.add_argument(
        "--metadata",
        choices=("auto", "off", "required"),
        default="auto",
        help="Use ExifTool automatically, skip it, or require it",
    )

    metadata_parser = subparsers.add_parser(
        "metadata", help="Enrich pending files with ExifTool metadata"
    )
    metadata_parser.add_argument("--config", type=Path, default=Path("config.toml"))

    report_parser = subparsers.add_parser("report", help="Rebuild pairing and reports")
    report_parser.add_argument("--config", type=Path, default=Path("config.toml"))

    structure_parser = subparsers.add_parser(
        "structure", help="Rebuild proposed events and metadata burst candidates"
    )
    structure_parser.add_argument("--config", type=Path, default=Path("config.toml"))

    visual_parser = subparsers.add_parser(
        "visual", help="Find exact duplicates and build lightweight visual similarity groups"
    )
    visual_parser.add_argument("--config", type=Path, default=Path("config.toml"))
    visual_parser.add_argument(
        "--limit", type=int, default=None,
        help="Only fingerprint this many burst captures; skips group rebuild",
    )

    quality_parser = subparsers.add_parser(
        "quality", help="Analyze explainable technical quality without a large model"
    )
    quality_parser.add_argument("--config", type=Path, default=Path("config.toml"))
    quality_parser.add_argument("--limit", type=int, default=None)

    ai_parser = subparsers.add_parser(
        "ai", help="Run the configured local vision-language model"
    )
    ai_parser.add_argument("--config", type=Path, default=Path("config.toml"))
    ai_parser.add_argument("--mode", choices=("benchmark", "recommended"), default="benchmark")
    ai_parser.add_argument("--limit", type=int, default=100)

    ai_report_parser = subparsers.add_parser(
        "ai-report", help="Export one local model run to CSV and JSON"
    )
    ai_report_parser.add_argument("--config", type=Path, default=Path("config.toml"))
    ai_report_parser.add_argument("--run-id", type=int, required=True)

    baseline_parser = subparsers.add_parser(
        "archive-baseline", help="Record an immutable logical baseline of the original archive"
    )
    baseline_parser.add_argument("--config", type=Path, default=Path("config.toml"))
    baseline_parser.add_argument("--name", required=True)

    archive_check_parser = subparsers.add_parser(
        "archive-check", help="Compare the current inventory with the latest archive baseline"
    )
    archive_check_parser.add_argument("--config", type=Path, default=Path("config.toml"))

    active_baseline_parser = subparsers.add_parser(
        "active-baseline", help="Record a logical baseline of the active library"
    )
    active_baseline_parser.add_argument("--config", type=Path, default=Path("config.toml"))
    active_baseline_parser.add_argument("--name", required=True)

    active_check_parser = subparsers.add_parser(
        "active-check", help="Compare the active library with its latest baseline"
    )
    active_check_parser.add_argument("--config", type=Path, default=Path("config.toml"))

    lightroom_parser = subparsers.add_parser(
        "lightroom-manifest", help="Write a reviewable CSV/JSON preparation plan only"
    )
    lightroom_parser.add_argument("--config", type=Path, default=Path("config.toml"))

    serve_parser = subparsers.add_parser("serve", help="Start the local-only web application")
    serve_parser.add_argument("--config", type=Path, default=Path("config.toml"))
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--no-open", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "doctor":
            return doctor(args.config)
        if args.command == "scan":
            return scan(args.config, args.metadata)
        if args.command == "metadata":
            return metadata(args.config)
        if args.command == "report":
            return report(args.config)
        if args.command == "structure":
            return structure(args.config)
        if args.command == "visual":
            return visual(args.config, args.limit)
        if args.command == "quality":
            return quality(args.config, args.limit)
        if args.command == "ai":
            return ai(args.config, args.mode, args.limit)
        if args.command == "ai-report":
            return ai_report(args.config, args.run_id)
        if args.command == "archive-baseline":
            return archive_baseline(args.config, args.name)
        if args.command == "archive-check":
            return archive_check(args.config)
        if args.command == "active-baseline":
            return active_baseline(args.config, args.name)
        if args.command == "active-check":
            return active_check(args.config)
        if args.command == "lightroom-manifest":
            return lightroom_manifest(args.config)
        if args.command == "serve":
            return serve(args.config, args.host, args.port, not args.no_open)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 2
