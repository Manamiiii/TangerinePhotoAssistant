from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 26
SUPPORTED_SCHEMA_VERSIONS = frozenset(range(1, SCHEMA_VERSION + 1))


def read_schema_version(path: Path) -> int | None:
    """Read a catalog version without creating or mutating the database."""
    if not path.is_file():
        return None
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_info'"
        ).fetchone()
        if table is None:
            return None
        row = connection.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
        return int(row[0]) if row is not None else None
    finally:
        connection.close()


def _schema_backup_directory(path: Path) -> Path:
    if path.parent.name.casefold() == "analysisdatabase":
        return path.parent.parent / "Backups" / "AnalysisDatabase"
    return path.parent / "SchemaBackups"


def backup_before_schema_upgrade(path: Path, from_version: int) -> Path:
    """Create and verify a consistent SQLite backup before an in-place upgrade."""
    backup_directory = _schema_backup_directory(path)
    backup_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    target = backup_directory / (
        f"{path.stem}-pre-schema{SCHEMA_VERSION}-from{from_version}-{timestamp}{path.suffix}"
    )
    source = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
        destination.commit()
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Schema upgrade backup failed SQLite integrity verification")
        backed_up_version = destination.execute(
            "SELECT version FROM schema_info LIMIT 1"
        ).fetchone()[0]
        if int(backed_up_version) != from_version:
            raise RuntimeError("Schema upgrade backup has an unexpected catalog version")
    except Exception:
        destination.close()
        source.close()
        target.unlink(missing_ok=True)
        raise
    else:
        destination.close()
        source.close()
    return target


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_version = read_schema_version(path)
    if path.is_file() and path.stat().st_size > 0 and existing_version is None:
        raise RuntimeError("Existing database is missing a readable schema_info version")
    if existing_version is not None and existing_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise RuntimeError(
            f"Unsupported database schema {existing_version}; expected {SCHEMA_VERSION}"
        )
    if existing_version is not None and existing_version < SCHEMA_VERSION:
        backup_before_schema_upgrade(path, existing_version)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_info (
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            root_path TEXT NOT NULL,
            status TEXT NOT NULL,
            files_seen INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS scan_errors (
            id INTEGER PRIMARY KEY,
            scan_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
            path TEXT NOT NULL,
            error_type TEXT NOT NULL,
            message TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            relative_path TEXT NOT NULL,
            parent_relative TEXT NOT NULL,
            file_name TEXT NOT NULL,
            stem TEXT NOT NULL,
            extension TEXT NOT NULL,
            media_kind TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            first_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
            last_seen_run_id INTEGER NOT NULL REFERENCES scan_runs(id),
            present INTEGER NOT NULL DEFAULT 1,
            metadata_status TEXT NOT NULL DEFAULT 'pending',
            metadata_error TEXT,
            exif_json TEXT,
            captured_at TEXT,
            camera_make TEXT,
            camera_model TEXT,
            lens_model TEXT,
            exposure_time REAL,
            f_number REAL,
            iso INTEGER,
            focal_length_mm REAL,
            focal_length_35mm REAL,
            exposure_compensation REAL,
            width INTEGER,
            height INTEGER,
            gps_latitude REAL,
            gps_longitude REAL,
            metadata_profile_version INTEGER NOT NULL DEFAULT 0,
            metadata_refreshed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_files_present ON files(present);
        CREATE INDEX IF NOT EXISTS idx_files_pairing
            ON files(parent_relative, stem, extension) WHERE present = 1;
        CREATE INDEX IF NOT EXISTS idx_files_captured_at ON files(captured_at);
        CREATE INDEX IF NOT EXISTS idx_files_first_seen_present
            ON files(first_seen_run_id, present);
        CREATE INDEX IF NOT EXISTS idx_files_present_size
            ON files(present, size_bytes);
        CREATE INDEX IF NOT EXISTS idx_files_present_media
            ON files(present, media_kind, size_bytes);
        CREATE INDEX IF NOT EXISTS idx_files_present_extension
            ON files(present, extension, size_bytes);
        CREATE INDEX IF NOT EXISTS idx_files_present_metadata
            ON files(present, metadata_status);
        CREATE INDEX IF NOT EXISTS idx_files_present_camera
            ON files(present, camera_model, camera_make);
        CREATE INDEX IF NOT EXISTS idx_files_present_lens
            ON files(present, lens_model);
        CREATE INDEX IF NOT EXISTS idx_files_present_relative_size
            ON files(present, relative_path, size_bytes);

        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY,
            capture_key TEXT NOT NULL UNIQUE,
            parent_relative TEXT NOT NULL,
            stem TEXT NOT NULL,
            captured_at TEXT,
            pairing_status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS capture_files (
            capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            PRIMARY KEY (capture_id, file_id)
        );

        CREATE INDEX IF NOT EXISTS idx_capture_files_capture_role_file
            ON capture_files(capture_id, role, file_id);

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            proposed_name TEXT NOT NULL,
            category TEXT NOT NULL,
            date_label TEXT,
            start_at TEXT,
            end_at TEXT,
            capture_count INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed',
            confidence REAL NOT NULL,
            reason_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_status_start
            ON events(status, start_at);

        CREATE TABLE IF NOT EXISTS album_types (
            name TEXT PRIMARY KEY,
            sort_order INTEGER NOT NULL DEFAULT 100,
            built_in INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS event_sources (
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            parent_relative TEXT NOT NULL,
            PRIMARY KEY (event_id, parent_relative)
        );

        CREATE TABLE IF NOT EXISTS event_captures (
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            sequence_index INTEGER NOT NULL,
            PRIMARY KEY (event_id, capture_id)
        );

        CREATE INDEX IF NOT EXISTS idx_event_captures_capture
            ON event_captures(capture_id);

        CREATE TABLE IF NOT EXISTS event_equipment (
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            equipment_kind TEXT NOT NULL,
            equipment_key TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            note TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (event_id, equipment_kind, equipment_key)
        );

        CREATE INDEX IF NOT EXISTS idx_event_equipment_kind_key
            ON event_equipment(equipment_kind, equipment_key, event_id);

        CREATE TABLE IF NOT EXISTS bursts (
            id INTEGER PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            burst_key TEXT NOT NULL UNIQUE,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            capture_count INTEGER NOT NULL,
            camera_model TEXT,
            grouping_method TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate'
        );

        CREATE INDEX IF NOT EXISTS idx_bursts_event_start
            ON bursts(event_id, start_at);

        CREATE TABLE IF NOT EXISTS burst_captures (
            burst_id INTEGER NOT NULL REFERENCES bursts(id) ON DELETE CASCADE,
            capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            sequence_index INTEGER NOT NULL,
            offset_ms INTEGER NOT NULL,
            PRIMARY KEY (burst_id, capture_id)
        );

        CREATE INDEX IF NOT EXISTS idx_burst_captures_capture
            ON burst_captures(capture_id);

        CREATE INDEX IF NOT EXISTS idx_captures_captured_at
            ON captures(captured_at);

        CREATE TABLE IF NOT EXISTS file_hashes (
            file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
            algorithm TEXT NOT NULL,
            digest TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            computed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_file_hashes_digest
            ON file_hashes(algorithm, digest, size_bytes);

        CREATE TABLE IF NOT EXISTS duplicate_groups (
            id INTEGER PRIMARY KEY,
            group_key TEXT NOT NULL UNIQUE,
            algorithm TEXT NOT NULL,
            digest TEXT NOT NULL,
            file_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'review'
        );

        CREATE TABLE IF NOT EXISTS duplicate_group_files (
            group_id INTEGER NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            PRIMARY KEY (group_id, file_id)
        );

        CREATE INDEX IF NOT EXISTS idx_duplicate_group_files_file
            ON duplicate_group_files(file_id);

        CREATE TABLE IF NOT EXISTS visual_fingerprints (
            capture_id INTEGER PRIMARY KEY REFERENCES captures(id) ON DELETE CASCADE,
            source_file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            dhash64 TEXT,
            mean_r INTEGER,
            mean_g INTEGER,
            mean_b INTEGER,
            width INTEGER,
            height INTEGER,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            computed_at TEXT NOT NULL,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_visual_fingerprints_source
            ON visual_fingerprints(source_file_id);

        CREATE TABLE IF NOT EXISTS similarity_groups (
            id INTEGER PRIMARY KEY,
            burst_id INTEGER NOT NULL REFERENCES bursts(id) ON DELETE CASCADE,
            group_key TEXT NOT NULL UNIQUE,
            capture_count INTEGER NOT NULL,
            max_adjacent_hamming INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate'
        );

        CREATE INDEX IF NOT EXISTS idx_similarity_groups_burst_count
            ON similarity_groups(burst_id, capture_count);
        CREATE INDEX IF NOT EXISTS idx_similarity_groups_capture_count
            ON similarity_groups(capture_count DESC, id);

        CREATE TABLE IF NOT EXISTS similarity_group_captures (
            group_id INTEGER NOT NULL REFERENCES similarity_groups(id) ON DELETE CASCADE,
            capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            sequence_index INTEGER NOT NULL,
            distance_from_previous INTEGER,
            PRIMARY KEY (group_id, capture_id)
        );

        CREATE INDEX IF NOT EXISTS idx_similarity_group_captures_capture
            ON similarity_group_captures(capture_id);

        CREATE TABLE IF NOT EXISTS similarity_group_overrides (
            capture_id INTEGER PRIMARY KEY REFERENCES captures(id) ON DELETE CASCADE,
            action TEXT NOT NULL CHECK(action IN ('exclude', 'split_before')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS similarity_group_revisions (
            id INTEGER PRIMARY KEY,
            operation TEXT NOT NULL,
            capture_ids_json TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS similarity_group_revision_captures (
            revision_id INTEGER NOT NULL REFERENCES similarity_group_revisions(id) ON DELETE CASCADE,
            capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            PRIMARY KEY (revision_id, capture_id)
        );

        CREATE INDEX IF NOT EXISTS idx_similarity_group_revision_captures_capture
            ON similarity_group_revision_captures(capture_id, revision_id DESC);

        CREATE TABLE IF NOT EXISTS quality_metrics (
            capture_id INTEGER PRIMARY KEY REFERENCES captures(id) ON DELETE CASCADE,
            source_file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            algorithm_version TEXT NOT NULL,
            luminance_mean REAL,
            shadow_clip_pct REAL,
            highlight_clip_pct REAL,
            edge_strength REAL,
            exposure_score REAL,
            sharpness_score REAL,
            exif_score REAL,
            technical_score REAL,
            issue_json TEXT NOT NULL,
            histogram_json TEXT,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            computed_at TEXT NOT NULL,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_quality_metrics_score
            ON quality_metrics(technical_score, capture_id);

        CREATE TABLE IF NOT EXISTS capture_reviews (
            capture_id INTEGER PRIMARY KEY REFERENCES captures(id) ON DELETE CASCADE,
            auto_rating INTEGER,
            auto_pick INTEGER NOT NULL DEFAULT 0,
            similarity_rank INTEGER,
            user_rating INTEGER,
            user_pick INTEGER,
            user_reject INTEGER NOT NULL DEFAULT 0,
            user_note TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_capture_reviews_auto_pick
            ON capture_reviews(auto_pick, auto_rating);

        CREATE TABLE IF NOT EXISTS selection_sessions (
            id INTEGER PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES similarity_groups(id) ON DELETE CASCADE,
            started_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL,
            completed_at TEXT,
            active_seconds REAL NOT NULL DEFAULT 0,
            decision_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active', 'completed', 'abandoned'))
        );

        CREATE INDEX IF NOT EXISTS idx_selection_sessions_group_status
            ON selection_sessions(group_id, status, id DESC);

        CREATE TABLE IF NOT EXISTS tag_definitions (
            id INTEGER PRIMARY KEY,
            dimension TEXT NOT NULL CHECK(dimension IN ('subject', 'status', 'problem', 'location')),
            name TEXT NOT NULL COLLATE NOCASE,
            built_in INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 100,
            created_at TEXT NOT NULL,
            UNIQUE(dimension, name)
        );

        CREATE INDEX IF NOT EXISTS idx_tag_definitions_dimension_order
            ON tag_definitions(dimension, sort_order, name);

        CREATE TABLE IF NOT EXISTS capture_tags (
            capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            tag_id INTEGER NOT NULL REFERENCES tag_definitions(id) ON DELETE CASCADE,
            source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual', 'analysis', 'import')),
            confidence REAL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (capture_id, tag_id, source)
        );

        CREATE INDEX IF NOT EXISTS idx_capture_tags_tag_capture
            ON capture_tags(tag_id, capture_id);
        CREATE INDEX IF NOT EXISTS idx_capture_tags_capture_source
            ON capture_tags(capture_id, source);

        CREATE TABLE IF NOT EXISTS ai_runs (
            id INTEGER PRIMARY KEY,
            mode TEXT NOT NULL,
            model_id TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            status TEXT NOT NULL,
            requested_count INTEGER NOT NULL,
            completed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            worker_pid INTEGER,
            heartbeat_at TEXT,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ai_runs_status_started
            ON ai_runs(status, started_at);

        CREATE TABLE IF NOT EXISTS ai_run_backups (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            integrity_status TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ai_run_backups_run_created
            ON ai_run_backups(run_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS ai_analyses (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES ai_runs(id) ON DELETE CASCADE,
            capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            model_id TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            priority INTEGER NOT NULL DEFAULT 0,
            selection_reason TEXT NOT NULL,
            result_json TEXT,
            raw_response TEXT,
            error TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            user_verdict TEXT,
            user_note TEXT,
            reviewed_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            UNIQUE(run_id, capture_id)
        );

        CREATE INDEX IF NOT EXISTS idx_ai_analyses_run_status_priority
            ON ai_analyses(run_id, status, priority DESC, id);
        CREATE INDEX IF NOT EXISTS idx_ai_analyses_capture_finished
            ON ai_analyses(capture_id, finished_at);
        CREATE INDEX IF NOT EXISTS idx_ai_analyses_capture_model_prompt_status
            ON ai_analyses(capture_id, model_id, prompt_version, status);

        CREATE TABLE IF NOT EXISTS edit_recipe_revisions (
            id INTEGER PRIMARY KEY,
            capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            source_analysis_id INTEGER REFERENCES ai_analyses(id) ON DELETE SET NULL,
            parameter_space TEXT NOT NULL DEFAULT 'tangerine-preview-v1',
            parameters_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft', 'accepted', 'dismissed')),
            note TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_edit_recipe_revisions_capture
            ON edit_recipe_revisions(capture_id, id DESC);

        CREATE TABLE IF NOT EXISTS archive_baselines (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            scan_run_id INTEGER REFERENCES scan_runs(id),
            file_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            note TEXT,
            scope TEXT NOT NULL DEFAULT 'archive'
        );

        CREATE TABLE IF NOT EXISTS archive_baseline_files (
            baseline_id INTEGER NOT NULL REFERENCES archive_baselines(id) ON DELETE CASCADE,
            relative_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            sha256 TEXT,
            PRIMARY KEY (baseline_id, relative_path)
        );

        CREATE INDEX IF NOT EXISTS idx_archive_baseline_files_path
            ON archive_baseline_files(relative_path, baseline_id);

        CREATE TABLE IF NOT EXISTS archive_checks (
            id INTEGER PRIMARY KEY,
            baseline_id INTEGER NOT NULL REFERENCES archive_baselines(id) ON DELETE CASCADE,
            scan_run_id INTEGER REFERENCES scan_runs(id),
            checked_at TEXT NOT NULL,
            missing_count INTEGER NOT NULL,
            changed_count INTEGER NOT NULL,
            new_count INTEGER NOT NULL,
            healthy INTEGER NOT NULL,
            sample_json TEXT NOT NULL,
            UNIQUE(baseline_id, scan_run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_archive_checks_baseline_scan
            ON archive_checks(baseline_id, scan_run_id);

        CREATE TABLE IF NOT EXISTS migration_plans (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            source_root TEXT NOT NULL,
            target_root TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'review',
            item_count INTEGER NOT NULL,
            total_bytes INTEGER NOT NULL,
            excluded_count INTEGER NOT NULL,
            excluded_bytes INTEGER NOT NULL,
            conflict_count INTEGER NOT NULL,
            unassigned_count INTEGER NOT NULL,
            available_bytes INTEGER NOT NULL,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS migration_items (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER NOT NULL REFERENCES migration_plans(id) ON DELETE CASCADE,
            file_id INTEGER REFERENCES files(id),
            event_id INTEGER REFERENCES events(id),
            source_relative TEXT NOT NULL,
            target_relative TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            source_sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            reason TEXT NOT NULL,
            UNIQUE(plan_id, source_relative)
        );

        CREATE TABLE IF NOT EXISTS migration_runs (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER NOT NULL REFERENCES migration_plans(id),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'prepared',
            copied_count INTEGER NOT NULL DEFAULT 0,
            verified_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            copied_bytes INTEGER NOT NULL DEFAULT 0,
            total_bytes INTEGER NOT NULL,
            speed_bytes_per_second REAL,
            eta_seconds REAL,
            audit_status TEXT NOT NULL DEFAULT 'pending',
            audit_started_at TEXT,
            audit_finished_at TEXT,
            confirmation TEXT NOT NULL,
            batch_max_files INTEGER,
            batch_max_bytes INTEGER,
            batch_max_seconds INTEGER,
            completed_batches INTEGER NOT NULL DEFAULT 0,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_migration_runs_plan_status
            ON migration_runs(plan_id, status, id);

        CREATE TABLE IF NOT EXISTS migration_failures (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES migration_runs(id) ON DELETE CASCADE,
            item_id INTEGER REFERENCES migration_items(id),
            occurred_at TEXT NOT NULL,
            stage TEXT NOT NULL,
            error_code TEXT NOT NULL,
            message TEXT NOT NULL,
            source_relative TEXT,
            target_relative TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_migration_failures_run
            ON migration_failures(run_id, id);

        CREATE TABLE IF NOT EXISTS library_state (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            archive_root TEXT NOT NULL,
            active_root TEXT NOT NULL,
            switched_at TEXT,
            migration_run_id INTEGER REFERENCES migration_runs(id),
            status TEXT NOT NULL DEFAULT 'archive'
        );

        CREATE INDEX IF NOT EXISTS idx_migration_items_plan_status
            ON migration_items(plan_id, status, id);
        CREATE INDEX IF NOT EXISTS idx_migration_items_plan_target
            ON migration_items(plan_id, target_relative);
        """
    )
    _ensure_column(connection, "archive_baselines", "root_path", "TEXT")
    _ensure_column(
        connection, "archive_baselines", "scope", "TEXT NOT NULL DEFAULT 'archive'"
    )
    _ensure_column(connection, "migration_items", "run_id", "INTEGER")
    _ensure_column(connection, "migration_items", "copied_bytes", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(connection, "migration_items", "target_sha256", "TEXT")
    _ensure_column(connection, "migration_items", "verified_at", "TEXT")
    _ensure_column(connection, "migration_items", "last_error", "TEXT")
    _ensure_column(connection, "migration_runs", "batch_max_files", "INTEGER")
    _ensure_column(connection, "migration_runs", "batch_max_bytes", "INTEGER")
    _ensure_column(connection, "migration_runs", "batch_max_seconds", "INTEGER")
    _ensure_column(
        connection, "migration_runs", "completed_batches", "INTEGER NOT NULL DEFAULT 0"
    )
    _ensure_column(
        connection, "ai_analyses", "attempt_count", "INTEGER NOT NULL DEFAULT 0"
    )
    _ensure_column(connection, "ai_analyses", "user_verdict", "TEXT")
    _ensure_column(connection, "ai_analyses", "user_note", "TEXT")
    _ensure_column(connection, "ai_analyses", "reviewed_at", "TEXT")
    _ensure_column(connection, "ai_runs", "worker_pid", "INTEGER")
    _ensure_column(connection, "ai_runs", "heartbeat_at", "TEXT")
    _ensure_column(connection, "similarity_group_overrides", "manual_batch_key", "TEXT")
    _ensure_column(connection, "similarity_group_overrides", "manual_group_key", "TEXT")
    _ensure_column(connection, "quality_metrics", "histogram_json", "TEXT")
    _ensure_column(
        connection, "files", "metadata_profile_version", "INTEGER NOT NULL DEFAULT 0"
    )
    _ensure_column(connection, "files", "metadata_refreshed_at", "TEXT")
    _ensure_column(connection, "capture_reviews", "selection_reason_json", "TEXT")
    _ensure_column(
        connection, "tag_definitions", "active", "INTEGER NOT NULL DEFAULT 1"
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_similarity_group_overrides_batch
           ON similarity_group_overrides(manual_batch_key)"""
    )
    connection.executemany(
        """INSERT OR IGNORE INTO album_types(name, sort_order, built_in, created_at)
           VALUES (?, ?, 1, CURRENT_TIMESTAMP)""",
        (
            ("旅行", 10), ("纪念", 20), ("家人", 30), ("宠物", 40),
            ("回家", 50), ("专题", 60), ("日常", 70),
        ),
    )
    tag_presets = {
        "subject": (
            "人像", "风景", "宠物", "星空", "建筑", "美食", "旅行", "纪实", "其他",
        ),
        "status": (
            "未评估", "待复核", "待修", "修图中", "已修", "待导出", "已导出", "已归档",
        ),
        "problem": (
            "闭眼", "失焦", "抖动", "表情", "姿势", "遮挡", "曝光", "构图",
            "背景干扰", "近似次优", "噪点", "高光溢出", "阴影死黑", "白平衡",
        ),
    }
    connection.executemany(
        """INSERT OR IGNORE INTO tag_definitions(
               dimension, name, built_in, sort_order, created_at
           ) VALUES (?, ?, 1, ?, CURRENT_TIMESTAMP)""",
        (
            (dimension, name, index * 10)
            for dimension, names in tag_presets.items()
            for index, name in enumerate(names, start=1)
        ),
    )
    connection.execute(
        """UPDATE tag_definitions SET active=0
           WHERE dimension='status' AND built_in=1 AND name IN ('精选', '待淘汰')"""
    )
    row = connection.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
    if row is None:
        connection.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(row["version"]) < SCHEMA_VERSION:
        connection.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))
    elif row["version"] != SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported database schema {row['version']}; expected {SCHEMA_VERSION}"
        )
    connection.commit()
    return connection


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Database does not exist: {path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[None]:
    try:
        connection.execute("BEGIN")
        yield
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
