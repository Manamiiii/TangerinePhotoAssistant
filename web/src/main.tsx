import { StrictMode, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type View = "home" | "library" | "bursts" | "analysis" | "statistics" | "equipment" | "lightroom" | "archive" | "migration";
type LibrarySection = "photos" | "albums";
type Theme = "light" | "dark";
type CountRow = { count: number } & Record<string, string | number | null>;

type StructureSummary = {
  event_count: number;
  categories: Array<{ category: string; event_count: number; capture_count: number }>;
  burst_count: number;
  captures_in_bursts: number;
  largest_burst: number;
};

type Overview = {
  generated_at: string;
  files: { count: number; size_bytes: number };
  by_media_kind: CountRow[];
  pairing: Array<{ pairing_status: string; count: number }>;
  metadata: Array<{ metadata_status: string; count: number }>;
  cameras: Array<{ camera_make: string; camera_model: string; count: number }>;
  lenses: Array<{ lens_model: string; count: number }>;
  capture_total: number;
  dated_captures: number;
  structure: StructureSummary;
  visual: {
    duplicate_group_count: number;
    duplicate_file_count: number;
    duplicate_total_bytes: number;
    similarity_group_count: number;
    captures_in_similarity_groups: number;
    largest_similarity_group: number;
    fingerprint_count: number;
    fingerprint_error_count: number;
  };
  latest_scan: {
    id: number;
    started_at: string;
    finished_at: string | null;
    status: string;
    files_seen: number;
  } | null;
};

type InboxItem = {
  id: number;
  parent_relative: string;
  stem: string;
  captured_at: string | null;
  pairing_status: string;
  camera_model: string | null;
  lens_model: string | null;
  file_count: number;
};
type Inbox = { scan_run_id: number | null; count: number; items: InboxItem[] };

type LibraryCapture = {
  id: number;
  stem: string;
  captured_at: string | null;
  pairing_status: string;
  camera_model: string | null;
  lens_model: string | null;
  album_id: number | null;
  album_name: string | null;
  category: string | null;
  user_rating: number | null;
  user_pick: number | null;
  user_reject: number | null;
  thumbnail_url: string;
};
type LibraryCapturesResponse = { count: number; limit: number; offset: number; items: LibraryCapture[] };
type LibraryFilters = {
  albums: Array<{ id: number; name: string; category: string; capture_count: number; status: string }>;
  album_types: Array<{ name: string; built_in: number }>;
  cameras: string[];
  lenses: string[];
};
type LibraryQuery = {
  pageSize: number;
  albumId: string;
  category: string;
  camera: string;
  lens: string;
  rating: string;
  selection: string;
  dateFrom: string;
  dateTo: string;
  search: string;
  sort: string;
};
type PhoneShareExport = {
  filename: string;
  photo_count: number;
  size_bytes: number;
  max_edge: number;
  quality: number;
  metadata_removed: boolean;
  download_url: string;
};

type EventItem = {
  id: number;
  proposed_name: string;
  category: string;
  date_label: string | null;
  start_at: string | null;
  end_at: string | null;
  capture_count: number;
  status: string;
  confidence: number;
  source_count: number;
  burst_count: number;
  largest_burst: number;
  sources: string[];
  reason: { method: string; legacy_buckets: string[] };
};
type EventsResponse = { count: number; limit: number; offset: number; items: EventItem[] };

type BurstItem = {
  id: number;
  start_at: string;
  end_at: string;
  capture_count: number;
  camera_model: string | null;
  event_id: number;
  event_name: string;
  category: string;
  first_stem: string;
  last_stem: string;
  similarity_group_count: number;
  largest_similarity_group: number;
};
type BurstsResponse = { count: number; limit: number; offset: number; items: BurstItem[] };

type SimilarityGroupItem = {
  id: number;
  capture_count: number;
  max_adjacent_hamming: number;
  start_at: string;
  end_at: string;
  event_id: number;
  event_name: string;
  category: string;
  average_score: number | null;
  recommended_capture_id: number | null;
  recommended_stem: string | null;
  cover_capture_id: number;
  thumbnail_url: string;
};
type SimilarityGroupsResponse = { count: number; limit: number; offset: number; items: SimilarityGroupItem[] };

type GroupCapture = {
  capture_id: number;
  stem: string;
  captured_at: string | null;
  sequence_index: number;
  distance_from_previous: number | null;
  technical_score: number | null;
  exposure_score: number | null;
  sharpness_score: number | null;
  exif_score: number | null;
  auto_rating: number | null;
  auto_pick: number;
  similarity_rank: number | null;
  user_rating: number | null;
  user_pick: number | null;
  user_reject: number;
  user_note: string | null;
  exposure_time: number | null;
  f_number: number | null;
  iso: number | null;
  focal_length_mm: number | null;
  camera_model: string | null;
  lens_model: string | null;
  issues: Array<{ code: string; severity: string; message: string }>;
  thumbnail_url: string;
};
type SimilarityGroupDetail = {
  id: number;
  capture_count: number;
  max_adjacent_hamming: number;
  start_at: string;
  end_at: string;
  event_name: string;
  category: string;
  items: GroupCapture[];
};

type CaptureDetail = {
  id: number;
  stem: string;
  parent_relative: string;
  captured_at: string | null;
  pairing_status: string;
  event_name: string | null;
  category: string | null;
  technical_score: number | null;
  exposure_score: number | null;
  sharpness_score: number | null;
  exif_score: number | null;
  auto_rating: number | null;
  user_rating: number | null;
  issues: Array<{ code: string; severity: string; message: string; evidence?: Record<string, unknown> }>;
  files: Array<{
    file_name: string;
    role: string;
    size_bytes: number;
    camera_model: string | null;
    lens_model: string | null;
    exposure_time: number | null;
    f_number: number | null;
    iso: number | null;
    focal_length_mm: number | null;
    focal_length_35mm: number | null;
    exposure_compensation: number | null;
    width: number | null;
    height: number | null;
  }>;
  ai_analyses: Array<{
    id: number;
    model_id: string;
    prompt_version: string;
    finished_at: string;
    result: Record<string, unknown>;
    user_verdict: "accurate" | "partial" | "inaccurate" | null;
    user_note: string | null;
    reviewed_at: string | null;
  }>;
  thumbnail_url: string;
};

type AiRun = {
  id: number;
  mode: string;
  model_id: string;
  prompt_version: string;
  status: string;
  requested_count: number;
  completed_count: number;
  failed_count: number;
  processed_count: number;
  success_rate: number | null;
  average_seconds_per_photo: number | null;
  throughput_per_hour: number | null;
  estimated_remaining_seconds: number | null;
  total_attempts: number;
  max_attempts: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  report_available?: boolean;
  backup_count?: number;
  latest_backup_at?: string | null;
};

type AiFailure = {
  id: number;
  capture_id: number;
  stem: string;
  status: string;
  selection_reason: string;
  attempt_count: number;
  error: string | null;
};

type AiResultAudit = {
  prompt_version: string;
  last_analysis_id: number;
  result_count: number;
  parse_errors: number;
  schema_errors: number;
  unsafe_action_mentions: number;
  with_visible_problems: number;
  with_shooting_advice: number;
  with_lightroom_suggestions: number;
  photoshop_needed: number;
  empty_photoshop_reason: number;
  overconfident: number;
  reviewed: number;
  timed_count: number;
  verdicts: { accurate: number; partial: number; inaccurate: number };
  average_confidence: number | null;
  average_seconds_per_photo: number | null;
};

type AiRecentResult = {
  id: number;
  capture_id: number;
  model_id: string;
  prompt_version: string;
  finished_at: string;
  user_verdict: "accurate" | "partial" | "inaccurate" | null;
  stem: string;
  event_name: string | null;
  category: string | null;
  technical_score: number | null;
  subject_type: string | null;
  quality_summary: string | null;
  visible_problem_count: number;
  overall_confidence: number | null;
  photoshop_needed: boolean;
  thumbnail_url: string;
  review_flags?: string[];
};

type AiResultsResponse = {
  count: number;
  limit: number;
  offset: number;
  items: AiRecentResult[];
};

type AiPreflight = {
  ready: boolean;
  blockers: string[];
  warnings: string[];
  model_path: string | null;
  model_file_count: number;
  model_bytes: number;
  quantization: string;
  gpu_memory_limit_gb: number;
  image_max_edge?: number;
  database_bytes: number;
  backup_root: string;
  backup_free_bytes: number;
  competing_processes: string[];
};

type GpuStatus = {
  available: boolean;
  name?: string;
  utilization_percent?: number;
  memory_used_mb?: number;
  memory_total_mb?: number;
  temperature_c?: number;
  message?: string;
};

type AnalysisOverview = {
  quality: {
    analyzed: number;
    errors: number;
    average_score: number | null;
    flagged: number;
    recommended_picks: number;
    ratings: Array<{ rating: number; count: number }>;
  };
  ai: {
    completed_analysis_count: number;
    analyzed_capture_count: number;
    latest_run: AiRun | null;
    recent_runs: AiRun[];
    latest_failures: AiFailure[];
    result_audit: { versions: AiResultAudit[]; latest: AiResultAudit | null };
    recent_results: AiRecentResult[];
    candidates: { benchmark_available: number; recommended_available: number } | null;
  };
  runtime: { ready: boolean; message: string };
};

type QualityItem = {
  capture_id: number;
  stem: string;
  captured_at: string | null;
  event_name: string;
  category: string;
  technical_score: number;
  exposure_score: number;
  sharpness_score: number;
  exif_score: number;
  auto_rating: number | null;
  auto_pick: number;
  similarity_rank: number | null;
  user_rating: number | null;
  user_pick: number | null;
  user_reject: number;
  user_note: string | null;
  issues: Array<{ code: string; severity: string; message: string }>;
  ai_result: {
    subject_type?: string;
    quality_summary?: string;
    photoshop_needed?: boolean;
  } | null;
};
type QualityResponse = { count: number; limit: number; offset: number; items: QualityItem[] };
type ReviewPayload = {
  user_rating: number | null;
  user_pick: boolean;
  user_reject: boolean;
  user_note: string | null;
};

type StatisticRow = { count: number; average_score: number | null } & Record<string, string | number | null>;
type Statistics = {
  summary: {
    capture_count: number;
    first_capture: string | null;
    last_capture: string | null;
    quality_analyzed: number;
    average_technical_score: number | null;
    user_picks: number;
    user_rejects: number;
  };
  categories: StatisticRow[];
  months: Array<StatisticRow & { month: string; user_picks: number }>;
  lenses: Array<StatisticRow & { lens_model: string }>;
  focal_ranges: Array<StatisticRow & { bucket: string }>;
  iso_ranges: Array<StatisticRow & { bucket: string }>;
  aperture_ranges: Array<StatisticRow & { bucket: string }>;
  ratings: Array<{ rating: number; count: number; user_rated: number }>;
  issues: Array<{ code: string; message: string; count: number }>;
};

type EquipmentItem = {
  brand?: string;
  model?: string;
  display_name?: string;
  kind?: string;
  section?: string;
  filter_thread_mm?: number;
  thread_mm?: number;
  system_mm?: number;
  lens_thread_mm?: number;
  stops?: number;
  capture_count?: number;
  status: string;
};
type EquipmentCatalog = {
  schema_version: number;
  profile_file: string;
  summary: {
    camera_count: number;
    lens_count: number;
    accessory_count: number;
    detected_camera_count: number;
    detected_lens_count: number;
  };
  cameras: EquipmentItem[];
  lenses: EquipmentItem[];
  accessories: EquipmentItem[];
  detected: {
    cameras: Array<{ model: string; capture_count: number }>;
    lenses: Array<{ model: string; capture_count: number }>;
  };
  filter_system: { compatibility?: string; infer_usage_from_thread_size?: boolean };
};

type ArchiveStatus = {
  baseline: {
    id: number;
    name: string;
    created_at: string;
    file_count: number;
    total_bytes: number;
  } | null;
  comparison: {
    missing: number;
    changed: number;
    new: number;
    healthy: boolean;
    samples: Array<{ relative_path: string; status: string }>;
  } | null;
};

type LightroomStatus = {
  capture_count: number;
  confirmed_events: number;
  event_count: number;
  rated_captures: number;
  user_picks: number;
  user_rejects: number;
};

type LightroomManifest = {
  capture_count: number;
  rated_count: number;
  user_pick_count: number;
  user_reject_count: number;
  source_bytes: number;
  csv_url: string;
  json_url: string;
};

type MigrationStatus = {
  plan: {
    id: number;
    created_at: string;
    source_root: string;
    target_root: string;
    status: string;
    item_count: number;
    total_bytes: number;
    excluded_count: number;
    excluded_bytes: number;
    conflict_count: number;
    unassigned_count: number;
    available_bytes: number;
    ready: boolean;
    csv_url: string;
    json_url: string;
    sample_conflicts: Array<{ source_relative: string; target_relative: string; reason: string }>;
    sample_unassigned: Array<{ source_relative: string; target_relative: string; reason: string }>;
    confirmation_phrase: string;
    switch_confirmation_phrase: string;
    failure_csv_url?: string;
    failure_json_url?: string;
    failures: Array<{ stage: string; error_code: string; message: string; source_relative: string; target_relative: string }>;
    run: {
      id: number;
      status: string;
      copied_count: number;
      verified_count: number;
      failed_count: number;
      copied_bytes: number;
      total_bytes: number;
      speed_bytes_per_second: number | null;
      eta_seconds: number | null;
      audit_status: string;
      batch_max_files: number | null;
      batch_max_bytes: number | null;
      batch_max_seconds: number | null;
      completed_batches: number;
    } | null;
  } | null;
};

type Task = {
  id: string | null;
  status: "idle" | "running" | "paused" | "complete" | "failed" | "cancelled";
  stage: string;
  message: string;
  current: number;
  total: number | null;
  error: string | null;
  bytes_current: number;
  bytes_total: number | null;
  speed_bytes_per_second: number | null;
  items_per_second: number | null;
  eta_seconds: number | null;
  failure_count: number;
  pausable: boolean;
};

const numberFormat = new Intl.NumberFormat("zh-CN");
const dateFormat = new Intl.DateTimeFormat("zh-CN", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function formatBytes(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function formatFileSize(bytes: number) {
  return bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(2)} GB`
    : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function formatDuration(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds)) return "计算中";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.ceil((seconds % 3600) / 60);
  return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分钟`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "尚未完成";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value.replace("T", " ") : dateFormat.format(parsed);
}

function formatExposure(value: number | null | undefined) {
  if (!value) return "—";
  return value < 1 ? `1/${Math.round(1 / value)}s` : `${value.toFixed(1)}s`;
}

function pairingLabel(status: string) {
  const labels: Record<string, string> = {
    paired: "JPG + RAW",
    jpeg_only: "仅 JPG",
    raw_only: "仅 RAW",
    paired_duplicate_role: "配对待检查",
  };
  return labels[status] ?? status;
}

function technicalGrade(score: number | null | undefined) {
  if (score == null) return "—";
  if (score >= 85) return "A+";
  if (score >= 75) return "A";
  if (score >= 60) return "B";
  if (score >= 45) return "C";
  return "D";
}

async function getJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

function Pagination({ count, limit, offset, onChange, onLimitChange }: {
  count: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(count / limit));
  const currentPage = Math.min(pageCount, Math.floor(offset / limit) + 1);
  const goToPage = (page: number) => onChange((Math.max(1, Math.min(pageCount, page)) - 1) * limit);
  return <div className="pagination-controls" aria-label="分页">
    <label>每页<select value={limit} onChange={(event) => onLimitChange(Number(event.target.value))}>
      {[20, 40, 80, 120, 200].map((size) => <option key={size} value={size}>{size}</option>)}
    </select></label>
    <div className="pagination-buttons">
      <button disabled={currentPage === 1} onClick={() => goToPage(1)} aria-label="第一页">«</button>
      <button disabled={currentPage === 1} onClick={() => goToPage(currentPage - 1)} aria-label="上一页">‹</button>
      <label>第<input type="number" min="1" max={pageCount} value={currentPage} onChange={(event) => goToPage(Number(event.target.value) || 1)} />页</label>
      <span>/ {numberFormat.format(pageCount)} 页</span>
      <button disabled={currentPage === pageCount} onClick={() => goToPage(currentPage + 1)} aria-label="下一页">›</button>
      <button disabled={currentPage === pageCount} onClick={() => goToPage(pageCount)} aria-label="最后一页">»</button>
    </div>
    <span>{count ? `${numberFormat.format(offset + 1)}–${numberFormat.format(Math.min(offset + limit, count))}` : "0"} / {numberFormat.format(count)}</span>
  </div>;
}

function TaskCard({ task, cancel, pause }: { task: Task | null; cancel?: () => void; pause?: () => void }) {
  if (!task || task.status === "idle") return null;
  const progress = task.total ? Math.min(100, (task.current / task.total) * 100) : null;
  const itemProgress = task.total
    ? `${numberFormat.format(task.current)} / ${numberFormat.format(task.total)}`
    : null;
  const itemSpeed = task.items_per_second
    ? `${(task.items_per_second * 60).toFixed(1)} 张/分钟`
    : null;
  const detail = task.error ?? (
    [
      itemProgress,
      itemSpeed,
      task.eta_seconds != null ? `预计剩余 ${formatDuration(task.eta_seconds)}` : null,
    ].filter(Boolean).join(" · ") || "所有操作都在本机完成"
  );
  return (
    <section className={`task-card ${task.status}`} aria-live="polite">
      <div>
        <span className="task-icon">
          {task.status === "complete" ? "✓" : task.status === "failed" ? "!" : "↻"}
        </span>
        <div>
          <strong>{task.message}</strong>
          <small>{detail}</small>
        </div>
      </div>
      {task.status === "running" && (
        <div className="task-actions"><div className="progress-track"><span style={{ width: `${progress ?? 22}%` }} className={progress === null ? "indeterminate" : ""} /></div>{pause && task.pausable && <button onClick={pause}>安全暂停</button>}{cancel && <button onClick={cancel}>安全取消</button>}</div>
      )}
      {task.status === "paused" && cancel && (
        <div className="task-actions"><div className="progress-track"><span style={{ width: `${progress ?? 0}%` }} /></div><button onClick={cancel}>取消剩余任务</button></div>
      )}
    </section>
  );
}

function InboxView({
  overview,
  inbox,
  task,
  startScan,
  cancelTask,
}: {
  overview: Overview | null;
  inbox: Inbox | null;
  task: Task | null;
  startScan: () => void;
  cancelTask: () => void;
}) {
  const pairing = useMemo(
    () => Object.fromEntries((overview?.pairing ?? []).map((row) => [row.pairing_status, row.count])),
    [overview],
  );
  return (
    <>
      <section className="hero-card">
        <div className="hero-copy">
          <span className="section-kicker">增量工作流</span>
          <h2>新照片放好后，<br />这里会接手其余工作。</h2>
          <p>快速核对图库，只读取新增或变化文件的拍摄信息。不会移动、删除或改写原片。</p>
          <button className="primary-action" onClick={startScan} disabled={task?.status === "running"}>
            <span>{task?.status === "running" ? "扫描进行中" : "扫描新照片"}</span>
            <b aria-hidden="true">→</b>
          </button>
        </div>
        <div className="library-number">
          <span>当前拍摄单元</span>
          <strong>{overview ? numberFormat.format(overview.capture_total) : "—"}</strong>
          <small>
            {overview
              ? `${numberFormat.format(overview.files.count)} 个文件 · ${formatBytes(overview.files.size_bytes)}`
              : "正在读取图库"}
          </small>
        </div>
        <div className="aperture-rings" aria-hidden="true"><i /><i /><i /></div>
      </section>

      <TaskCard task={task} cancel={cancelTask} />

      <section className="metric-grid" aria-label="图库概览">
        <article><span>完整配对</span><strong>{numberFormat.format(pairing.paired ?? 0)}</strong><small>JPG + RAW</small></article>
        <article><span>仅 JPG</span><strong>{numberFormat.format(pairing.jpeg_only ?? 0)}</strong><small>可能是导出或单拍</small></article>
        <article><span>仅 RAW</span><strong>{numberFormat.format(pairing.raw_only ?? 0)}</strong><small>需要复核</small></article>
        <article>
          <span>拍摄日期可用</span>
          <strong>{overview ? `${Math.round((overview.dated_captures / Math.max(overview.capture_total, 1)) * 100)}%` : "—"}</strong>
          <small>用于相册整理</small>
        </article>
      </section>

      <section className="content-grid">
        <div className="panel recent-panel">
          <div className="panel-heading">
            <div><span className="section-kicker">最近批次</span><h3>最近入库</h3></div>
            <span className="batch-count">{inbox ? `${numberFormat.format(inbox.count)} 个拍摄单元` : "读取中"}</span>
          </div>
          <div className="capture-list">
            {(inbox?.items ?? []).slice(0, 8).map((item) => (
              <article key={item.id} className="capture-row">
                <div className="file-avatar">{item.stem.slice(-2)}</div>
                <div className="capture-name"><strong>{item.stem}</strong><span title={item.parent_relative}>{item.parent_relative || "图库根目录"}</span></div>
                <div className="capture-camera"><strong>{item.camera_model ?? "未知相机"}</strong><span>{item.lens_model ?? "镜头信息不可用"}</span></div>
                <time>{item.captured_at?.slice(0, 10) ?? "日期未知"}</time>
                <span className={`pair-badge ${item.pairing_status}`}>{pairingLabel(item.pairing_status)}</span>
              </article>
            ))}
            {!inbox?.items.length && <div className="empty-state">还没有入库记录</div>}
          </div>
        </div>

        <div className="panel gear-panel">
          <div className="panel-heading"><div><span className="section-kicker">器材识别</span><h3>主要镜头</h3></div></div>
          <div className="lens-list">
            {(overview?.lenses ?? []).slice(0, 4).map((lens, index) => (
              <div className="lens-row" key={lens.lens_model}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{lens.lens_model}</strong><small>{numberFormat.format(lens.count)} 个文件记录</small></div>
              </div>
            ))}
          </div>
          <div className="next-step"><span>相册已整理</span><strong>{overview?.structure.event_count ?? 0} 个拍摄相册</strong><p>可在相册管理中调整名称、类型和照片归属。</p></div>
        </div>
      </section>
    </>
  );
}

function ModalShell({ title, close, children }: { title: string; close: () => void; children: ReactNode }) {
  return <div className="editor-backdrop" role="dialog" aria-modal="true" aria-label={title} onClick={close}>
    <section className="editor-modal" onClick={(event) => event.stopPropagation()}>
      <header><h3>{title}</h3><button onClick={close} aria-label="关闭">×</button></header>
      {children}
    </section>
  </div>;
}

function AlbumsView({ albums, filters, updateAlbum, createAlbum, createAlbumType, renameAlbumType, deleteAlbumType, openAlbum, changePage, changePageSize }: {
  albums: EventsResponse | null;
  filters: LibraryFilters | null;
  updateAlbum: (album: EventItem, changes: Partial<Pick<EventItem, "proposed_name" | "category" | "status">>) => void;
  createAlbum: (name: string, category: string) => void;
  createAlbumType: (name: string) => void;
  renameAlbumType: (name: string, nextName: string) => void;
  deleteAlbumType: (name: string) => void;
  openAlbum: (albumId: number) => void;
  changePage: (offset: number) => void;
  changePageSize: (limit: number) => void;
}) {
  const [albumEditor, setAlbumEditor] = useState<EventItem | "new" | null>(null);
  const [albumName, setAlbumName] = useState("");
  const [albumCategory, setAlbumCategory] = useState("");
  const [typeManagerOpen, setTypeManagerOpen] = useState(false);
  const [newTypeName, setNewTypeName] = useState("");
  const [editingType, setEditingType] = useState<string | null>(null);
  const [editedTypeName, setEditedTypeName] = useState("");
  const openAlbumEditor = (album: EventItem | "new") => {
    setAlbumEditor(album);
    setAlbumName(album === "new" ? "" : album.proposed_name);
    setAlbumCategory(album === "new" ? (filters?.album_types[0]?.name ?? "日常") : album.category);
  };
  const saveAlbum = () => {
    if (!albumName.trim() || !albumCategory) return;
    if (albumEditor === "new") createAlbum(albumName.trim(), albumCategory);
    else if (albumEditor) updateAlbum(albumEditor, { proposed_name: albumName.trim(), category: albumCategory });
    setAlbumEditor(null);
  };
  return (
    <>
      <section className="album-management-header">
        <div><strong>{numberFormat.format(albums?.count ?? 0)}</strong><span>个相册</span></div>
        <div className="album-management-actions"><button className="toolbar-button" onClick={() => setTypeManagerOpen(true)}>类型管理</button><button className="toolbar-button primary" onClick={() => openAlbumEditor("new")}>新建相册</button></div>
      </section>
      <section className="album-type-strip" aria-label="相册类型">
        {(filters?.album_types ?? []).map((item) => (
          <span key={item.name}>{item.name}{item.built_in ? "" : " · 自定义"}</span>
        ))}
      </section>
      <section className="panel event-panel album-panel">
        <div className="panel-heading"><div><span className="section-kicker">相册管理</span><h3>全部相册</h3></div><span className="batch-count">按最近拍摄时间排列</span></div>
        <div className="event-list">
          {(albums?.items ?? []).map((album) => (
            <article className="event-row album-row" key={album.id}>
              <div className={`category-chip category-${album.category}`}>{album.category}</div>
              <div className="event-main"><strong>{album.proposed_name}</strong><span>{album.source_count ? `${album.source_count} 个来源目录` : "手动创建"}</span></div>
              <div className="event-measure"><strong>{numberFormat.format(album.capture_count)}</strong><span>照片</span></div>
              <div className="album-date"><strong>{album.start_at?.slice(0, 10) ?? "—"}</strong><span>拍摄日期</span></div>
              <button className="album-open-action" onClick={() => openAlbum(album.id)}>查看照片</button>
              <div className="album-row-actions"><button onClick={() => openAlbumEditor(album)}>编辑</button><button className={album.status === "confirmed" ? "confirmed" : ""} disabled={album.status === "confirmed"} onClick={() => updateAlbum(album, { status: "confirmed" })}>{album.status === "confirmed" ? "已确认" : "确认"}</button></div>
            </article>
          ))}
          {!albums?.items.length && <div className="empty-state">还没有相册，可以新建一个空相册。</div>}
        </div>
      </section>
      {albums && <Pagination count={albums.count} limit={albums.limit} offset={albums.offset} onChange={changePage} onLimitChange={changePageSize} />}
      {albumEditor && <ModalShell title={albumEditor === "new" ? "新建相册" : "编辑相册"} close={() => setAlbumEditor(null)}>
        <form className="editor-form" onSubmit={(event) => { event.preventDefault(); saveAlbum(); }}>
          <label><span>相册名称</span><input autoFocus value={albumName} onChange={(event) => setAlbumName(event.target.value)} maxLength={180} /></label>
          <label><span>相册类型</span><select value={albumCategory} onChange={(event) => setAlbumCategory(event.target.value)}>{(filters?.album_types ?? []).map((type) => <option key={type.name}>{type.name}</option>)}</select></label>
          <footer><button type="button" className="toolbar-button" onClick={() => setAlbumEditor(null)}>取消</button><button className="toolbar-button primary" disabled={!albumName.trim() || !albumCategory}>保存</button></footer>
        </form>
      </ModalShell>}
      {typeManagerOpen && <ModalShell title="相册类型管理" close={() => setTypeManagerOpen(false)}>
        <div className="type-manager-list">
          {(filters?.album_types ?? []).map((type) => <div className="type-manager-row" key={type.name}>
            {editingType === type.name ? <input autoFocus value={editedTypeName} onChange={(event) => setEditedTypeName(event.target.value)} /> : <div><strong>{type.name}</strong><span>{type.built_in ? "内置类型" : "自定义类型"}</span></div>}
            <div>{!type.built_in && (editingType === type.name ? <><button onClick={() => { if (editedTypeName.trim()) renameAlbumType(type.name, editedTypeName.trim()); setEditingType(null); }}>保存</button><button onClick={() => setEditingType(null)}>取消</button></> : <><button onClick={() => { setEditingType(type.name); setEditedTypeName(type.name); }}>编辑</button><button className="danger-text" onClick={() => deleteAlbumType(type.name)}>删除</button></>)}</div>
          </div>)}
        </div>
        <form className="type-create-row" onSubmit={(event) => { event.preventDefault(); if (newTypeName.trim()) { createAlbumType(newTypeName.trim()); setNewTypeName(""); } }}><input value={newTypeName} onChange={(event) => setNewTypeName(event.target.value)} placeholder="新的类型名称" maxLength={40} /><button className="toolbar-button primary" disabled={!newTypeName.trim()}>新增类型</button></form>
      </ModalShell>}
    </>
  );
}

function BurstsView({ overview, bursts, groups, selectedGroup, task, startVisual, openGroup, closeGroup, openCapture, saveReview, cancelTask, changeGroupPage, changeGroupPageSize, changeBurstPage, changeBurstPageSize }: {
  overview: Overview | null;
  bursts: BurstsResponse | null;
  groups: SimilarityGroupsResponse | null;
  selectedGroup: SimilarityGroupDetail | null;
  task: Task | null;
  startVisual: () => void;
  openGroup: (groupId: number) => void;
  closeGroup: () => void;
  openCapture: (captureId: number) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  cancelTask: () => void;
  changeGroupPage: (offset: number) => void;
  changeGroupPageSize: (limit: number) => void;
  changeBurstPage: (offset: number) => void;
  changeBurstPageSize: (limit: number) => void;
}) {
  const summary = overview?.structure;
  const visual = overview?.visual;
  return (
    <>
      <section className="structure-hero burst-hero">
        <div><span className="section-kicker">照片挑选</span><h2>相似照片分组</h2><p>比较连拍和相似画面。</p><button className="primary-action" onClick={startVisual} disabled={task?.status === "running"}><span>{task?.status === "running" ? "分析进行中" : "更新相似分组"}</span><b aria-hidden="true">→</b></button></div>
        <div className="structure-stat"><strong>{visual ? numberFormat.format(visual.similarity_group_count) : "—"}</strong><span>个画面相似组</span></div>
      </section>
      <TaskCard task={task} cancel={cancelTask} />
      {selectedGroup ? (
        <section className="panel comparison-panel">
          <div className="panel-heading">
            <div><span className="section-kicker">组内对比</span><h3>{selectedGroup.event_name}</h3></div>
            <button className="secondary-action compact" onClick={closeGroup}>返回相似组</button>
          </div>
          <div className="comparison-note">共 {selectedGroup.capture_count} 张 · 按拍摄顺序排列 · 点击图片查看完整参数</div>
          <div className="comparison-grid">
            {selectedGroup.items.map((item) => (
              <article className={`comparison-card ${item.auto_pick ? "auto-pick" : ""} ${item.user_pick ? "user-pick" : ""} ${item.user_reject ? "user-reject" : ""}`} key={item.capture_id} onClick={() => openCapture(item.capture_id)}>
                <div className="photo-frame">
                  <img src={item.thumbnail_url} loading="lazy" alt={`${item.stem} 缩略图`} />
                  {item.auto_pick ? <span className="photo-flag">技术推荐</span> : null}
                  {item.user_pick ? <span className="photo-flag user">已保留</span> : null}
                </div>
                <div className="photo-card-copy"><strong>{item.stem}</strong><span>{item.technical_score == null ? "尚未评分" : `技术分 ${Math.round(item.technical_score)}`} · {formatExposure(item.exposure_time)} · ISO {item.iso ?? "—"}</span></div>
                <div className="photo-review" onClick={(event) => event.stopPropagation()}>
                  <select aria-label={`${item.stem} 人工星级`} value={item.user_rating ?? ""} onChange={(event) => saveReview(item.capture_id, { user_rating: event.target.value ? Number(event.target.value) : null, user_pick: Boolean(item.user_pick), user_reject: Boolean(item.user_reject), user_note: item.user_note })}>
                    <option value="">星级</option><option value="1">1★</option><option value="2">2★</option><option value="3">3★</option><option value="4">4★</option><option value="5">5★</option>
                  </select>
                  <button className={item.user_pick ? "selected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: !item.user_pick, user_reject: false, user_note: item.user_note })}>保留</button>
                  <button className={item.user_reject ? "rejected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: false, user_reject: !item.user_reject, user_note: item.user_note })}>待淘汰</button>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : (
        <section className="panel similarity-panel">
          <div className="panel-heading"><div><span className="section-kicker">画面相似组</span><h3>开始选片</h3></div><span className="batch-count">{numberFormat.format(groups?.count ?? 0)} 组 · 点击进入对比</span></div>
          <div className="similarity-grid">
            {(groups?.items ?? []).map((group) => (
              <button className="similarity-card" key={group.id} onClick={() => openGroup(group.id)}>
                <span className="similarity-cover"><img src={group.thumbnail_url} loading="lazy" alt={`${group.event_name} 相似组封面`} /><b>{group.capture_count} 张</b></span>
                <span className="similarity-copy"><strong>{group.event_name}</strong><small>{group.recommended_stem ? `推荐 ${group.recommended_stem}` : "等待技术评分"}{group.average_score == null ? "" : ` · 均分 ${group.average_score}`}</small></span>
              </button>
            ))}
          </div>
          {groups && <Pagination count={groups.count} limit={groups.limit} offset={groups.offset} onChange={changeGroupPage} onLimitChange={changeGroupPageSize} />}
        </section>
      )}
      <section className="metric-grid burst-metrics">
        <article><span>已生成指纹</span><strong>{visual ? numberFormat.format(visual.fingerprint_count) : "—"}</strong><small>只保存特征，不复制照片</small></article>
        <article><span>进入相似组</span><strong>{visual ? numberFormat.format(visual.captures_in_similarity_groups) : "—"}</strong><small>拍摄单元</small></article>
        <article><span>最大相似组</span><strong>{visual?.largest_similarity_group ?? "—"}</strong><small>张</small></article>
        <article><span>当前判断依据</span><strong className="text-value">画面 + 色彩</strong><small>无需大模型的快速预筛</small></article>
      </section>
      <section className="panel burst-panel">
        <div className="panel-heading"><div><span className="section-kicker">优先处理</span><h3>最大的连拍候选</h3></div><span className="batch-count">按组内数量排序</span></div>
        <div className="burst-list">
          {(bursts?.items ?? []).map((burst, index) => (
            <article className="burst-row" key={burst.id}>
              <span className="burst-rank">{String(index + 1).padStart(2, "0")}</span>
              <div className="burst-main"><strong>{burst.event_name}</strong><span>{burst.first_stem} → {burst.last_stem}</span></div>
              <div className="burst-camera"><strong>{burst.camera_model ?? "未知相机"}</strong><span>{burst.start_at.replace("T", " ")}</span></div>
              <div className="burst-count"><strong>{burst.capture_count}</strong><span>张</span></div>
              <span className="candidate-badge">{burst.similarity_group_count ? `${burst.similarity_group_count} 个相似组` : "未形成相似组"}</span>
            </article>
          ))}
        </div>
        {bursts && <Pagination count={bursts.count} limit={bursts.limit} offset={bursts.offset} onChange={changeBurstPage} onLimitChange={changeBurstPageSize} />}
      </section>
    </>
  );
}

function CaptureDetailPanel({ detail, close, saveAiReview }: {
  detail: CaptureDetail;
  close: () => void;
  saveAiReview: (analysisId: number, verdict: "accurate" | "partial" | "inaccurate" | null, note: string | null) => void;
}) {
  const exif = detail.files.find((file) => file.role === "jpeg") ?? detail.files[0];
  const latestAnalysis = detail.ai_analyses[0];
  const latestAi = latestAnalysis?.result as Record<string, unknown> | undefined;
  const visibleProblems = Array.isArray(latestAi?.visible_problems) ? latestAi.visible_problems as Array<Record<string, unknown>> : [];
  const shootingAdvice = Array.isArray(latestAi?.shooting_advice) ? latestAi.shooting_advice as Array<Record<string, unknown>> : [];
  const lightroomSuggestions = Array.isArray(latestAi?.lightroom_suggestions) ? latestAi.lightroom_suggestions as Array<Record<string, unknown>> : [];
  const [aiNote, setAiNote] = useState(latestAnalysis?.user_note ?? "");
  return (
    <div className="detail-backdrop" role="dialog" aria-modal="true" aria-label={`${detail.stem} 照片详情`} onClick={close}>
      <section className="detail-panel" onClick={(event) => event.stopPropagation()}>
        <button className="detail-close" onClick={close} aria-label="关闭详情">×</button>
        <div className="detail-image"><img src={detail.thumbnail_url} alt={`${detail.stem} 大图预览`} /></div>
        <div className="detail-copy">
          <span className="section-kicker">{detail.category ?? "未分类"}</span>
          <h2>{detail.stem}</h2>
          <p>{detail.event_name ?? detail.parent_relative}</p>
          <div className="exif-strip">
            <div><strong>{formatExposure(exif?.exposure_time)}</strong><span>快门</span></div>
            <div><strong>{exif?.f_number ? `f/${exif.f_number}` : "—"}</strong><span>光圈</span></div>
            <div><strong>{exif?.iso ? `ISO ${exif.iso}` : "—"}</strong><span>感光度</span></div>
            <div><strong>{exif?.focal_length_mm ? `${exif.focal_length_mm}mm` : "—"}</strong><span>焦距</span></div>
          </div>
          <div className="detail-section"><h3>技术评分</h3><p>{detail.technical_score == null ? "尚未运行技术质量分析。" : `总分 ${Math.round(detail.technical_score)} · 曝光 ${Math.round(detail.exposure_score ?? 0)} · 清晰度 ${Math.round(detail.sharpness_score ?? 0)} · 参数 ${Math.round(detail.exif_score ?? 0)}`}</p></div>
          <div className="detail-section"><h3>问题证据</h3>{detail.issues.length ? <ul>{detail.issues.map((issue) => <li key={issue.code}>{issue.message}</li>)}</ul> : <p>尚未发现或尚未分析。</p>}</div>
          <div className="detail-section"><h3>本地模型建议</h3><p>{typeof latestAi?.quality_summary === "string" ? latestAi.quality_summary : "尚未运行本地模型分析。"}</p>
            {latestAnalysis && <small className="ai-result-version">{latestAnalysis.model_id} · {latestAnalysis.prompt_version} · {formatDate(latestAnalysis.finished_at)}</small>}
            {!!visibleProblems.length && <div className="ai-advice-block"><strong>可见问题</strong><ul>{visibleProblems.map((problem, index) => <li key={index}><b>{String(problem.name ?? "问题")}</b>：{String(problem.evidence ?? "没有证据说明")}（{String(problem.severity ?? "—")} / {String(problem.confidence ?? "—")}）</li>)}</ul></div>}
            {!!shootingAdvice.length && <div className="ai-advice-block"><strong>下次拍摄</strong><ul>{shootingAdvice.map((advice, index) => <li key={index}><b>{String(advice.suggestion ?? "建议")}</b>：{String(advice.reason ?? "")} <em>{String(advice.exif_basis ?? "")}</em></li>)}</ul></div>}
            {!!lightroomSuggestions.length && <div className="ai-advice-block"><strong>Lightroom</strong><ul>{lightroomSuggestions.map((advice, index) => <li key={index}><b>{String(advice.adjustment ?? "调整")}</b> · {String(advice.direction ?? "")}：{String(advice.reason ?? "")}</li>)}</ul></div>}
            {latestAnalysis && <div className="ai-advice-block"><strong>Photoshop</strong><p>{latestAi?.photoshop_needed === true ? "建议使用" : "不需要"} · {String(latestAi?.photoshop_reason ?? "未说明")}</p></div>}
            {latestAnalysis && <div className="ai-review-controls">
              <span>这条分析是否可信？</span>
              <div>
                <button className={latestAnalysis.user_verdict === "accurate" ? "selected" : ""} onClick={() => saveAiReview(latestAnalysis.id, "accurate", aiNote)}>准确</button>
                <button className={latestAnalysis.user_verdict === "partial" ? "selected" : ""} onClick={() => saveAiReview(latestAnalysis.id, "partial", aiNote)}>部分准确</button>
                <button className={latestAnalysis.user_verdict === "inaccurate" ? "rejected" : ""} onClick={() => saveAiReview(latestAnalysis.id, "inaccurate", aiNote)}>不准确</button>
              </div>
              <textarea value={aiNote} onChange={(event) => setAiNote(event.target.value)} placeholder="可选：记录误判、漏判或参数建议问题" maxLength={2000} />
              <button onClick={() => saveAiReview(latestAnalysis.id, latestAnalysis.user_verdict, aiNote)}>保存备注</button>
            </div>}
          </div>
          <div className="detail-section"><h3>文件</h3><p>{detail.files.map((file) => `${file.file_name} · ${formatFileSize(file.size_bytes)}`).join(" / ")}</p></div>
        </div>
      </section>
    </div>
  );
}

function PhotoLibraryView({ library, filters, query, updateQuery, openCapture, exportPhotos, assignToAlbum, changePage, changePageSize }: {
  library: LibraryCapturesResponse | null;
  filters: LibraryFilters | null;
  query: LibraryQuery;
  updateQuery: (changes: Partial<LibraryQuery>) => void;
  openCapture: (captureId: number) => void;
  exportPhotos: (captureIds: number[], maxEdge: number) => Promise<PhoneShareExport>;
  assignToAlbum: (albumId: number, captureIds: number[]) => Promise<void>;
  changePage: (offset: number) => void;
  changePageSize: (limit: number) => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [targetAlbum, setTargetAlbum] = useState("");
  const [maxEdge, setMaxEdge] = useState(2048);
  const [exporting, setExporting] = useState(false);
  const [latestExport, setLatestExport] = useState<PhoneShareExport | null>(null);
  const toggle = (captureId: number) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(captureId)) next.delete(captureId); else next.add(captureId);
    return next;
  });
  const exportSelected = async () => {
    if (!selected.size) return;
    setExporting(true);
    try {
      const result = await exportPhotos(Array.from(selected), maxEdge);
      setLatestExport(result);
      const link = document.createElement("a");
      link.href = result.download_url;
      link.download = result.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
    } finally {
      setExporting(false);
    }
  };
  const items = library?.items ?? [];
  const allSelected = items.length > 0 && items.every((item) => selected.has(item.id));
  return <>
    <section className="library-toolbar">
      <div><strong>{library ? numberFormat.format(library.count) : "—"}</strong><span>张符合条件的照片</span></div>
      <div className="library-toolbar-actions"><button className="toolbar-button" onClick={() => setSelected((current) => new Set([...current, ...items.map((item) => item.id)]))} disabled={!items.length}>选择本页</button></div>
    </section>
    <section className="library-filters">
      <label className="search-filter"><span>搜索</span><input value={query.search} onChange={(event) => updateQuery({ search: event.target.value })} placeholder="文件名、相册或目录" /></label>
      <label><span>相册</span><select value={query.albumId} onChange={(event) => updateQuery({ albumId: event.target.value })}><option value="">全部相册</option>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select></label>
      <label><span>类型</span><select value={query.category} onChange={(event) => updateQuery({ category: event.target.value })}><option value="">全部类型</option>{(filters?.album_types ?? []).map((type) => <option key={type.name}>{type.name}</option>)}</select></label>
      <label><span>相机</span><select value={query.camera} onChange={(event) => updateQuery({ camera: event.target.value })}><option value="">全部相机</option>{(filters?.cameras ?? []).map((camera) => <option key={camera}>{camera}</option>)}</select></label>
      <label><span>镜头</span><select value={query.lens} onChange={(event) => updateQuery({ lens: event.target.value })}><option value="">全部镜头</option>{(filters?.lenses ?? []).map((lens) => <option key={lens}>{lens}</option>)}</select></label>
      <label><span>人工星级</span><select value={query.rating} onChange={(event) => updateQuery({ rating: event.target.value })}><option value="">全部星级</option>{[5, 4, 3, 2, 1].map((rating) => <option key={rating} value={rating}>{rating} 星</option>)}</select></label>
      <label><span>选片状态</span><select value={query.selection} onChange={(event) => updateQuery({ selection: event.target.value })}><option value="">全部状态</option><option value="picked">已保留</option><option value="rejected">待淘汰</option><option value="unreviewed">未处理</option></select></label>
      <label><span>开始日期</span><input type="date" value={query.dateFrom} onChange={(event) => updateQuery({ dateFrom: event.target.value })} /></label>
      <label><span>结束日期</span><input type="date" value={query.dateTo} onChange={(event) => updateQuery({ dateTo: event.target.value })} /></label>
      <label><span>排序</span><select value={query.sort} onChange={(event) => updateQuery({ sort: event.target.value })}><option value="newest">最新拍摄</option><option value="oldest">最早拍摄</option><option value="name">文件名称</option><option value="rating">人工星级</option></select></label>
      <button className="toolbar-button filter-reset" onClick={() => updateQuery({ albumId: "", category: "", camera: "", lens: "", rating: "", selection: "", dateFrom: "", dateTo: "", search: "", sort: "newest" })}>清除筛选</button>
    </section>
    <section className={`selection-toolbar ${selected.size ? "visible" : ""}`}>
      <div><strong>已选择 {selected.size} 张</strong><button onClick={() => setSelected(allSelected ? new Set([...selected].filter((id) => !items.some((item) => item.id === id))) : new Set([...selected, ...items.map((item) => item.id)]))}>{allSelected ? "取消本页全选" : "选择本页全部"}</button><button onClick={() => setSelected(new Set())}>清除</button></div>
      <div className="selection-actions"><label>归入相册<select value={targetAlbum} onChange={(event) => setTargetAlbum(event.target.value)}><option value="">选择相册</option>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select></label><button disabled={!targetAlbum} onClick={async () => { await assignToAlbum(Number(targetAlbum), Array.from(selected)); setSelected(new Set()); }}>应用</button><label>分享尺寸<select value={maxEdge} onChange={(event) => setMaxEdge(Number(event.target.value))}><option value={1080}>1080px</option><option value={2048}>2048px</option><option value={3840}>3840px</option></select></label><button className="primary-action" disabled={!selected.size || exporting} onClick={exportSelected}><span>{exporting ? "正在生成" : "导出分享包"}</span><b>↓</b></button></div>
    </section>
    {latestExport && <div className="export-success"><span>已生成 {latestExport.photo_count} 张照片 · {formatBytes(latestExport.size_bytes)} · EXIF 已移除</span><a href={latestExport.download_url} download={latestExport.filename}>再次下载</a></div>}
    <section className="photo-library-grid">
      {items.map((item) => <article className={`library-photo-card ${selected.has(item.id) ? "selected" : ""}`} key={item.id}>
        <button className="photo-select" aria-label={`${selected.has(item.id) ? "取消选择" : "选择"} ${item.stem}`} onClick={() => toggle(item.id)}><span>{selected.has(item.id) ? "✓" : ""}</span></button>
        <button className="photo-open" onClick={() => openCapture(item.id)}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} /></button>
        <div className="photo-card-copy"><div><strong>{item.stem}</strong><span>{item.captured_at?.slice(0, 10) ?? "日期未知"}</span></div><p>{item.album_name ?? "尚未归入相册"}</p><div className="photo-card-status"><span>{item.user_rating ? `${item.user_rating} 星` : "未评分"}</span>{item.user_pick ? <b>已选</b> : item.user_reject ? <b className="rejected">待淘汰</b> : null}</div></div>
      </article>)}
      {!items.length && <div className="empty-state">图库中还没有可查看的 JPEG 照片。</div>}
    </section>
    {library && <Pagination count={library.count} limit={library.limit} offset={library.offset} onChange={changePage} onLimitChange={changePageSize} />}
  </>;
}

function LibraryView({ library, albums, filters, query, updateQuery, task, startScan, cancelTask, updateAlbum, createAlbum, createAlbumType, renameAlbumType, deleteAlbumType, assignToAlbum, openCapture, exportPhotos, changePage, changePageSize, changeAlbumPage, changeAlbumPageSize, openAlbum }: {
  library: LibraryCapturesResponse | null;
  albums: EventsResponse | null;
  filters: LibraryFilters | null;
  query: LibraryQuery;
  updateQuery: (changes: Partial<LibraryQuery>) => void;
  task: Task | null;
  startScan: () => void;
  cancelTask: () => void;
  updateAlbum: (album: EventItem, changes: Partial<Pick<EventItem, "proposed_name" | "category" | "status">>) => void;
  createAlbum: (name: string, category: string) => void;
  createAlbumType: (name: string) => void;
  renameAlbumType: (name: string, nextName: string) => void;
  deleteAlbumType: (name: string) => void;
  assignToAlbum: (albumId: number, captureIds: number[]) => Promise<void>;
  openCapture: (captureId: number) => void;
  exportPhotos: (captureIds: number[], maxEdge: number) => Promise<PhoneShareExport>;
  changePage: (offset: number) => void;
  changePageSize: (limit: number) => void;
  changeAlbumPage: (offset: number) => void;
  changeAlbumPageSize: (limit: number) => void;
  openAlbum: (albumId: number) => void;
}) {
  const [section, setSection] = useState<LibrarySection>("photos");
  return (
    <>
      <div className="section-tabs" role="tablist" aria-label="图库功能">
        <button className={section === "photos" ? "active" : ""} onClick={() => setSection("photos")}>全部照片</button>
        <button className={section === "albums" ? "active" : ""} onClick={() => setSection("albums")}>相册管理</button>
      </div>
      {section === "photos" && <PhotoLibraryView library={library} filters={filters} query={query} updateQuery={updateQuery} openCapture={openCapture} exportPhotos={exportPhotos} assignToAlbum={assignToAlbum} changePage={changePage} changePageSize={changePageSize} />}
      {section === "albums" && <AlbumsView albums={albums} filters={filters} updateAlbum={updateAlbum} createAlbum={createAlbum} createAlbumType={createAlbumType} renameAlbumType={renameAlbumType} deleteAlbumType={deleteAlbumType} openAlbum={(albumId) => { openAlbum(albumId); setSection("photos"); }} changePage={changeAlbumPage} changePageSize={changeAlbumPageSize} />}
      <section className="library-maintenance"><div><strong>图库维护</strong><span>只在加入新照片后运行增量扫描。</span></div><button className="toolbar-button" onClick={startScan} disabled={task?.status === "running"}>{task?.status === "running" ? "扫描进行中" : "扫描新照片"}</button></section>
      <TaskCard task={task} cancel={cancelTask} />
    </>
  );
}

function HomeView({ overview, events, groups, analysis, statistics, library, task, navigate, openCapture }: {
  overview: Overview | null;
  events: EventsResponse | null;
  groups: SimilarityGroupsResponse | null;
  analysis: AnalysisOverview | null;
  statistics: Statistics | null;
  library: LibraryCapturesResponse | null;
  task: Task | null;
  navigate: (view: View) => void;
  openCapture: (captureId: number) => void;
}) {
  const pendingEvents = (events?.items ?? []).filter((event) => event.status !== "confirmed").length;
  const quality = analysis?.quality;
  const remainingQuality = Math.max(0, (overview?.capture_total ?? 0) - (quality?.analyzed ?? 0));
  return <>
    <section className="home-metrics">
      <article><span>全部照片</span><strong>{overview ? numberFormat.format(overview.capture_total) : "—"}</strong><small>{overview ? formatBytes(overview.files.size_bytes) : ""}</small></article>
      <article><span>拍摄相册</span><strong>{overview?.structure.event_count ?? "—"}</strong><small>{pendingEvents} 个名称待确认</small></article>
      <article><span>相似照片</span><strong>{groups?.count ?? "—"}</strong><small>组</small></article>
      <article><span>已选照片</span><strong>{numberFormat.format(statistics?.summary.user_picks ?? 0)}</strong><small>可导出或准备后期</small></article>
    </section>
    <section className="home-management-grid">
      <section className="panel recent-photos-panel"><div className="panel-heading"><div><h3>最近照片</h3></div><button className="text-action" onClick={() => navigate("library")}>查看全部</button></div><div className="recent-photo-grid">
        {(library?.items ?? []).slice(0, 8).map((item) => <button key={item.id} onClick={() => openCapture(item.id)}><img src={item.thumbnail_url} alt={item.stem} /><span>{item.stem}</span></button>)}
      </div></section>
      <section className="panel pending-panel"><div className="panel-heading"><div><h3>待处理</h3></div></div><div className="pending-list">
        <button onClick={() => navigate("library")}><span><strong>{pendingEvents}</strong> 个相册名称待确认</span><b>整理相册</b></button>
        <button onClick={() => navigate("bursts")}><span><strong>{groups?.count ?? 0}</strong> 组相似照片可挑选</span><b>开始挑选</b></button>
        <button onClick={() => navigate("analysis")}><span><strong>{numberFormat.format(remainingQuality)}</strong> 张照片尚未质量分析</span><b>查看分析</b></button>
        <button onClick={() => navigate("library")}><span><strong>{numberFormat.format(statistics?.summary.user_picks ?? 0)}</strong> 张照片已标记保留</span><b>选择导出</b></button>
      </div></section>
    </section>
    {task && task.status !== "idle" && <section className="home-current-task"><TaskCard task={task} /></section>}
  </>;
}

function AnalysisView({ analysis, preflight, quality, task, startQuality, startAi, saveReview, cancelTask, pauseAi, resumeAi, retryAiFailures, openCapture, changeQualityPage, changeQualityPageSize }: {
  analysis: AnalysisOverview | null;
  preflight: AiPreflight | null;
  quality: QualityResponse | null;
  task: Task | null;
  startQuality: () => void;
  startAi: (mode: "benchmark" | "recommended", limit: number) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  cancelTask: () => void;
  pauseAi: () => void;
  resumeAi: (runId: number) => void;
  retryAiFailures: (runId: number) => void;
  openCapture: (captureId: number) => void;
  changeQualityPage: (offset: number) => void;
  changeQualityPageSize: (limit: number) => void;
}) {
  const summary = analysis?.quality;
  const ai = analysis?.ai;
  const running = task?.status === "running";
  const [batchSize, setBatchSize] = useState(100);
  const [resultOffset, setResultOffset] = useState(0);
  const [resultLimit, setResultLimit] = useState(40);
  const [resultVersion, setResultVersion] = useState("photo-critique-v4");
  const [resultVerdict, setResultVerdict] = useState("all");
  const [resultPage, setResultPage] = useState<AiResultsResponse | null>(null);
  const [gpu, setGpu] = useState<GpuStatus | null>(null);
  const estimatedBatchSeconds = ai?.latest_run?.average_seconds_per_photo
    ? ai.latest_run.average_seconds_per_photo * batchSize
    : null;
  useEffect(() => {
    let active = true;
    const parameters = new URLSearchParams({ limit: String(resultLimit), offset: String(resultOffset) });
    if (resultVersion !== "all") parameters.set("prompt_version", resultVersion);
    if (resultVerdict !== "all") parameters.set("verdict", resultVerdict);
    getJson<AiResultsResponse>(`/api/ai/results?${parameters.toString()}`)
      .then((page) => { if (active) setResultPage(page); })
      .catch(() => { if (active) setResultPage(null); });
    return () => { active = false; };
  }, [resultLimit, resultOffset, resultVersion, resultVerdict, ai?.completed_analysis_count]);
  useEffect(() => {
    let active = true;
    const refresh = () => getJson<GpuStatus>("/api/system/gpu")
      .then((status) => { if (active) setGpu(status); })
      .catch(() => { if (active) setGpu(null); });
    void refresh();
    const timer = running ? window.setInterval(refresh, 5000) : null;
    return () => {
      active = false;
      if (timer != null) window.clearInterval(timer);
    };
  }, [running]);
  return (
    <>
      <section className="structure-hero analysis-hero">
        <div>
          <span className="section-kicker">分层分析</span>
          <h2>照片质量与问题</h2>
          <p>技术检测覆盖全部个人照片；Qwen3-VL 只处理代表帧和问题候选。模型结果仅作复核建议，不会自动删除或改写 Lightroom。</p>
          <div className="analysis-actions">
            <button className="primary-action" onClick={startQuality} disabled={running}><span>运行技术质量分析</span><b>→</b></button>
            <button className="secondary-action" onClick={() => startAi("benchmark", 10)} disabled={running || !summary?.analyzed || !preflight?.ready}>10张快速验证</button>
            <label className="analysis-batch-control">
              <span>每批</span>
              <select value={batchSize} onChange={(event) => setBatchSize(Number(event.target.value))} disabled={running}>
                {[25, 50, 100, 200, 500].map((size) => <option key={size} value={size}>{size} 张</option>)}
              </select>
              <small>{estimatedBatchSeconds ? `约 ${formatDuration(estimatedBatchSeconds)}` : "完成一次后显示估时"}</small>
            </label>
            <button className="secondary-action" onClick={() => startAi("recommended", batchSize)} disabled={running || !summary?.analyzed || !preflight?.ready}>运行推荐批次</button>
            {ai?.latest_run && ["failed", "cancelled", "paused"].includes(ai.latest_run.status) && <button className="secondary-action" onClick={() => resumeAi(ai.latest_run!.id)} disabled={running}>继续上次模型任务</button>}
            {ai?.latest_run && ai.latest_run.status === "complete" && ai.latest_run.failed_count > 0 && <button className="secondary-action" onClick={() => retryAiFailures(ai.latest_run!.id)} disabled={running || !preflight?.ready}>用当前版本重试失败项</button>}
          </div>
          {ai?.candidates && <p className="candidate-count">当前模型与提示词尚有 {numberFormat.format(ai.candidates.recommended_available)} 张推荐候选；快速验证可从 {numberFormat.format(ai.candidates.benchmark_available)} 张中均衡抽样。</p>}
        </div>
        <div className={`runtime-card ${preflight?.ready ? "ready" : ""}`}>
          <span>模型运行环境</span><strong>{preflight?.ready ? "预检通过" : "未就绪"}</strong><small>{preflight ? (preflight.ready ? `${preflight.quantization.toUpperCase()} · ${formatFileSize(preflight.model_bytes)} · ${preflight.image_max_edge ?? 1280}px · 显存上限 ${preflight.gpu_memory_limit_gb}GB` : preflight.blockers.join("；")) : analysis?.runtime.message ?? "正在检查"}</small>
          {gpu?.available && <small>{gpu.name} · GPU {gpu.utilization_percent}% · 显存 {((gpu.memory_used_mb ?? 0) / 1024).toFixed(1)} / {((gpu.memory_total_mb ?? 0) / 1024).toFixed(1)} GB · {gpu.temperature_c}°C</small>}
        </div>
      </section>
      <TaskCard task={task} cancel={cancelTask} pause={pauseAi} />
      <section className="metric-grid">
        <article><span>技术分析完成</span><strong>{summary ? numberFormat.format(summary.analyzed) : "—"}</strong><small>{summary?.errors ?? 0} 个读取错误</small></article>
        <article><span>平均技术分</span><strong>{summary?.average_score ?? "—"}</strong><small>算法证据，不代表审美</small></article>
        <article><span>组内推荐</span><strong>{summary ? numberFormat.format(summary.recommended_picks) : "—"}</strong><small>每个相似组一个候选</small></article>
        <article><span>模型分析完成</span><strong>{ai ? numberFormat.format(ai.analyzed_capture_count) : "—"}</strong><small>{ai?.latest_run ? `${ai.latest_run.model_id} · ${ai.latest_run.status}${ai.latest_run.average_seconds_per_photo ? ` · ${ai.latest_run.average_seconds_per_photo.toFixed(1)}秒/张` : ""}` : "尚未启动"}</small></article>
      </section>
      {ai?.result_audit?.latest && <section className="metric-grid ai-audit-metrics">
        <article><span>当前提示词结果</span><strong>{numberFormat.format(ai.result_audit.latest.result_count)}</strong><small>{ai.result_audit.latest.prompt_version}</small></article>
        <article><span>发现具体问题</span><strong>{numberFormat.format(ai.result_audit.latest.with_visible_problems)}</strong><small>有画面证据才展开建议</small></article>
        <article><span>过度自信输出</span><strong>{numberFormat.format(ai.result_audit.latest.overconfident)}</strong><small>置信度 ≥ 0.99，v3 将自动校准</small></article>
        <article><span>结构/逻辑警告</span><strong>{numberFormat.format(ai.result_audit.latest.schema_errors ?? 0)}</strong><small>缺字段、枚举或参数方向需复核</small></article>
        <article><span>危险操作提及</span><strong>{numberFormat.format(ai.result_audit.latest.unsafe_action_mentions ?? 0)}</strong><small>只提示人工复核，系统不会执行</small></article>
        <article><span>当前版本均速</span><strong>{ai.result_audit.latest.average_seconds_per_photo == null ? "—" : `${ai.result_audit.latest.average_seconds_per_photo.toFixed(1)} 秒`}</strong><small>{numberFormat.format(ai.result_audit.latest.timed_count)} 张有效计时</small></article>
        <article><span>人工复核</span><strong>{numberFormat.format(ai.result_audit.latest.reviewed)}</strong><small>准确 {ai.result_audit.latest.verdicts.accurate} · 部分 {ai.result_audit.latest.verdicts.partial} · 不准确 {ai.result_audit.latest.verdicts.inaccurate}</small></article>
      </section>}
      {!!ai?.result_audit?.versions?.length && <section className="panel ai-version-panel">
        <div className="panel-heading"><div><span className="section-kicker">版本比较</span><h3>提示词质量与速度</h3></div><span className="batch-count">结构异常只提示人工复核</span></div>
        <div className="ai-version-table">
          <div className="ai-version-row ai-version-header"><span>版本</span><span>结果</span><span>均速</span><span>平均置信度</span><span>结构/逻辑警告</span><span>危险提及</span></div>
          {ai.result_audit.versions.map((version) => <div className="ai-version-row" key={version.prompt_version}>
            <strong>{version.prompt_version}</strong><span>{numberFormat.format(version.result_count)}</span><span>{version.average_seconds_per_photo == null ? "—" : `${version.average_seconds_per_photo.toFixed(1)}秒`}</span><span>{version.average_confidence ?? "—"}</span><span>{version.schema_errors}</span><span>{version.unsafe_action_mentions}</span>
          </div>)}
        </div>
      </section>}
      {!!ai?.recent_results?.length && <section className="panel ai-results-panel">
        <div className="panel-heading"><div><span className="section-kicker">最近完成</span><h3>模型分析结果</h3></div><span className="batch-count">点击照片查看完整建议并人工复核</span></div>
        <div className="ai-result-grid">
          {ai.recent_results.map((result) => <button key={result.id} className="ai-result-card" onClick={() => openCapture(result.capture_id)}>
            <img src={result.thumbnail_url} loading="lazy" alt={`${result.stem} 缩略图`} />
            <span><strong>{result.stem} · {result.subject_type ?? "未分类"}</strong><small>{result.quality_summary ?? "没有摘要"}</small><em>{result.visible_problem_count} 个问题 · 技术分 {result.technical_score == null ? "—" : Math.round(result.technical_score)} · 置信度 {result.overall_confidence ?? "—"}</em></span>
          </button>)}
        </div>
      </section>}
      <section className="panel ai-results-panel">
        <div className="panel-heading"><div><span className="section-kicker">分页复核</span><h3>全部模型结果</h3></div><span className="batch-count">{resultPage ? `${numberFormat.format(resultPage.count)} 条` : "正在读取"}</span></div>
        <div className="ai-results-toolbar">
          <label>提示词版本<select value={resultVersion} onChange={(event) => { setResultVersion(event.target.value); setResultOffset(0); }}>
            <option value="photo-critique-v4">v4 当前结果</option>
            {(ai?.result_audit?.versions ?? []).filter((item) => item.prompt_version !== "photo-critique-v4").map((item) => <option key={item.prompt_version} value={item.prompt_version}>{item.prompt_version}</option>)}
            <option value="all">全部版本</option>
          </select></label>
          <label>人工复核<select value={resultVerdict} onChange={(event) => { setResultVerdict(event.target.value); setResultOffset(0); }}>
            <option value="all">全部</option><option value="unreviewed">未复核</option><option value="accurate">准确</option><option value="partial">部分准确</option><option value="inaccurate">不准确</option>
          </select></label>
        </div>
        {!!resultPage?.items.length && <div className="ai-result-grid">
          {resultPage.items.map((result) => <button key={result.id} className="ai-result-card" onClick={() => openCapture(result.capture_id)}>
            <img src={result.thumbnail_url} loading="lazy" alt={`${result.stem} 缩略图`} />
            <span><strong>{result.stem} · {result.subject_type ?? "未分类"}</strong><small>{result.quality_summary ?? "没有摘要"}</small><em className={result.review_flags?.length ? "result-review-warning" : ""}>{result.review_flags?.length ? "需优先人工复核" : `${result.visible_problem_count} 个问题`} · {result.prompt_version} · {result.user_verdict ?? "未复核"}</em></span>
          </button>)}
        </div>}
        {resultPage && !resultPage.items.length && <div className="empty-state">当前筛选条件没有模型结果。</div>}
        {resultPage && <Pagination count={resultPage.count} limit={resultPage.limit} offset={resultPage.offset} onChange={setResultOffset} onLimitChange={(limit) => { setResultOffset(0); setResultLimit(limit); }} />}
      </section>
      {!!ai?.recent_runs.length && (
        <section className="panel ai-history-panel">
          <div className="panel-heading"><div><span className="section-kicker">运行记录</span><h3>模型任务历史</h3></div><span className="batch-count">保留模型、量化和提示词版本</span></div>
          <div className="ai-run-list">
            {ai.recent_runs.map((run) => (
              <article className="ai-run-row" key={run.id}>
                <div><strong>#{run.id} · {run.model_id}</strong><span>{run.mode} · {formatDate(run.started_at)}{run.backup_count ? ` · ${run.backup_count} 份数据库备份` : ""}{run.report_available && <> · <a href={`/api/ai/runs/${run.id}/report.csv`}>CSV</a> · <a href={`/api/ai/runs/${run.id}/report.json`}>JSON</a> · <a href={`/api/reports/ai-run-${run.id}.log`}>日志</a></>}</span></div>
                <div><strong>{run.completed_count} / {run.requested_count}</strong><span>完成 / 计划</span></div>
                <div><strong>{run.success_rate == null ? "—" : `${run.success_rate}%`}</strong><span>成功率</span></div>
                <div><strong>{run.average_seconds_per_photo == null ? "—" : `${run.average_seconds_per_photo.toFixed(1)}秒`}</strong><span>平均每张</span></div>
                <div><strong>{run.status}</strong><span>{run.failed_count ? `${run.failed_count} 个失败` : "无失败"}</span></div>
              </article>
            ))}
          </div>
          {!!ai.latest_failures.length && (
            <div className="ai-failure-list">
              <strong>最近任务失败清单</strong>
              {ai.latest_failures.map((failure) => (
                <div key={failure.id}><span>{failure.stem} · 尝试 {failure.attempt_count} 次</span><small>{failure.error ?? "未知错误"}</small></div>
              ))}
            </div>
          )}
        </section>
      )}
      <section className="panel event-panel">
        <div className="panel-heading"><div><span className="section-kicker">优先复核</span><h3>技术问题候选</h3></div><span className="batch-count">按技术分从低到高</span></div>
        <div className="event-list quality-list">
          {(quality?.items ?? []).map((item) => (
            <article className="event-row quality-row" key={item.capture_id}>
              <div className={`category-chip category-${item.category}`}>{item.category}</div>
              <div className="event-main"><strong>{item.stem}{item.auto_pick ? " · 组内推荐" : ""}</strong><span>{item.ai_result?.quality_summary ?? (item.issues.map((issue) => issue.message).join("；") || "未发现明确技术问题")}</span></div>
              <div className="event-measure"><strong>{Math.round(item.technical_score)}</strong><span>技术分</span></div>
              <div className="event-measure"><strong>{technicalGrade(item.technical_score)}</strong><span>技术评级</span></div>
              <div className="review-controls">
                <select aria-label={`${item.stem} 人工星级`} value={item.user_rating ?? ""} onChange={(event) => saveReview(item.capture_id, { user_rating: event.target.value ? Number(event.target.value) : null, user_pick: Boolean(item.user_pick), user_reject: Boolean(item.user_reject), user_note: item.user_note })}>
                  <option value="">人工星级</option><option value="1">1 星</option><option value="2">2 星</option><option value="3">3 星</option><option value="4">4 星</option><option value="5">5 星</option>
                </select>
                <button className={item.user_pick ? "selected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: !item.user_pick, user_reject: false, user_note: item.user_note })}>保留</button>
                <button className={item.user_reject ? "rejected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: false, user_reject: !item.user_reject, user_note: item.user_note })}>待淘汰</button>
              </div>
            </article>
          ))}
          {!quality?.items.length && <div className="empty-state">代码已就绪。先运行技术质量分析，模型按钮随后会启用。</div>}
        </div>
        {quality && <Pagination count={quality.count} limit={quality.limit} offset={quality.offset} onChange={changeQualityPage} onLimitChange={changeQualityPageSize} />}
      </section>
    </>
  );
}

function Distribution({ title, rows, labelKey }: {
  title: string;
  rows: StatisticRow[];
  labelKey: string;
}) {
  const maximum = Math.max(1, ...rows.map((row) => row.count));
  return (
    <section className="panel distribution-panel">
      <div className="panel-heading"><div><span className="section-kicker">分布</span><h3>{title}</h3></div></div>
      <div className="bar-list">
        {rows.map((row, index) => (
          <div className="bar-row" key={`${String(row[labelKey])}-${index}`}>
            <span title={String(row[labelKey])}>{String(row[labelKey])}</span>
            <div><i style={{ width: `${Math.max(2, row.count / maximum * 100)}%` }} /></div>
            <strong>{numberFormat.format(row.count)}</strong>
            <small>{row.average_score == null ? "未评分" : `均分 ${row.average_score}`}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function EquipmentView({ equipment }: { equipment: EquipmentCatalog | null }) {
  const accessoryLabels: Record<string, string> = {
    supports: "支撑设备",
    remotes: "快门控制",
    lighting: "闪光与引闪",
    filters: "滤镜",
    adapters: "转接环",
    accessories: "其他配件",
  };
  return (
    <>
      <section className="compact-summary">
        <div><span className="section-kicker">器材档案</span><h2>设备管理</h2><p>统一查看已拥有器材、滤镜兼容关系和图库中的实际使用量。</p></div>
        <div className="compact-actions"><span>档案来源</span><strong>{equipment?.profile_file ?? "读取中"}</strong></div>
      </section>
      <section className="metric-grid">
        <article><span>相机</span><strong>{equipment?.summary.camera_count ?? "—"}</strong><small>已登记机身</small></article>
        <article><span>镜头</span><strong>{equipment?.summary.lens_count ?? "—"}</strong><small>{equipment?.summary.detected_lens_count ?? "—"} 种出现在 EXIF</small></article>
        <article><span>附件</span><strong>{equipment?.summary.accessory_count ?? "—"}</strong><small>灯光、滤镜与支撑设备</small></article>
        <article><span>滤镜系统</span><strong className="text-value">全镜头兼容</strong><small>通过转接环使用</small></article>
      </section>
      <section className="equipment-layout">
        <section className="panel equipment-panel">
          <div className="panel-heading"><div><span className="section-kicker">相机系统</span><h3>机身与镜头</h3></div><span className="batch-count">拍摄量按拍摄单元计算</span></div>
          <div className="equipment-list">
            {[...(equipment?.cameras ?? []), ...(equipment?.lenses ?? [])].map((item) => (
              <article className="equipment-row" key={`${item.model}-${item.filter_thread_mm ?? "body"}`}>
                <div className="equipment-icon">{item.filter_thread_mm ? "L" : "C"}</div>
                <div><strong>{item.display_name ?? item.model}</strong><span>{item.brand ?? "未知品牌"}{item.filter_thread_mm ? ` · ${item.filter_thread_mm}mm 滤镜口径` : " · 相机机身"}</span></div>
                <div className="equipment-usage"><strong>{numberFormat.format(item.capture_count ?? 0)}</strong><span>拍摄单元</span></div>
              </article>
            ))}
          </div>
        </section>
        <section className="panel equipment-panel">
          <div className="panel-heading"><div><span className="section-kicker">附件清单</span><h3>灯光、滤镜与辅助设备</h3></div></div>
          <div className="equipment-list accessory-list">
            {(equipment?.accessories ?? []).map((item, index) => (
              <article className="equipment-row" key={`${item.section}-${item.model ?? index}`}>
                <div className="equipment-icon accessory">{String(accessoryLabels[item.section ?? ""] ?? "附件").slice(0, 1)}</div>
                <div><strong>{item.display_name ?? item.model ?? item.kind}</strong><span>{accessoryLabels[item.section ?? ""] ?? "附件"}{item.thread_mm ? ` · ${item.thread_mm}mm` : ""}{item.stops ? ` · ${item.stops} 档` : ""}</span></div>
                <span className="owned-badge">在用</span>
              </article>
            ))}
          </div>
        </section>
      </section>
      <section className="panel equipment-note">
        <strong>这一版先把器材档案与照片使用统计放到同一个界面。</strong>
        <span>下一步可加入购买日期、序列号、保修、借出状态、维护记录和自定义备注；这些信息只进入本地数据库。</span>
      </section>
    </>
  );
}

function ArchiveView({ archive, activeLibrary, createBaseline, createActiveBaseline }: {
  archive: ArchiveStatus | null;
  activeLibrary: ArchiveStatus | null;
  createBaseline: () => void;
  createActiveBaseline: () => void;
}) {
  const baselineCard = (title: string, status: ArchiveStatus | null, create: () => void, historical: boolean) => (
    <section className="panel archive-panel">
      <div className="panel-heading"><div><span className="section-kicker">{historical ? "历史档案" : "活动图库"}</span><h3>{title}</h3></div></div>
      {status?.baseline ? <div className="archive-status">
        <span className={`archive-health ${status.comparison?.healthy ? "healthy" : "warning"}`}>{status.comparison?.healthy ? "当前图库与基线一致" : "发现需要复核的差异"}</span>
        <strong>{status.baseline.name}</strong>
        <small>{formatDate(status.baseline.created_at)} · {numberFormat.format(status.baseline.file_count)} 个文件 · {formatBytes(status.baseline.total_bytes)}</small>
        <div className="archive-counts"><div><b>{status.comparison?.missing ?? 0}</b><span>缺失</span></div><div><b>{status.comparison?.changed ?? 0}</b><span>变化</span></div><div><b>{status.comparison?.new ?? 0}</b><span>新增</span></div></div>
      </div> : <div className="archive-status"><p>尚未建立完整性基线。基线只记录路径、大小和修改时间，不复制或修改照片。</p><button className="primary-action" onClick={create}><span>建立基线</span><b>→</b></button></div>}
    </section>
  );
  return <>
    <section className="compact-summary"><div><span className="section-kicker">系统安全</span><h2>原片保护</h2><p>独立核对历史档案与活动图库，所有差异只报告、不自动修复。</p></div></section>
    <section className="statistics-grid">
      {baselineCard("历史原片完整性", archive, createBaseline, true)}
      {baselineCard("活动图库完整性", activeLibrary, createActiveBaseline, false)}
    </section>
  </>;
}

function StatisticsView({ statistics }: {
  statistics: Statistics | null;
}) {
  const summary = statistics?.summary;
  return (
    <>
      <section className="structure-hero statistics-hero">
        <div><span className="section-kicker">摄影数据</span><h2>拍摄统计</h2><p>查看题材、器材和拍摄参数分布。</p></div>
        <div className="structure-stat"><strong>{summary ? numberFormat.format(summary.capture_count) : "—"}</strong><span>个个人拍摄单元</span></div>
      </section>
      <section className="metric-grid">
        <article><span>拍摄时间跨度</span><strong className="text-value">{summary?.first_capture?.slice(0, 10) ?? "—"}</strong><small>至 {summary?.last_capture?.slice(0, 10) ?? "—"}</small></article>
        <article><span>已完成质量分析</span><strong>{summary ? numberFormat.format(summary.quality_analyzed) : "—"}</strong><small>平均分 {summary?.average_technical_score ?? "—"}</small></article>
        <article><span>人工保留</span><strong>{summary ? numberFormat.format(summary.user_picks) : "—"}</strong><small>只保存在本地数据库</small></article>
        <article><span>人工待淘汰</span><strong>{summary ? numberFormat.format(summary.user_rejects) : "—"}</strong><small>不会删除原片</small></article>
      </section>
      <section className="statistics-grid">
        <Distribution title="题材占比" rows={statistics?.categories ?? []} labelKey="category" />
        <Distribution title="主要镜头" rows={statistics?.lenses ?? []} labelKey="lens_model" />
        <Distribution title="焦段习惯" rows={statistics?.focal_ranges ?? []} labelKey="bucket" />
        <Distribution title="ISO分布" rows={statistics?.iso_ranges ?? []} labelKey="bucket" />
        <Distribution title="光圈分布" rows={statistics?.aperture_ranges ?? []} labelKey="bucket" />
      </section>
      <section className="panel month-panel">
        <div className="panel-heading"><div><span className="section-kicker">时间趋势</span><h3>最近拍摄月份</h3></div><span className="batch-count">质量分析后显示月度均分</span></div>
        <div className="month-strip">{(statistics?.months ?? []).slice(-24).map((month) => <div key={month.month}><span>{month.month}</span><i style={{ height: `${Math.max(8, Math.min(100, month.count / Math.max(1, ...(statistics?.months ?? []).map((item) => item.count)) * 100))}%` }} /><strong>{month.count}</strong><small>{month.average_score ?? "—"}</small></div>)}</div>
      </section>
    </>
  );
}

function LightroomView({ status, manifest, generateManifest }: {
  status: LightroomStatus | null;
  manifest: LightroomManifest | null;
  generateManifest: () => void;
}) {
  return (
    <>
      <section className="structure-hero lightroom-hero">
        <div><span className="section-kicker">Lightroom Classic</span><h2>后期准备清单</h2><p>汇总已选照片、评级和相册信息。</p><button className="primary-action" onClick={generateManifest}><span>生成准备清单</span><b>→</b></button></div>
        <div className="structure-stat"><strong>{status ? numberFormat.format(status.capture_count) : "—"}</strong><span>个待准备拍摄单元</span></div>
      </section>
      <section className="metric-grid">
        <article><span>相册已确认</span><strong>{status ? `${status.confirmed_events}/${status.event_count}` : "—"}</strong><small>未确认名称仍会标注为建议</small></article>
        <article><span>已有评级</span><strong>{status ? numberFormat.format(status.rated_captures) : "—"}</strong><small>人工星级与技术评级分别保存</small></article>
        <article><span>人工保留</span><strong>{status ? numberFormat.format(status.user_picks) : "—"}</strong><small>准备清单中的pick字段</small></article>
        <article><span>人工待淘汰</span><strong>{status ? numberFormat.format(status.user_rejects) : "—"}</strong><small>只标记，不删除</small></article>
      </section>
      <section className="lightroom-grid">
        <section className="panel safety-panel"><div className="panel-heading"><div><span className="section-kicker">安全状态</span><h3>本轮只生成报告</h3></div></div><div className="safety-list"><div><b>✓</b><span><strong>历史原片不变</strong><small>D:\Photo继续只读保留，不移动、不改名、不改写</small></span></div><div><b>✓</b><span><strong>XMP写入关闭</strong><small>不会在原片旁创建或修改附属文件</small></span></div><div><b>✓</b><span><strong>使用活动图库</strong><small>Lightroom准备清单指向D:\PhotoLibrary\Photos</small></span></div><div><b>✓</b><span><strong>JPG与RAW同步</strong><small>同一拍摄单元共享评级和标签</small></span></div></div></section>
        <section className="panel manifest-panel"><div className="panel-heading"><div><span className="section-kicker">最近生成</span><h3>Lightroom准备文件</h3></div></div>{manifest ? <div className="manifest-result"><strong>{numberFormat.format(manifest.capture_count)} 个拍摄单元</strong><span>{numberFormat.format(manifest.rated_count)} 个已有评级 · {formatBytes(manifest.source_bytes)} 原始文件索引</span><a href={manifest.csv_url}>下载CSV清单</a><a href={manifest.json_url}>下载完整JSON</a><small>下载的是清单，不是照片副本。</small></div> : <div className="empty-state">尚未在本次启动中生成清单。</div>}</section>
      </section>
    </>
  );
}

function MigrationView({ status, task, generatePlan, startMigration, pauseMigration, cancelMigration, resumeMigration, switchLibrary }: {
  status: MigrationStatus | null;
  task: Task | null;
  generatePlan: () => void;
  startMigration: (planId: number, confirmation: string, batchFiles: number, batchGb: number, batchMinutes: number) => void;
  pauseMigration: () => void;
  cancelMigration: () => void;
  resumeMigration: (runId: number) => void;
  switchLibrary: (runId: number, confirmation: string) => void;
}) {
  const plan = status?.plan;
  const [copyConfirmation, setCopyConfirmation] = useState("");
  const [switchConfirmation, setSwitchConfirmation] = useState("");
  const [batchFiles, setBatchFiles] = useState(2000);
  const [batchGb, setBatchGb] = useState(100);
  const [batchMinutes, setBatchMinutes] = useState(240);
  const run = plan?.run;
  const migrationRunning = task?.status === "running" && task.stage.startsWith("migration");
  const migrationPaused = task?.status === "paused" && task.stage.startsWith("migration");
  return (
    <>
      <section className="structure-hero migration-hero">
        <div><span className="section-kicker">只读迁移规划</span><h2>先把每个文件的去向写清楚，晚上再复制。</h2><p>来源固定为D:\Photo，新图库为D:\PhotoLibrary\Photos。现在只生成逐文件清单、检查重名与空间，不创建目标目录，不复制、移动或删除照片。</p><button className="primary-action" onClick={generatePlan}><span>生成最新迁移计划</span><b>→</b></button></div>
        <div className="structure-stat"><strong>{plan ? numberFormat.format(plan.item_count) : "—"}</strong><span>个计划复制文件</span></div>
      </section>
      <section className="metric-grid migration-metrics">
        <article><span>计划数据量</span><strong>{plan ? formatBytes(plan.total_bytes) : "—"}</strong><small>原片仍留在旧目录</small></article>
        <article><span>目标可用空间</span><strong>{plan ? formatBytes(plan.available_bytes) : "—"}</strong><small>D盘当前剩余容量</small></article>
        <article><span>路径冲突</span><strong>{plan ? numberFormat.format(plan.conflict_count) : "—"}</strong><small>必须为0才能执行</small></article>
        <article><span>待人工归类</span><strong>{plan ? numberFormat.format(plan.unassigned_count) : "—"}</strong><small>视频、PSD及附属文件等</small></article>
      </section>
      <section className="migration-grid">
        <section className="panel safety-panel"><div className="panel-heading"><div><span className="section-kicker">安全闸门</span><h3>{run?.status === "switched" ? "迁移审计通过，活动图库已切换" : plan ? (plan.ready ? "计划通过预检查" : "计划暂不能执行") : "等待生成计划"}</h3></div></div><div className="safety-list"><div><b>✓</b><span><strong>旧图库保持原样</strong><small>D:\Photo始终只读保留</small></span></div><div><b>✓</b><span><strong>素材独立保留</strong><small>{plan ? `${numberFormat.format(plan.excluded_count)} 个素材文件不进入个人图库` : "D:\Photo\素材默认排除"}</small></span></div><div><b>{plan?.conflict_count ? "!" : "✓"}</b><span><strong>禁止覆盖同名目标</strong><small>{plan ? `${numberFormat.format(plan.conflict_count)} 个冲突需要处理` : "发现冲突时不会自动改名"}</small></span></div><div><b>✓</b><span><strong>复制执行入口受确认保护</strong><small>只有已审计计划和完整确认文字才能创建任务</small></span></div></div></section>
        <section className="panel manifest-panel"><div className="panel-heading"><div><span className="section-kicker">逐文件清单</span><h3>迁移计划报告</h3></div></div>{plan ? <div className="manifest-result"><strong>计划 #{plan.id}</strong><span>{formatDate(plan.created_at)} · {numberFormat.format(plan.item_count)} 个文件</span><a href={plan.csv_url}>下载CSV清单</a><a href={plan.json_url}>下载完整JSON</a><small>报告明确标记 files_copied=false，今晚确认后才执行。</small></div> : <div className="empty-state">尚未生成迁移计划。</div>}</section>
      </section>
      {plan && <section className="panel migration-execution">
        <div className="panel-heading"><div><span className="section-kicker">执行前摘要</span><h3>复制、校验、审计、再确认切换</h3></div></div>
        <div className="migration-summary">
          <div><span>来源（永久保留）</span><strong>{plan.source_root}</strong></div>
          <div><span>目标（禁止覆盖）</span><strong>{plan.target_root}</strong></div>
          <div><span>逐文件 SHA-256</span><strong>源文件 + 临时目标</strong></div>
          <div><span>完成后</span><strong>全库重新审计，不删除旧原片</strong></div>
        </div>
        {run && <div className="migration-run-status">
          <strong>任务 #{run.id} · {run.status} · 已完成 {numberFormat.format(run.completed_batches)} 批</strong>
          <span>{numberFormat.format(run.verified_count)} 已校验 · {numberFormat.format(run.failed_count)} 失败 · {formatBytes(run.copied_bytes)} 已写入</span>
          <small>每批最多 {numberFormat.format(run.batch_max_files ?? 0)} 个文件 / {run.batch_max_bytes ? formatBytes(run.batch_max_bytes) : "不限数据量"} / {run.batch_max_seconds ? formatDuration(run.batch_max_seconds) : "不限时长"}</small>
          <small>{run.speed_bytes_per_second ? `${formatFileSize(run.speed_bytes_per_second)}/秒 · 预计剩余 ${formatDuration(run.eta_seconds)}` : `全库审计：${run.audit_status}`}</small>
        </div>}
        {!run && <div className="danger-confirmation">
          <div className="batch-config">
            <label><span>每批文件数</span><input type="number" min="1" value={batchFiles} onChange={(event) => setBatchFiles(Math.max(1, Number(event.target.value)))} /></label>
            <label><span>每批数据量（GB）</span><input type="number" min="1" value={batchGb} onChange={(event) => setBatchGb(Math.max(1, Number(event.target.value)))} /></label>
            <label><span>每批最长时间（分钟）</span><input type="number" min="1" value={batchMinutes} onChange={(event) => setBatchMinutes(Math.max(1, Number(event.target.value)))} /></label>
          </div>
          <small>任一上限先达到，就在当前文件完成复制和 SHA-256 校验后自动暂停。</small>
          <label>要创建真实复制任务，请完整输入 <code>{plan.confirmation_phrase}</code></label>
          <input value={copyConfirmation} onChange={(event) => setCopyConfirmation(event.target.value)} placeholder={plan.confirmation_phrase} autoComplete="off" />
          <button className="primary-action" disabled={!plan.ready || copyConfirmation !== plan.confirmation_phrase || migrationRunning} onClick={() => startMigration(plan.id, copyConfirmation, batchFiles, batchGb, batchMinutes)}><span>确认并创建分批复制任务</span><b>→</b></button>
          <small>此按钮会真实创建目标目录并复制照片；不会移动、删除或修改 D:\Photo。</small>
        </div>}
        {run && ["failed", "cancelled"].includes(run.status) && <div className="danger-confirmation"><strong>断点与失败清单已保留</strong><button className="primary-action" onClick={() => resumeMigration(run.id)}><span>继续任务并重试失败文件</span><b>→</b></button></div>}
        {(migrationRunning || migrationPaused) && <div className="task-actions">
          <div className="progress-track"><span style={{ width: `${task?.bytes_total ? Math.min(100, task.bytes_current / task.bytes_total * 100) : 0}%` }} /></div>
          {migrationRunning && <button onClick={pauseMigration}>暂停</button>}
          {(migrationRunning || migrationPaused) && <button onClick={cancelMigration}>安全取消</button>}
          {migrationPaused && run && <button onClick={() => resumeMigration(run.id)}>继续</button>}
        </div>}
        {run?.status === "paused" && !migrationPaused && <div className="danger-confirmation"><strong>上一批已经安全结束</strong><button className="primary-action" onClick={() => resumeMigration(run.id)}><span>开始下一批</span><b>→</b></button><small>服务重启后也可以从这里继续，不会重复复制已校验文件。</small></div>}
        {run?.status === "audited" && <div className="danger-confirmation switch-confirmation">
          <label>全库审计已通过。切换前请再次输入 <code>{plan.switch_confirmation_phrase}</code></label>
          <input value={switchConfirmation} onChange={(event) => setSwitchConfirmation(event.target.value)} placeholder={plan.switch_confirmation_phrase} autoComplete="off" />
          <button className="primary-action" disabled={switchConfirmation !== plan.switch_confirmation_phrase} onClick={() => switchLibrary(run.id, switchConfirmation)}><span>再次确认并切换活动图库</span><b>→</b></button>
          <small>切换只更新活动路径和数据库关联；旧原片仍完整保留。</small>
        </div>}
        {plan.failures.length > 0 && <div className="manifest-result"><strong>{numberFormat.format(plan.failures.length)} 条失败记录（页面最多显示 50 条）</strong>{plan.failure_csv_url && <a href={plan.failure_csv_url}>下载失败 CSV</a>}{plan.failure_json_url && <a href={plan.failure_json_url}>下载失败 JSON</a>}</div>}
      </section>}
      {plan?.sample_conflicts.length ? <section className="panel migration-issues"><div className="panel-heading"><div><span className="section-kicker">需要处理</span><h3>目标路径冲突样例</h3></div></div>{plan.sample_conflicts.map((item) => <div className="migration-issue" key={`${item.source_relative}-${item.target_relative}`}><strong>{item.source_relative}</strong><span>→ {item.target_relative}</span></div>)}</section> : null}
      {plan?.sample_unassigned.length ? <section className="panel migration-issues"><div className="panel-heading"><div><span className="section-kicker">不会猜测</span><h3>待整理文件样例</h3></div></div>{plan.sample_unassigned.map((item) => <div className="migration-issue" key={item.source_relative}><strong>{item.source_relative}</strong><span>→ {item.target_relative}</span></div>)}</section> : null}
    </>
  );
}

function App() {
  const [view, setView] = useState<View>("home");
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = window.localStorage.getItem("tangerine-theme");
    return saved === "dark" ? "dark" : "light";
  });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [libraryCaptures, setLibraryCaptures] = useState<LibraryCapturesResponse | null>(null);
  const [libraryOffset, setLibraryOffset] = useState(0);
  const [libraryQuery, setLibraryQuery] = useState<LibraryQuery>({
    pageSize: 80, albumId: "", category: "", camera: "", lens: "",
    rating: "", selection: "", dateFrom: "", dateTo: "", search: "", sort: "newest",
  });
  const [libraryFilters, setLibraryFilters] = useState<LibraryFilters | null>(null);
  const [albumOffset, setAlbumOffset] = useState(0);
  const [albumPageSize, setAlbumPageSize] = useState(40);
  const [events, setEvents] = useState<EventsResponse | null>(null);
  const [bursts, setBursts] = useState<BurstsResponse | null>(null);
  const [burstOffset, setBurstOffset] = useState(0);
  const [burstPageSize, setBurstPageSize] = useState(40);
  const [analysis, setAnalysis] = useState<AnalysisOverview | null>(null);
  const [aiPreflight, setAiPreflight] = useState<AiPreflight | null>(null);
  const [quality, setQuality] = useState<QualityResponse | null>(null);
  const [qualityOffset, setQualityOffset] = useState(0);
  const [qualityPageSize, setQualityPageSize] = useState(40);
  const [similarityGroups, setSimilarityGroups] = useState<SimilarityGroupsResponse | null>(null);
  const [groupOffset, setGroupOffset] = useState(0);
  const [groupPageSize, setGroupPageSize] = useState(40);
  const [selectedGroup, setSelectedGroup] = useState<SimilarityGroupDetail | null>(null);
  const [captureDetail, setCaptureDetail] = useState<CaptureDetail | null>(null);
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [equipment, setEquipment] = useState<EquipmentCatalog | null>(null);
  const [archive, setArchive] = useState<ArchiveStatus | null>(null);
  const [activeLibraryBaseline, setActiveLibraryBaseline] = useState<ArchiveStatus | null>(null);
  const [lightroomStatus, setLightroomStatus] = useState<LightroomStatus | null>(null);
  const [lightroomManifest, setLightroomManifest] = useState<LightroomManifest | null>(null);
  const [migration, setMigration] = useState<MigrationStatus | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("tangerine-theme", theme);
  }, [theme]);

  const refreshLibrary = useCallback(async () => {
    const libraryParameters = new URLSearchParams({
      limit: String(libraryQuery.pageSize), offset: String(libraryOffset), sort: libraryQuery.sort,
    });
    if (libraryQuery.albumId) libraryParameters.set("album_id", libraryQuery.albumId);
    if (libraryQuery.category) libraryParameters.set("category", libraryQuery.category);
    if (libraryQuery.camera) libraryParameters.set("camera_model", libraryQuery.camera);
    if (libraryQuery.lens) libraryParameters.set("lens_model", libraryQuery.lens);
    if (libraryQuery.rating) libraryParameters.set("rating", libraryQuery.rating);
    if (libraryQuery.selection) libraryParameters.set("selection", libraryQuery.selection);
    if (libraryQuery.dateFrom) libraryParameters.set("date_from", libraryQuery.dateFrom);
    if (libraryQuery.dateTo) libraryParameters.set("date_to", libraryQuery.dateTo);
    if (libraryQuery.search.trim()) libraryParameters.set("search", libraryQuery.search.trim());
    const [overviewData, libraryData, filterData, eventData, burstData, analysisData, preflightData, qualityData, groupData, statisticsData, equipmentData, archiveData, activeBaselineData, lightroomData, migrationData] = await Promise.all([
      getJson<Overview>("/api/overview"),
      getJson<LibraryCapturesResponse>(`/api/library/captures?${libraryParameters.toString()}`),
      getJson<LibraryFilters>("/api/library/filters"),
      getJson<EventsResponse>(`/api/albums?limit=${albumPageSize}&offset=${albumOffset}`),
      getJson<BurstsResponse>(`/api/bursts?limit=${burstPageSize}&offset=${burstOffset}`),
      getJson<AnalysisOverview>("/api/analysis/overview"),
      getJson<AiPreflight>("/api/ai/preflight"),
      getJson<QualityResponse>(`/api/quality?limit=${qualityPageSize}&offset=${qualityOffset}`),
      getJson<SimilarityGroupsResponse>(`/api/similarity-groups?limit=${groupPageSize}&offset=${groupOffset}`),
      getJson<Statistics>("/api/statistics"),
      getJson<EquipmentCatalog>("/api/equipment"),
      getJson<ArchiveStatus>("/api/archive/status"),
      getJson<ArchiveStatus>("/api/active-library/baseline/status"),
      getJson<LightroomStatus>("/api/lightroom/status"),
      getJson<MigrationStatus>("/api/migration/status"),
    ]);
    setOverview(overviewData);
    setLibraryCaptures(libraryData);
    setLibraryFilters(filterData);
    setEvents(eventData);
    setBursts(burstData);
    setAnalysis(analysisData);
    setAiPreflight(preflightData);
    setQuality(qualityData);
    setSimilarityGroups(groupData);
    setStatistics(statisticsData);
    setEquipment(equipmentData);
    setArchive(archiveData);
    setActiveLibraryBaseline(activeBaselineData);
    setLightroomStatus(lightroomData);
    setMigration(migrationData);
  }, [albumOffset, albumPageSize, burstOffset, burstPageSize, groupOffset, groupPageSize, libraryOffset, libraryQuery, qualityOffset, qualityPageSize]);

  useEffect(() => {
    Promise.all([refreshLibrary(), getJson<Task>("/api/tasks/current").then(setTask)]).catch(
      (reason: Error) => setError(reason.message),
    );
  }, [refreshLibrary]);

  useEffect(() => {
    if (task?.status !== "running") return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getJson<Task>("/api/tasks/current");
        setTask(next);
        if (next.status !== "running") await refreshLibrary();
      } catch (reason) {
        setError((reason as Error).message);
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [task?.status, refreshLibrary]);

  const startScan = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/scan", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const cancelTask = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/tasks/current/cancel", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startVisual = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/visual/analyze", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startQuality = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/quality/analyze", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startAi = async (mode: "benchmark" | "recommended", limit: number) => {
    if (mode === "recommended" && !window.confirm(`将分析最多 ${limit} 张推荐照片。任务可暂停、继续和取消，确认现在加载本地模型吗？`)) return;
    setError(null);
    try {
      setTask(await getJson<Task>("/api/ai/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, limit }),
      }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const pauseAi = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/ai/runs/current/pause", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const resumeAi = async (runId: number) => {
    setError(null);
    try {
      setTask(await getJson<Task>(`/api/ai/runs/${runId}/resume`, { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const retryAiFailures = async (runId: number) => {
    setError(null);
    try {
      setTask(await getJson<Task>(`/api/ai/runs/${runId}/retry-failures`, { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const saveReview = async (captureId: number, review: ReviewPayload) => {
    setError(null);
    try {
      await getJson(`/api/reviews/${captureId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(review),
      });
      setQuality((current) => current ? {
        ...current,
        items: current.items.map((item) => item.capture_id === captureId ? {
          ...item,
          user_rating: review.user_rating,
          user_pick: Number(review.user_pick),
          user_reject: Number(review.user_reject),
          user_note: review.user_note,
        } : item),
      } : current);
      setSelectedGroup((current) => current ? {
        ...current,
        items: current.items.map((item) => item.capture_id === captureId ? {
          ...item,
          user_rating: review.user_rating,
          user_pick: Number(review.user_pick),
          user_reject: Number(review.user_reject),
          user_note: review.user_note,
        } : item),
      } : current);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const saveAiReview = async (analysisId: number, verdict: "accurate" | "partial" | "inaccurate" | null, note: string | null) => {
    setError(null);
    try {
      const saved = await getJson<{ user_verdict: "accurate" | "partial" | "inaccurate" | null; user_note: string | null; reviewed_at: string | null }>(`/api/ai/analyses/${analysisId}/review`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_verdict: verdict, user_note: note }),
      });
      setCaptureDetail((current) => current ? {
        ...current,
        ai_analyses: current.ai_analyses.map((item) => item.id === analysisId ? { ...item, ...saved } : item),
      } : current);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const openGroup = async (groupId: number) => {
    setError(null);
    try {
      setSelectedGroup(await getJson<SimilarityGroupDetail>(`/api/similarity-groups/${groupId}`));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const openCapture = async (captureId: number) => {
    setError(null);
    try {
      setCaptureDetail(await getJson<CaptureDetail>(`/api/captures/${captureId}`));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const createBaseline = async () => {
    if (!window.confirm("建立新的原片逻辑基线？这只记录当前索引，不读取、复制或修改照片。")) return;
    setError(null);
    try {
      await getJson("/api/archive/baselines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setArchive(await getJson<ArchiveStatus>("/api/archive/status"));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const createActiveBaseline = async () => {
    if (!window.confirm("为当前活动图库建立新的逻辑基线？这不会读取文件内容或修改照片。")) return;
    setError(null);
    try {
      await getJson("/api/active-library/baselines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setActiveLibraryBaseline(await getJson<ArchiveStatus>("/api/active-library/baseline/status"));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const updateEvent = async (event: EventItem, changes: Partial<Pick<EventItem, "proposed_name" | "category" | "status">>) => {
    setError(null);
    const next = { ...event, ...changes };
    try {
      await getJson(`/api/albums/${event.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposed_name: next.proposed_name, category: next.category, status: next.status }),
      });
      setEvents((current) => current ? { ...current, items: current.items.map((item) => item.id === event.id ? next : item) } : current);
      setLightroomStatus((current) => current ? { ...current, confirmed_events: current.confirmed_events + (event.status !== "confirmed" && next.status === "confirmed" ? 1 : event.status === "confirmed" && next.status !== "confirmed" ? -1 : 0) } : current);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const createAlbum = async (name: string, category: string) => {
    setError(null);
    try {
      await getJson("/api/albums", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, category }),
      });
      setAlbumOffset(0);
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const createAlbumType = async (name: string) => {
    setError(null);
    try {
      await getJson("/api/album-types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const deleteAlbumType = async (name: string) => {
    setError(null);
    try {
      await getJson(`/api/album-types/${encodeURIComponent(name)}`, { method: "DELETE" });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const renameAlbumType = async (name: string, nextName: string) => {
    setError(null);
    try {
      await getJson(`/api/album-types/${encodeURIComponent(name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName }),
      });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const assignToAlbum = async (albumId: number, captureIds: number[]) => {
    setError(null);
    try {
      await getJson(`/api/albums/${albumId}/captures`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capture_ids: captureIds }),
      });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const generateManifest = async () => {
    setError(null);
    try {
      setLightroomManifest(await getJson<LightroomManifest>("/api/lightroom/manifest", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const exportPhoneShare = async (captureIds: number[], maxEdge: number) => {
    setError(null);
    try {
      return await getJson<PhoneShareExport>("/api/exports/phone-share", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capture_ids: captureIds, max_edge: maxEdge, quality: 90 }),
      });
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const generateMigrationPlan = async () => {
    if (!window.confirm("现在只生成迁移清单并检查冲突，不会创建目录或复制照片。继续吗？")) return;
    setError(null);
    try {
      setMigration(await getJson<MigrationStatus>("/api/migration/plans", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startMigration = async (planId: number, confirmation: string, batchFiles: number, batchGb: number, batchMinutes: number) => {
    if (!window.confirm("这会真实创建 D:\\PhotoLibrary\\Photos 并开始复制，但不会移动或删除 D:\\Photo。确认启动吗？")) return;
    setError(null);
    try {
      setTask(await getJson<Task>("/api/migration/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_id: planId,
          confirmation,
          batch_max_files: batchFiles,
          batch_max_gb: batchGb,
          batch_max_minutes: batchMinutes,
        }),
      }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const pauseMigration = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/migration/runs/current/pause", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const resumeMigration = async (runId: number) => {
    setError(null);
    try {
      setTask(await getJson<Task>(`/api/migration/runs/${runId}/resume`, { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const switchLibrary = async (runId: number, confirmation: string) => {
    if (!window.confirm("最后确认：将活动图库切换到新路径。旧原片不会删除，确认继续吗？")) return;
    setError(null);
    try {
      await getJson("/api/migration/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, confirmation }),
      });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const pageMeta = {
    home: ["OVERVIEW", "首页概览", ""],
    library: ["LIBRARY", "照片图库", "浏览、整理并管理全部拍摄单元"],
    bursts: ["REVIEW", "连拍选片", "比较连拍与相似画面，留下真正需要的版本"],
    analysis: ["ANALYSIS / REVIEW", "质量分析", "批量运行技术检测与本地模型，在单张详情中复核结果"],
    statistics: ["STATISTICS", "摄影统计", "从器材、参数和选片结果理解拍摄习惯"],
    equipment: ["EQUIPMENT", "设备管理", "器材档案与实际使用统计"],
    lightroom: ["OUTPUT", "后期输出", "检查评分与相册后生成 Lightroom 只读准备清单"],
    archive: ["SYSTEM / SAFETY", "原片保护", "核对历史档案与活动图库完整性"],
    migration: ["SYSTEM / MIGRATION", "图库迁移", "查看迁移记录、校验和活动图库状态"],
  }[view];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">T</span><div><strong>Tangerine</strong><span>Photo Assistant</span></div></div>
        <nav aria-label="主要功能">
          <span className="nav-group-label">照片管理</span>
          <button className={`nav-item ${view === "home" ? "active" : ""}`} onClick={() => setView("home")}><span>首</span>首页概览</button>
          <button className={`nav-item ${view === "library" ? "active" : ""}`} onClick={() => setView("library")}><span>图</span>照片图库</button>
          <button className={`nav-item ${view === "bursts" ? "active" : ""}`} onClick={() => setView("bursts")}><span>选</span>连拍选片</button>
          <span className="nav-group-label system-label">分析学习</span>
          <button className={`nav-item ${view === "analysis" ? "active" : ""}`} onClick={() => setView("analysis")}><span>析</span>质量分析</button>
          <button className={`nav-item ${view === "statistics" ? "active" : ""}`} onClick={() => setView("statistics")}><span>统</span>摄影统计</button>
          <span className="nav-group-label system-label">工具</span>
          <button className={`nav-item ${view === "equipment" ? "active" : ""}`} onClick={() => setView("equipment")}><span>器</span>设备管理</button>
          <button className={`nav-item ${view === "lightroom" ? "active" : ""}`} onClick={() => setView("lightroom")}><span>出</span>后期输出</button>
          <span className="nav-group-label system-label">系统</span>
          <button className={`nav-item ${view === "archive" ? "active" : ""}`} onClick={() => setView("archive")}><span>护</span>原片保护</button>
          <button className={`nav-item ${view === "migration" ? "active" : ""}`} onClick={() => setView("migration")}><span>迁</span>图库迁移</button>
        </nav>
        <div className="privacy-note"><span className="status-dot" /><div><strong>本地离线</strong><small>照片与人脸数据不离开电脑</small></div></div>
      </aside>

      <main>
        <header className="topbar">
          <div><span className="eyebrow">{pageMeta[0]}</span><h1>{pageMeta[1]}</h1></div>
          <div className="topbar-tools">
            <button className="theme-toggle" onClick={() => setTheme((current) => current === "light" ? "dark" : "light")} aria-label={`切换到${theme === "light" ? "深色" : "浅色"}主题`}>
              <span aria-hidden="true">{theme === "light" ? "☀" : "◐"}</span>
              {theme === "light" ? "浅色" : "深色"}
            </button>
            <div className="scan-meta"><span>上次扫描</span><strong>{formatDate(overview?.latest_scan?.finished_at)}</strong></div>
          </div>
        </header>
        {error && <div className="error-banner" role="alert">{error}</div>}
        {view === "home" && <HomeView overview={overview} events={events} groups={similarityGroups} analysis={analysis} statistics={statistics} library={libraryCaptures} task={task} navigate={setView} openCapture={openCapture} />}
        {view === "library" && <LibraryView
          library={libraryCaptures} albums={events} filters={libraryFilters} query={libraryQuery}
          updateQuery={(changes) => { setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, ...changes })); }}
          task={task} startScan={startScan} cancelTask={cancelTask} updateAlbum={updateEvent}
          createAlbum={createAlbum} createAlbumType={createAlbumType} renameAlbumType={renameAlbumType} deleteAlbumType={deleteAlbumType} assignToAlbum={assignToAlbum}
          openCapture={openCapture} exportPhotos={exportPhoneShare} changePage={setLibraryOffset}
          changePageSize={(limit) => { setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, pageSize: limit })); }}
          changeAlbumPage={setAlbumOffset} changeAlbumPageSize={(limit) => { setAlbumOffset(0); setAlbumPageSize(limit); }}
          openAlbum={(albumId) => { setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: String(albumId) })); }}
        />}
        {view === "bursts" && <BurstsView overview={overview} bursts={bursts} groups={similarityGroups} selectedGroup={selectedGroup} task={task} startVisual={startVisual} openGroup={openGroup} closeGroup={() => setSelectedGroup(null)} openCapture={openCapture} saveReview={saveReview} cancelTask={cancelTask} changeGroupPage={setGroupOffset} changeGroupPageSize={(limit) => { setGroupOffset(0); setGroupPageSize(limit); }} changeBurstPage={setBurstOffset} changeBurstPageSize={(limit) => { setBurstOffset(0); setBurstPageSize(limit); }} />}
        {view === "analysis" && <AnalysisView analysis={analysis} preflight={aiPreflight} quality={quality} task={task} startQuality={startQuality} startAi={startAi} saveReview={saveReview} cancelTask={cancelTask} pauseAi={pauseAi} resumeAi={resumeAi} retryAiFailures={retryAiFailures} openCapture={openCapture} changeQualityPage={setQualityOffset} changeQualityPageSize={(limit) => { setQualityOffset(0); setQualityPageSize(limit); }} />}
        {view === "statistics" && <StatisticsView statistics={statistics} />}
        {view === "equipment" && <EquipmentView equipment={equipment} />}
        {view === "archive" && <ArchiveView archive={archive} activeLibrary={activeLibraryBaseline} createBaseline={createBaseline} createActiveBaseline={createActiveBaseline} />}
        {view === "migration" && <MigrationView status={migration} task={task} generatePlan={generateMigrationPlan} startMigration={startMigration} pauseMigration={pauseMigration} cancelMigration={cancelTask} resumeMigration={resumeMigration} switchLibrary={switchLibrary} />}
        {view === "lightroom" && <LightroomView status={lightroomStatus} manifest={lightroomManifest} generateManifest={generateManifest} />}
        {captureDetail && <CaptureDetailPanel detail={captureDetail} close={() => setCaptureDetail(null)} saveAiReview={saveAiReview} />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
