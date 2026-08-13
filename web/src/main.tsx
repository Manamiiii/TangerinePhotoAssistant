import { StrictMode, useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type View = "home" | "library" | "bursts" | "analysis" | "statistics" | "equipment" | "lightroom" | "archive" | "settings";
type LibrarySection = "photos" | "albums";
type PhotoLayout = "list" | "small" | "medium" | "large";
type Theme = "light" | "dark";
type CountRow = { count: number } & Record<string, string | number | null>;

type StructureSummary = {
  event_count: number;
  unconfirmed_event_count: number;
  unassigned_capture_count: number;
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
  user_note: string | null;
  similarity_group_id: number | null;
  similarity_group_size: number | null;
  item_type: "photo" | "group";
  selection_capture_ids: number[];
  group_pick_count: number | null;
  group_reject_count: number | null;
  group_unreviewed_count: number | null;
  grouping_override: "exclude" | "split_before" | null;
  size_bytes: number;
  thumbnail_url: string;
};
type LibraryCapturesResponse = { count: number; limit: number; offset: number; collapsed: boolean; items: LibraryCapture[] };
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
  quality: string;
  dateFrom: string;
  dateTo: string;
  search: string;
  sort: string;
  collapseGroups: boolean;
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
  pick_count: number;
  reject_count: number;
  review_status: "pending" | "picked" | "skipped";
  thumbnail_url: string;
};
type SimilarityAlbumSummary = { id: number; name: string; category: string; total_count: number; pending_count: number };
type SimilarityGroupsResponse = { count: number; limit: number; offset: number; items: SimilarityGroupItem[]; total_count: number; pending_count: number; albums: SimilarityAlbumSummary[] };

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
  grouping_override: "exclude" | "split_before" | null;
  manual_batch_key: string | null;
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
  shadow_clip_pct: number | null;
  highlight_clip_pct: number | null;
  histogram: number[] | null;
  auto_rating: number | null;
  user_rating: number | null;
  user_pick: number | null;
  user_reject: number | null;
  user_note: string | null;
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
    gps_latitude: number | null;
    gps_longitude: number | null;
    metering_mode: string | null;
    white_balance: string | null;
    flash: string | null;
    focus_mode: string | null;
    film_simulation: string | null;
    dynamic_range: string | null;
    exposure_program: string | number | null;
    exposure_mode: string | number | null;
    shutter_type: string | number | null;
    orientation: string | number | null;
    captured_at_precise: string | null;
    timezone_offset: string | null;
    color_space: string | number | null;
    bits_per_sample: string | number | number[] | null;
    image_quality: string | number | null;
    image_stabilization: string | number | number[] | null;
    drive_mode: string | number | null;
    drive_speed: string | number | null;
    sequence_number: string | number | null;
    auto_bracketing: string | number | null;
    af_mode: string | number | null;
    af_area_mode: string | number | null;
    focus_pixel: string | number | number[] | null;
    blur_warning: string | number | null;
    focus_warning: string | number | null;
    exposure_warning: string | number | null;
    faces_detected: string | number | null;
    roll_angle: string | number | null;
    camera_elevation_angle: string | number | null;
    white_balance_fine_tune: string | number | number[] | null;
    highlight_tone: string | number | null;
    shadow_tone: string | number | null;
    saturation: string | number | null;
    camera_sharpness: string | number | null;
    noise_reduction: string | number | null;
    clarity: string | number | null;
    color_chrome_effect: string | number | null;
    color_chrome_fx_blue: string | number | null;
    grain_effect_roughness: string | number | null;
    grain_effect_size: string | number | null;
    lens_modulation_optimizer: string | number | null;
    auto_dynamic_range: string | number | null;
    raw_compression: string | number | null;
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
  detail_data: { metadata_profile_version: number; metadata_pending: number; histograms_pending: number };
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
  thumbnail_url: string;
  issues: Array<{ code: string; severity: string; message: string }>;
  ai_result: {
    subject_type?: string;
    quality_summary?: string;
    photoshop_needed?: boolean;
    shooting_advice?: Array<{ suggestion?: string; reason?: string }>;
    lightroom_suggestions?: Array<{ adjustment?: string; direction?: string; reason?: string }>;
  } | null;
};
type QualityResponse = { count: number; limit: number; offset: number; items: QualityItem[] };
type QualityReviewFilter = "all" | "problems" | "low_score" | "with_model" | "without_model" | "unrated";
type PhotoInboxStatus = { path: string; exists: boolean; can_open: boolean };
type SystemCapabilities = {
  platform: string;
  library_root: string;
  workspace_root: string;
  metadata: { level: "basic" | "full"; exiftool: boolean; message: string };
  ai: { ready: boolean; message: string };
  features: {
    open_folder: boolean;
    raw_pairing: boolean;
    lightroom_manifest: boolean;
    phone_share_export: boolean;
  };
  safety: {
    offline_only: boolean;
    library_read_only: boolean;
    allow_move: boolean;
    allow_delete: boolean;
    allow_original_metadata_write: boolean;
  };
};
type EditableSettings = {
  library: { originals: string; workspace: string };
  cache: { root: string; max_size_gb: number; thumbnail_max_size_gb: number };
  analysis: { raw_extensions: string[]; burst_time_gap_seconds: number; metadata_batch_size: number };
  tools: { exiftool: string };
  models: {
    python: string;
    vision_language_model: string;
    quantization: "none" | "int8";
    gpu_memory_limit_gb: number;
    max_new_tokens: number;
    image_max_edge: number;
  };
};
type SettingsStatus = {
  configured: EditableSettings;
  effective: SystemCapabilities;
  restart_required: boolean;
  backup_path: string | null;
  message?: string;
};
type ReviewPayload = {
  user_rating: number | null;
  user_pick: boolean;
  user_reject: boolean;
  user_note: string | null;
};
type Toast = { id: number; kind: "success" | "error"; message: string; actionLabel?: string; action?: () => void };
type SimilarityRevision = {
  id: number;
  operation: string;
  label: string;
  created_at: string;
  group_count: number;
  excluded_count: number;
  automatic: boolean;
  representative_capture_id: number;
  album_names: string[];
  can_undo: boolean;
};

function similarityGroupsUrl(limit: number, offset: number, reviewFilter: "all" | "pending", albumId: string) {
  const parameters = new URLSearchParams({ limit: String(limit), offset: String(offset), review_filter: reviewFilter });
  if (albumId) parameters.set("album_id", albumId);
  return `/api/similarity-groups?${parameters}`;
}

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
  cameras: Array<StatisticRow & { camera_model: string }>;
  lenses: Array<StatisticRow & { lens_model: string; user_picks: number; pick_rate: number | null }>;
  focal_ranges: Array<StatisticRow & { bucket: string }>;
  iso_ranges: Array<StatisticRow & { bucket: string }>;
  aperture_ranges: Array<StatisticRow & { bucket: string }>;
  shutter_ranges: Array<StatisticRow & { bucket: string }>;
  exposure_compensation_ranges: Array<StatisticRow & { bucket: string }>;
  ratings: Array<{ rating: number; count: number; user_rated: number }>;
  issues: Array<{ code: string; message: string; count: number }>;
  selection: {
    group_total: number;
    groups_reviewed: number | null;
    average_picks_per_group: number | null;
  } | null;
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
    checked_at?: string;
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
  result: { scan_run_id?: number; album_id?: number; assigned_count?: number } | null;
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

function technicalGrade(score: number | null | undefined) {
  if (score == null) return "—";
  if (score >= 85) return "A+";
  if (score >= 75) return "A";
  if (score >= 60) return "B";
  if (score >= 45) return "C";
  return "D";
}

function technicalAdvice(code: string) {
  return ({
    slow_shutter_risk: "下次可提高快门速度、开启防抖或使用三脚架；先确认主体是否有运动。",
    high_iso: "优先增加环境光或使用更大光圈；降噪时注意保留纹理。",
    highlight_clipping: "Lightroom 可先降低高光和白色色阶；下次拍摄可适当负曝光补偿。",
    deep_shadows: "确认是否为有意剪影；需要恢复时先小幅提亮阴影并控制噪点。",
    low_global_detail: "放大检查主体焦点；下次提高快门或缩小一点光圈，避免只靠锐化补救。",
    jpeg_stream_recovered: "检查画面边缘是否完整，并从存储卡重新复制原文件进行比对。",
  } as Record<string, string>)[code] ?? "打开照片查看证据，再结合拍摄意图决定是否调整。";
}

function modelAdvice(result: QualityItem["ai_result"]) {
  const shooting = result?.shooting_advice?.[0];
  if (shooting) return [shooting.suggestion, shooting.reason].filter(Boolean).join("：");
  const lightroom = result?.lightroom_suggestions?.[0];
  if (lightroom) return [lightroom.adjustment, lightroom.direction, lightroom.reason].filter(Boolean).join(" · ");
  return result?.quality_summary ?? "打开详情查看完整模型建议。";
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
    <span>共 {numberFormat.format(count)} 条</span>
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
        <div className="task-actions"><div className="progress-track"><span style={{ width: `${progress ?? 22}%` }} className={progress === null ? "indeterminate" : ""} /></div>{pause && task.pausable && task.status === "running" && <button onClick={pause}>安全暂停</button>}{cancel && <button onClick={cancel}>安全取消</button>}</div>
      )}
      {task.status === "paused" && cancel && (
        <div className="task-actions"><div className="progress-track"><span style={{ width: `${progress ?? 0}%` }} /></div><button onClick={cancel}>取消剩余任务</button></div>
      )}
    </section>
  );
}

function taskBelongsTo(task: Task | null, area: "library" | "visual" | "analysis") {
  if (!task || task.status === "idle") return false;
  const stage = task.stage.toLocaleLowerCase();
  const message = task.message;
  if (area === "visual") return ["duplicates", "fingerprints"].includes(stage) || /视觉预筛|相似分组|画面指纹|精确重复/.test(message);
  if (area === "analysis") return stage === "quality" || stage.startsWith("detail-") || stage.startsWith("ai-") || /技术质量|详情数据|扩展拍摄信息|直方图|模型任务|本地模型|Qwen/.test(message);
  return ["indexing", "metadata", "pairing", "structure"].includes(stage) || /图库更新|核对文件|扫描|相册/.test(message);
}

function ModalShell({ title, close, children, wide = false }: { title: string; close: () => void; children: ReactNode; wide?: boolean }) {
  return <div className="editor-backdrop" role="dialog" aria-modal="true" aria-label={title} onClick={close}>
    <section className={`editor-modal ${wide ? "wide" : ""}`} onClick={(event) => event.stopPropagation()}>
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
      <section className="panel event-panel album-panel">
        <div className="panel-heading"><div><h3>全部相册</h3><span className="batch-count">{numberFormat.format(albums?.count ?? 0)} 个 · 按最近拍摄时间排列</span></div><button className="toolbar-button primary" onClick={() => openAlbumEditor("new")}>新建相册</button></div>
        <div className="event-list">
          {(albums?.items ?? []).map((album) => (
            <article className="event-row album-row" key={album.id}>
              <div className={`category-chip category-${album.category}`}>{album.category}</div>
              <div className="event-main"><strong>{album.proposed_name}</strong><span>{album.source_count ? `${album.source_count} 个来源目录` : "手动创建"}</span></div>
              <div className="event-measure"><strong>{numberFormat.format(album.capture_count)}</strong><span>照片</span></div>
              <div className="album-date"><strong>{album.start_at?.slice(0, 10) ?? "—"}</strong><span>拍摄日期</span></div>
              <div className="album-row-actions"><button onClick={() => openAlbumEditor(album)}>编辑</button><button className={album.status === "confirmed" ? "confirmed" : ""} disabled={album.status === "confirmed"} onClick={() => updateAlbum(album, { status: "confirmed" })}>{album.status === "confirmed" ? "已确认" : "确认"}</button><button className="album-open-action" onClick={() => openAlbum(album.id)}>打开照片</button></div>
            </article>
          ))}
          {!albums?.items.length && <div className="empty-state">还没有相册，可以新建一个空相册。</div>}
        </div>
      </section>
      {albums && <Pagination count={albums.count} limit={albums.limit} offset={albums.offset} onChange={changePage} onLimitChange={changePageSize} />}
      <section className="panel album-types-panel">
        <div className="panel-heading"><div><h3>相册类型</h3></div><span className="batch-count">用于筛选和归类相册</span></div>
        <div className="type-manager-list">
          {(filters?.album_types ?? []).map((type) => <div className="type-manager-row" key={type.name}>
            {editingType === type.name ? <input autoFocus value={editedTypeName} onChange={(event) => setEditedTypeName(event.target.value)} /> : <div><strong>{type.name}</strong><span>{type.built_in ? "内置类型" : "自定义类型"}</span></div>}
            <div>{!type.built_in && (editingType === type.name ? <><button onClick={() => { if (editedTypeName.trim()) renameAlbumType(type.name, editedTypeName.trim()); setEditingType(null); }}>保存</button><button onClick={() => setEditingType(null)}>取消</button></> : <><button onClick={() => { setEditingType(type.name); setEditedTypeName(type.name); }}>编辑</button><button className="danger-text" onClick={() => deleteAlbumType(type.name)}>删除</button></>)}</div>
          </div>)}
        </div>
        <form className="type-create-row" onSubmit={(event) => { event.preventDefault(); if (newTypeName.trim()) { createAlbumType(newTypeName.trim()); setNewTypeName(""); } }}><input value={newTypeName} onChange={(event) => setNewTypeName(event.target.value)} placeholder="新的类型名称" maxLength={40} /><button className="toolbar-button primary" disabled={!newTypeName.trim()}>新增类型</button></form>
      </section>
      {albumEditor && <ModalShell title={albumEditor === "new" ? "新建相册" : "编辑相册"} close={() => setAlbumEditor(null)}>
        <form className="editor-form" onSubmit={(event) => { event.preventDefault(); saveAlbum(); }}>
          <label><span>相册名称</span><input autoFocus value={albumName} onChange={(event) => setAlbumName(event.target.value)} maxLength={180} /></label>
          <label><span>相册类型</span><select value={albumCategory} onChange={(event) => setAlbumCategory(event.target.value)}>{(filters?.album_types ?? []).map((type) => <option key={type.name}>{type.name}</option>)}</select></label>
          <footer><button type="button" className="toolbar-button" onClick={() => setAlbumEditor(null)}>取消</button><button className="toolbar-button primary" disabled={!albumName.trim() || !albumCategory}>保存</button></footer>
        </form>
      </ModalShell>}
    </>
  );
}

function BurstsView({ groups, selectedGroup, task, startVisual, openGroup, closeGroup, openCapture, saveReview, editGrouping, saveGrouping, restoreGroupingRevision, cancelTask, changeGroupPage, changeGroupPageSize, reviewFilter, setReviewFilter, albumId, setAlbumId }: {
  groups: SimilarityGroupsResponse | null;
  selectedGroup: SimilarityGroupDetail | null;
  task: Task | null;
  startVisual: () => void;
  openGroup: (groupId: number) => void;
  closeGroup: () => void;
  openCapture: (captureId: number, context?: number[]) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  editGrouping: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  saveGrouping: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<{ revision_id: number; group_ids: number[] }>;
  restoreGroupingRevision: (revisionId: number, useBefore?: boolean) => Promise<void>;
  cancelTask: () => void;
  changeGroupPage: (offset: number) => void;
  changeGroupPageSize: (limit: number) => void;
  reviewFilter: "all" | "pending";
  setReviewFilter: (filter: "all" | "pending") => void;
  albumId: string;
  setAlbumId: (albumId: string) => void;
}) {
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [albumUndo, setAlbumUndo] = useState<SimilarityRevision | null>(null);
  const groupItems = groups?.items ?? [];
  const currentIndex = selectedGroup ? groupItems.findIndex((item) => item.id === selectedGroup.id) : -1;
  const nextPending = groupItems.find((item, index) => index > currentIndex && item.review_status === "pending")
    ?? groupItems.find((item, index) => index !== currentIndex && item.review_status === "pending");
  const statusLabels = { pending: "待选", picked: "已选定", skipped: "已排除" } as const;
  const completedCount = Math.max(0, (groups?.total_count ?? 0) - (groups?.pending_count ?? 0));
  const completionPercent = groups?.total_count ? Math.round(completedCount / groups.total_count * 100) : 0;
  const selectedAlbum = groups?.albums.find((album) => String(album.id) === albumId) ?? null;
  useEffect(() => {
    setAlbumUndo(null);
    if (!albumId || selectedGroup) return;
    const controller = new AbortController();
    getJson<{ items: SimilarityRevision[] }>(`/api/similarity-group-revisions?album_id=${albumId}&limit=100`, { signal: controller.signal })
      .then((result) => setAlbumUndo(result.items.find((revision) => revision.can_undo) ?? null))
      .catch((reason: Error) => { if (reason.name !== "AbortError") setAlbumUndo(null); });
    return () => controller.abort();
  }, [albumId, groups, selectedGroup]);
  useEffect(() => {
    setEditingGroupId(null);
  }, [selectedGroup?.id]);
  return (
    <>
      <section className="structure-hero burst-hero">
        <div><span className="section-kicker">照片挑选</span><h2>相似照片分组</h2><p>比较连拍和相似画面。</p><button className="primary-action" onClick={startVisual} disabled={task?.status === "running"}><span>{task?.status === "running" ? "分析进行中" : "更新相似分组"}</span><b aria-hidden="true">→</b></button></div>
        <div className="structure-stat"><strong>{groups ? numberFormat.format(groups.pending_count) : "—"}</strong><span>组待选 / 共 {groups ? numberFormat.format(groups.total_count) : "—"} 组</span><small>已完成 {completionPercent}%</small></div>
      </section>
      <TaskCard task={taskBelongsTo(task, "visual") ? task : null} cancel={cancelTask} />
      {selectedGroup ? (
        <section className="panel comparison-panel">
          <div className="panel-heading comparison-heading">
            <div><button className="back-navigation" onClick={closeGroup}>← 返回相似组</button><span className="section-kicker">组内对比</span><h3>{selectedGroup.event_name}</h3></div>
            {editingGroupId !== selectedGroup.id && nextPending && <button className="toolbar-button primary next-group-action" onClick={() => openGroup(nextPending.id)}>下一组待选 →</button>}
          </div>
          {editingGroupId === selectedGroup.id ? <SimilarityGroupingEditor key={selectedGroup.id} group={selectedGroup} cancel={() => setEditingGroupId(null)} save={saveGrouping} restore={(captureId) => editGrouping(captureId, "auto")} restoreRevision={restoreGroupingRevision} /> : <>
          <div className="comparison-note comparison-context"><span>共 {selectedGroup.capture_count} 张 · 按拍摄顺序排列 · 点击图片查看完整参数</span><button className="toolbar-button" onClick={() => setEditingGroupId(selectedGroup.id)}>调整这一组</button></div>
          <div className="comparison-grid">
            {selectedGroup.items.map((item) => (
              <article className={`comparison-card ${item.auto_pick ? "auto-pick" : ""} ${item.user_pick ? "user-pick" : ""} ${item.user_reject ? "user-reject" : ""}`} key={item.capture_id} onClick={() => openCapture(item.capture_id, selectedGroup.items.map((member) => member.capture_id))}>
                <div className="photo-frame">
                  <img src={item.thumbnail_url} loading="lazy" alt={`${item.stem} 缩略图`} />
                  {item.auto_pick ? <span className="photo-flag">技术推荐</span> : null}
                  {item.user_pick ? <span className="photo-flag user">组内入选</span> : null}
                </div>
                <div className="photo-card-copy"><strong>{item.stem}</strong><span>{item.technical_score == null ? "尚未评分" : `技术分 ${Math.round(item.technical_score)}`} · {formatExposure(item.exposure_time)} · ISO {item.iso ?? "—"}</span></div>
                <div className="photo-review" onClick={(event) => event.stopPropagation()}>
                  <select aria-label={`${item.stem} 人工星级`} value={item.user_rating ?? ""} onChange={(event) => saveReview(item.capture_id, { user_rating: event.target.value ? Number(event.target.value) : null, user_pick: Boolean(item.user_pick), user_reject: Boolean(item.user_reject), user_note: item.user_note })}>
                    <option value="">星级</option><option value="1">1★</option><option value="2">2★</option><option value="3">3★</option><option value="4">4★</option><option value="5">5★</option>
                  </select>
                  <button className={item.user_pick ? "selected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: !item.user_pick, user_reject: false, user_note: item.user_note })}>入选</button>
                  <button className={item.user_reject ? "rejected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: false, user_reject: !item.user_reject, user_note: item.user_note })}>排除</button>
                </div>
              </article>
            ))}
          </div></>}
        </section>
      ) : !albumId ? (
        <section className="panel album-selection-panel">
          <div className="panel-heading"><div><span className="section-kicker">第一步</span><h3>选择要处理的相册</h3><p>连拍和相似画面始终在相册内部处理，不会跨相册混合。</p></div><span className="batch-count">{groups?.albums.length ?? 0} 个相册包含相似组</span></div>
          <div className="similarity-album-grid">{(groups?.albums ?? []).map((album) => { const done = album.total_count - album.pending_count; const percent = album.total_count ? Math.round(done / album.total_count * 100) : 0; return <button key={album.id} onClick={() => setAlbumId(String(album.id))}><span><small>{album.category}</small><strong>{album.name}</strong></span><b><strong>{album.pending_count}</strong><small>待选</small></b><i><span style={{ width: `${percent}%` }} /></i><em>共 {album.total_count} 组 · 已完成 {percent}%</em></button>; })}</div>
          {!groups?.albums.length && <div className="empty-state">还没有可处理的相似组，请先更新相似分组。</div>}
        </section>
      ) : (
        <section className="panel similarity-panel">
          <div className="similarity-album-context"><button className="back-navigation" onClick={() => setAlbumId("")}>← 更换相册</button><div><span className="section-kicker">当前相册</span><h3>{selectedAlbum?.name ?? "相册选片"}</h3></div><div><strong>{groups?.pending_count ?? 0}</strong><span>组待选 / 共 {groups?.total_count ?? 0} 组</span></div></div>
          {albumUndo && <div className="similarity-recovery-bar"><span>本相册最近一次人工分组仍可撤销</span><button className="toolbar-button" onClick={() => { if (window.confirm("撤销本相册最近一次人工分组调整？")) void restoreGroupingRevision(albumUndo.id, true); }}>撤销最近调整</button></div>}
          <div className="similarity-list-controls"><div className="burst-view-toggle" role="tablist" aria-label="选片进度筛选"><button className={reviewFilter === "pending" ? "active" : ""} onClick={() => setReviewFilter("pending")}>只看待选</button><button className={reviewFilter === "all" ? "active" : ""} onClick={() => setReviewFilter("all")}>全部分组</button></div><span className="batch-count">当前显示 {numberFormat.format(groups?.count ?? 0)} 组 · 点击进入对比</span></div>
          <div className="similarity-grid">
            {groupItems.map((group) => (
              <button className="similarity-card" key={group.id} onClick={() => openGroup(group.id)}>
                <span className="similarity-cover"><img src={group.thumbnail_url} loading="lazy" alt={`${group.event_name} 相似组封面`} /><b>{group.capture_count} 张</b><i className={`review-status-badge ${group.review_status}`}>{statusLabels[group.review_status]}</i></span>
                <span className="similarity-copy"><strong>{group.event_name}</strong><small>{group.recommended_stem ? `推荐 ${group.recommended_stem}` : "等待技术评分"}{group.average_score == null ? "" : ` · 均分 ${group.average_score}`}{group.pick_count ? ` · ${group.pick_count} 张入选` : ""}</small></span>
              </button>
            ))}
            {!groupItems.length && <div className="empty-state">{reviewFilter === "pending" ? "所有相似组都已处理完，可切换到“全部”回顾。" : "还没有相似分组，先运行相似分析。"}</div>}
          </div>
          {groups && <Pagination count={groups.count} limit={groups.limit} offset={groups.offset} onChange={changeGroupPage} onLimitChange={changeGroupPageSize} />}
        </section>
      )}
    </>
  );
}

function LuminanceHistogram({ histogram, shadowClip, highlightClip }: {
  histogram: number[];
  shadowClip: number | null;
  highlightClip: number | null;
}) {
  const width = 256;
  const height = 72;
  const max = Math.max(1, ...histogram);
  const barWidth = width / histogram.length;
  return (
    <div className="detail-histogram">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="亮度直方图">
        <rect x="0" y="0" width={barWidth * 2} height={height} className="histogram-clip-zone" />
        <rect x={width - barWidth * 2} y="0" width={barWidth * 2} height={height} className="histogram-clip-zone" />
        {histogram.map((value, index) => {
          const barHeight = Math.max(value > 0 ? 1 : 0, (value / max) * height);
          return <rect key={index} x={index * barWidth} y={height - barHeight} width={Math.max(0.5, barWidth - 0.6)} height={barHeight} className="histogram-bar" />;
        })}
      </svg>
      <small>基于 JPG 亮度，不代表 RAW 动态余量 · 暗部剪切 {shadowClip == null ? "—" : `${shadowClip.toFixed(1)}%`} · 高光剪切 {highlightClip == null ? "—" : `${highlightClip.toFixed(1)}%`}</small>
    </div>
  );
}

function ScoreBar({ label, score }: { label: string; score: number | null }) {
  return (
    <div className="score-bar">
      <span>{label}</span>
      <div className="score-bar-track"><i style={{ width: `${Math.max(0, Math.min(100, score ?? 0))}%` }} className={score != null && score < 60 ? "low" : ""} /></div>
      <b>{score == null ? "—" : Math.round(score)}</b>
    </div>
  );
}

type ParameterHelpEntry = { title: string; meaning: string; options: Array<readonly [string, string]>; note?: string };
const parameterHelp = {
  shutter: { title: "快门速度", meaning: "控制曝光持续时间。它是连续数值，不存在有限的全部选项。", options: [["1/1000 秒及更快", "凝固运动、飞鸟和体育"], ["1/125–1/500 秒", "一般手持和日常动作"], ["1/30–1/100 秒", "静止主体可尝试手持，需留意防抖和焦距"], ["1 秒及更慢", "记录流水、车轨等运动，通常需要支撑"], ["Bulb / Time", "由摄影者控制超长曝光时长"]] },
  aperture: { title: "光圈", meaning: "控制进光量和景深，是由镜头决定范围的连续档位。f 数越小，光圈越大。", options: [["f/1.0–f/2.0", "大进光量、浅景深"], ["f/2.8–f/4", "主体分离与清晰范围的平衡"], ["f/5.6–f/8", "常见最佳画质区间"], ["f/11–f/22", "扩大景深，但过小可能出现衍射"]] },
  iso: { title: "ISO 感光度", meaning: "表示传感器信号增益，是连续档位；提高 ISO 通常会增加噪点并降低动态范围。", options: [["原生低 ISO", "通常有最佳画质和动态范围"], ["自动 ISO", "相机按快门下限等规则自动选择"], ["高 ISO", "弱光下换取快门速度"], ["扩展 ISO（L/H）", "机内推拉值，画质或高光余量可能受限"]] },
  focal: { title: "焦距", meaning: "影响视角和画面透视呈现，是镜头提供的连续或固定数值。", options: [["24mm 以下（等效）", "超广角"], ["24–35mm", "广角"], ["40–60mm", "标准视角"], ["70–200mm", "中长焦到长焦"], ["200mm 以上", "超长焦"]] },
  compensation: { title: "曝光补偿", meaning: "在自动测光结果上主动增亮或压暗，是连续档位。", options: [["0 EV", "采用相机测光结果"], ["正补偿", "整体增亮，常用于雪景或逆光人物"], ["负补偿", "整体压暗，常用于保护高光"], ["自动包围曝光", "连续拍摄不同补偿值以便选择或合成"]] },
  film: { title: "胶片模拟", meaning: "相机对 JPG 色彩、对比度和色调的预设，不等同于 RAW 的全部可调空间。", options: [["Provia / Standard", "自然、通用"], ["Velvia / Vivid", "高饱和、高反差，常用于风景"], ["Astia / Soft", "较柔和的人像色调"], ["Classic Chrome", "低饱和、纪实感"], ["Classic Neg.", "较强色彩层次和负片感"], ["Nostalgic Neg.", "暖高光与柔和怀旧色调"], ["ETERNA / Cinema", "低反差、电影感"], ["ETERNA Bleach Bypass", "低饱和、高反差"], ["Acros / Monochrome", "黑白；可带黄/红/绿滤镜"], ["Sepia", "棕褐色单色"]], note: "胶片模拟是厂商专有枚举；此处列出当前图库富士设备的常见全集，新机型可能增加选项。" },
  program: { title: "曝光程序与模式", meaning: "决定快门、光圈和 ISO 中哪些由摄影者控制。", options: [["Auto / 全自动", "相机决定主要曝光参数"], ["P / Program AE", "相机组合快门与光圈，可程序偏移"], ["A / Av", "摄影者设光圈，相机决定快门"], ["S / Tv", "摄影者设快门，相机决定光圈"], ["M / Manual", "摄影者设快门和光圈"], ["Bulb / Time", "超长曝光"], ["Scene / 场景模式", "针对人像、运动、夜景等的自动策略"]] },
  shutterType: { title: "快门类型", meaning: "不同快门的静音、最高速度、闪光同步和运动畸变特性不同。", options: [["机械快门（Mechanical Shutter）", "实体帘幕曝光；闪光兼容好，运动畸变较少，但有声音和机械震动"], ["电子前帘（Electronic Front Curtain / EFCS）", "电子开始、机械结束；震动较小，但高速大光圈可能影响焦外或曝光均匀"], ["电子快门（Electronic Shutter）", "完全静音、可达更高速度；快速运动可能滚动变形，频闪灯下可能有条纹"], ["机械 + 电子（Mechanical + Electronic）", "相机按速度或条件自动切换"], ["电子前帘 + 机械", "相机在 EFCS 和机械之间自动切换"], ["自动（Auto）", "由机身根据当前功能选择"]], note: "部分机型还提供全局快门或特殊高速模式；实际选项以相机型号为准。" },
  metering: { title: "测光模式", meaning: "决定相机用画面哪些区域估算曝光。", options: [["多区 / 评价（Multi-segment / Evaluative）", "综合全画面与主体信息，最通用"], ["中央重点（Center-weighted）", "全画面测光但提高中央区域权重"], ["点测光（Spot）", "只测很小区域，适合精确控制主体亮度"], ["局部测光（Partial）", "测量中央较小区域，范围大于点测光"], ["平均测光（Average）", "平均考虑整个画面"], ["高光重点（Highlight-weighted）", "优先避免亮部过曝"]] },
  whiteBalance: { title: "白平衡", meaning: "校正不同光源的色温和色偏，也可用于创造冷暖氛围。", options: [["自动（Auto / AWB）", "相机判断中性色；部分机型可选保留白色或保留暖色"], ["日光（Daylight）", "晴天日光"], ["阴影（Shade）", "增加暖色以修正阴影偏蓝"], ["阴天（Cloudy）", "比日光略暖"], ["钨丝灯（Tungsten）", "修正暖色白炽灯"], ["荧光灯（Fluorescent）", "修正不同类型荧光灯偏色"], ["闪光灯（Flash）", "匹配机顶闪光灯"], ["色温 K 值", "直接指定色温"], ["自定义 / Custom", "使用灰卡或已测量白点"]] },
  focus: { title: "对焦模式", meaning: "决定相机锁定一次焦点，还是持续跟随主体变化。", options: [["AF-S / Single", "半按后锁定，适合静止主体"], ["AF-C / Continuous", "持续更新焦点，适合运动主体"], ["AF-A / Automatic", "相机在单次和连续之间判断"], ["MF / Manual", "手动对焦"], ["DMF", "自动对焦后允许手动微调"]] },
  afArea: { title: "AF 区域", meaning: "决定相机可从多大范围内选择对焦点。", options: [["单点 / Single Point", "精确指定一个对焦点"], ["区域 / Zone", "在一组对焦点内识别主体"], ["宽域 / Wide", "相机在大范围内自动选择"], ["全域 / All", "使用整个对焦覆盖区"], ["追踪 / Tracking", "识别并持续跟随指定主体"], ["人脸 / 眼睛识别", "优先人物面部或眼睛"], ["动物 / 鸟类 / 交通工具识别", "机型支持的专用主体识别"]] },
  stabilization: { title: "防抖", meaning: "补偿手持抖动，不能冻结主体自身运动。", options: [["关闭（Off）", "不进行光学或传感器补偿"], ["持续（Continuous / Mode 1）", "持续稳定取景与曝光"], ["仅拍摄时（Shooting Only）", "曝光前后启用，较省电"], ["摇摄（Panning / Mode 2）", "保留一个方向的主动移动"], ["机身防抖（IBIS）", "移动传感器补偿"], ["镜头防抖（OIS / VR / OSS）", "移动镜片组补偿"], ["协同防抖", "机身和镜头配合"]] },
  dynamicRange: { title: "动态范围设置", meaning: "通过曝光和 JPG 曲线保护高光或抬升阴影，主要影响机内 JPG。", options: [["DR100", "标准基准，不额外压缩高光"], ["DR200", "约增加 1 档高光保护，通常要求较高最低 ISO"], ["DR400", "约增加 2 档高光保护，最低 ISO 要求更高"], ["Auto DR", "相机根据场景选择 DR100/200/400"], ["D-Range Priority", "综合调整高光与阴影曲线；部分配方参数会被限制"]], note: "其他品牌可能称 Active D-Lighting、DRO、Highlight Tone Priority 等，机制并不完全相同。" },
} satisfies Record<string, ParameterHelpEntry>;

function ParameterHelp({ kind }: { kind: keyof typeof parameterHelp }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const help: ParameterHelpEntry = parameterHelp[kind];
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [open]);
  return <span ref={rootRef} className="parameter-help">
    <button type="button" aria-label={`解释${help.title}`} aria-expanded={open} onClick={() => setOpen((current) => !current)}>?</button>
    {open && <span className="parameter-help-popover" role="note"><span className="parameter-help-heading"><strong>{help.title}</strong><button type="button" aria-label="关闭解释" onClick={() => setOpen(false)}>×</button></span><span>{help.meaning}</span><b>可能的选项与含义</b><span className="parameter-help-options">{help.options.map(([value, meaning]) => <span key={value}><strong>{value}</strong><small>{meaning}</small></span>)}</span>{help.note && <em>{help.note}</em>}</span>}
  </span>;
}

const metadataValueTranslations: Record<string, string> = {
  "auto": "自动", "automatic": "自动", "manual": "手动", "normal": "标准", "standard": "标准",
  "on": "开启", "off": "关闭", "yes": "是", "no": "否", "none": "无", "unknown": "未知",
  "mechanical": "机械快门", "mechanical shutter": "机械快门", "electronic": "电子快门", "electronic shutter": "电子快门",
  "electronic front curtain": "电子前帘", "electronic front curtain shutter": "电子前帘",
  "mechanical + electronic": "机械 + 电子自动切换", "mechanical + electronic shutter": "机械 + 电子自动切换",
  "program ae": "程序自动曝光（P）", "aperture-priority ae": "光圈优先（A/Av）", "aperture priority": "光圈优先（A/Av）",
  "shutter speed priority ae": "快门优先（S/Tv）", "shutter-priority ae": "快门优先（S/Tv）", "manual exposure": "手动曝光（M）",
  "multi-segment": "多区测光", "multi-zone": "多区测光", "evaluative": "评价测光", "center-weighted average": "中央重点平均测光",
  "center-weighted": "中央重点测光", "spot": "点测光", "partial": "局部测光", "average": "平均测光", "highlight-weighted": "高光重点测光",
  "daylight": "日光", "shade": "阴影", "cloudy": "阴天", "tungsten": "钨丝灯", "incandescent": "白炽灯",
  "fluorescent": "荧光灯", "flash": "闪光灯", "custom": "自定义", "auto white priority": "自动（白色优先）", "auto ambiance priority": "自动（氛围优先）",
  "single": "单次", "single af": "单次自动对焦（AF-S）", "continuous": "连续", "continuous af": "连续自动对焦（AF-C）",
  "manual focus": "手动对焦（MF）", "af-s": "单次自动对焦（AF-S）", "af-c": "连续自动对焦（AF-C）", "af-a": "自动切换对焦（AF-A）",
  "single point": "单点", "single-point": "单点", "zone": "区域", "wide": "宽域", "wide/tracking": "宽域 / 追踪", "tracking": "追踪", "all": "全域",
  "continuous, mode 1": "持续防抖（模式 1）", "shooting only": "仅拍摄时防抖", "panning": "摇摄防抖",
  "sr+": "智能场景识别自动", "fine": "精细", "fine jpeg": "精细 JPEG", "raw + jpeg": "RAW + JPEG",
  "uncompressed": "未压缩", "lossless compressed": "无损压缩", "compressed": "有损压缩",
  "srgb": "sRGB", "adobe rgb": "Adobe RGB", "horizontal (normal)": "横向（正常）",
  "rotate 90 cw": "顺时针旋转 90°", "rotate 270 cw": "顺时针旋转 270°", "high": "高", "low": "低", "strong": "强", "weak": "弱",
  "provia/standard": "Provia / 标准", "velvia/vivid": "Velvia / 鲜艳", "astia/soft": "Astia / 柔和",
  "f0/standard (provia)": "Provia / 标准", "f1/studio portrait": "Studio Portrait / 棚拍人像", "f2/fujichrome": "Fujichrome / 鲜艳",
  "classic chrome": "经典正片", "classic neg": "经典负片", "nostalgic neg": "怀旧负片", "eterna/cinema": "Eterna / 电影",
  "eterna bleach bypass": "Eterna 漂白效果", "acros": "Acros 黑白", "monochrome": "黑白", "sepia": "棕褐色",
  "single frame": "单张拍摄", "continuous low": "低速连拍", "continuous high": "高速连拍", "movie": "视频",
  "no flash": "未闪光", "fired": "已闪光", "fired, compulsory flash mode": "已闪光（强制闪光）", "auto, did not fire": "自动闪光（未触发）",
  "face detection": "人脸识别", "eye detection": "眼睛识别", "subject tracking": "主体追踪",
  "ois lens": "镜头光学防抖", "on (mode 1, continuous)": "开启（模式 1，持续）", "on (mode 2, shooting only)": "开启（模式 2，仅拍摄时）",
};

function formatMetadataText(value: unknown): string {
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) return value.map(formatMetadataText).join(" · ");
  if (typeof value !== "string") return String(value);
  const trimmed = value.trim();
  const translated = metadataValueTranslations[trimmed.toLocaleLowerCase()];
  if (!translated && trimmed.includes(";")) {
    const segments = trimmed.split(";").map((item) => item.trim());
    const localized = segments.map((item) => metadataValueTranslations[item.toLocaleLowerCase()] ?? item);
    if (localized.some((item, index) => item !== segments[index])) return `${localized.join("；")}（${value}）`;
  }
  return translated && translated !== value ? `${translated}（${value}）` : value;
}

function CaptureDetailPanel({ detail, close, saveAiReview, saveReview, navigate, hasPrev, hasNext }: {
  detail: CaptureDetail;
  close: () => void;
  saveAiReview: (analysisId: number, verdict: "accurate" | "partial" | "inaccurate" | null, note: string | null) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  navigate: (direction: 1 | -1) => void;
  hasPrev: boolean;
  hasNext: boolean;
}) {
  const exif = detail.files.find((file) => file.role === "jpeg") ?? detail.files[0];
  const latestAnalysis = detail.ai_analyses[0];
  const latestAi = latestAnalysis?.result as Record<string, unknown> | undefined;
  const visibleProblems = Array.isArray(latestAi?.visible_problems) ? latestAi.visible_problems as Array<Record<string, unknown>> : [];
  const shootingAdvice = Array.isArray(latestAi?.shooting_advice) ? latestAi.shooting_advice as Array<Record<string, unknown>> : [];
  const lightroomSuggestions = Array.isArray(latestAi?.lightroom_suggestions) ? latestAi.lightroom_suggestions as Array<Record<string, unknown>> : [];
  const [aiNote, setAiNote] = useState(latestAnalysis?.user_note ?? "");
  const [immersive, setImmersive] = useState(false);
  const [showImmersiveInfo, setShowImmersiveInfo] = useState(false);
  const [zoom, setZoom] = useState(0);
  const backdropRef = useRef<HTMLDivElement | null>(null);
  const [informationLevel, setInformationLevel] = useState<"compact" | "standard" | "full">(() => {
    const saved = window.localStorage.getItem("tangerine-detail-information");
    return saved === "compact" || saved === "full" ? saved : "standard";
  });
  useEffect(() => setAiNote(latestAnalysis?.user_note ?? ""), [latestAnalysis?.id, latestAnalysis?.user_note]);
  useEffect(() => window.localStorage.setItem("tangerine-detail-information", informationLevel), [informationLevel]);
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousPaddingRight = document.body.style.paddingRight;
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = "hidden";
    if (scrollbarWidth > 0) document.body.style.paddingRight = `${scrollbarWidth}px`;
    return () => {
      document.body.style.overflow = previousOverflow;
      document.body.style.paddingRight = previousPaddingRight;
    };
  }, []);
  const metadataText = formatMetadataText;
  const review = (changes: Partial<ReviewPayload>) => saveReview(detail.id, {
    user_rating: detail.user_rating,
    user_pick: Boolean(detail.user_pick),
    user_reject: Boolean(detail.user_reject),
    user_note: detail.user_note,
    ...changes,
  });
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      const review = (changes: Partial<ReviewPayload>) => saveReview(detail.id, {
        user_rating: detail.user_rating,
        user_pick: Boolean(detail.user_pick),
        user_reject: Boolean(detail.user_reject),
        user_note: detail.user_note,
        ...changes,
      });
      if (event.key === "Escape") { if (immersive) { setImmersive(false); setZoom(0); } else close(); return; }
      if (event.key === "f" || event.key === "F") { setImmersive((current) => !current); setZoom(0); return; }
      if (event.key === "ArrowLeft") { event.preventDefault(); navigate(-1); return; }
      if (event.key === "ArrowRight") { event.preventDefault(); navigate(1); return; }
      if (event.key >= "1" && event.key <= "5") { review({ user_rating: Number(event.key) }); return; }
      if (event.key === "0") { review({ user_rating: null }); return; }
      if (event.key === "p" || event.key === "P") { review({ user_pick: !detail.user_pick, user_reject: false }); return; }
      if (event.key === "x" || event.key === "X") { review({ user_pick: false, user_reject: !detail.user_reject }); }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [detail, close, immersive, navigate, saveReview]);
  return (
    <div ref={backdropRef} className={`detail-backdrop ${immersive ? "immersive" : ""}`} role="dialog" aria-modal="true" aria-label={`${detail.stem} 照片详情`} onClick={close}>
      {hasPrev && <button className="detail-nav prev" aria-label="上一张" onClick={(event) => { event.stopPropagation(); navigate(-1); }}>‹</button>}
      {hasNext && <button className="detail-nav next" aria-label="下一张" onClick={(event) => { event.stopPropagation(); navigate(1); }}>›</button>}
      <section className={`detail-panel ${showImmersiveInfo ? "show-immersive-info" : ""}`} onClick={(event) => event.stopPropagation()}>
        <button className="detail-close" onClick={close} aria-label="关闭详情">×</button>
        <div className={`detail-image ${zoom ? "zoomed" : ""}`}>
          <img style={zoom ? { width: `${zoom * 100}%`, height: "auto", maxWidth: "none" } : undefined} src={detail.thumbnail_url} alt={`${detail.stem} 大图预览`} />
          {detail.files.some((file) => file.role === "raw") && <span className="raw-badge">JPG + RAW</span>}
          <div className="detail-view-controls">
            <button onClick={() => { setImmersive((current) => !current); setZoom(0); }}>{immersive ? "退出沉浸" : "沉浸查看"}</button>
            {immersive && <><button onClick={() => setZoom(0)}>适应</button><button onClick={() => setZoom((current) => current ? Math.max(1, current - .5) : 1)}>−</button><button onClick={() => setZoom((current) => current ? Math.min(4, current + .5) : 1)}>＋</button><button onClick={() => setShowImmersiveInfo((current) => !current)}>{showImmersiveInfo ? "隐藏信息" : "显示信息"}</button><button onClick={() => void backdropRef.current?.requestFullscreen?.()}>浏览器全屏</button></>}
          </div>
        </div>
        <div className="detail-copy">
          <span className="section-kicker">{detail.category ?? "未分类"}</span>
          <h2>{detail.stem}</h2>
          <p>{detail.event_name ?? detail.parent_relative}</p>
          <div className="detail-review-bar">
            <div className="detail-stars" role="radiogroup" aria-label="人工星级">
              {[1, 2, 3, 4, 5].map((star) => <button key={star} className={detail.user_rating != null && detail.user_rating >= star ? "filled" : ""} aria-label={`${star} 星`} onClick={() => review({ user_rating: detail.user_rating === star ? null : star })}>★</button>)}
            </div>
            <button className={`detail-pick ${detail.user_pick ? "selected" : ""}`} onClick={() => review({ user_pick: !detail.user_pick, user_reject: false })}>入选</button>
            <button className={`detail-reject ${detail.user_reject ? "rejected" : ""}`} onClick={() => review({ user_pick: false, user_reject: !detail.user_reject })}>排除</button>
            <small className="detail-shortcut-hint">快捷键：← → 切换 · 1–5 打星 · 0 清除 · P 入选 · X 排除 · Esc 关闭</small>
          </div>
          <div className="exif-strip">
            <div><strong>{formatExposure(exif?.exposure_time)}</strong><span>快门 <ParameterHelp kind="shutter" /></span></div>
            <div><strong>{exif?.f_number ? `f/${exif.f_number}` : "—"}</strong><span>光圈 <ParameterHelp kind="aperture" /></span></div>
            <div><strong>{exif?.iso ? `ISO ${exif.iso}` : "—"}</strong><span>感光度 <ParameterHelp kind="iso" /></span></div>
            <div><strong>{exif?.focal_length_mm ? `${exif.focal_length_mm}mm` : "—"}</strong><span>焦距{exif?.focal_length_35mm ? ` · 等效${exif.focal_length_35mm}mm` : ""} <ParameterHelp kind="focal" /></span></div>
          </div>
          <div className="detail-section detail-exif-section">
            <div className="detail-section-heading"><h3>拍摄参数</h3><label>信息显示<select value={informationLevel} onChange={(event) => setInformationLevel(event.target.value as "compact" | "standard" | "full")}><option value="compact">精简</option><option value="standard">标准</option><option value="full">完整</option></select></label></div>
            <dl className="exif-grid">
              <div><dt>相机</dt><dd>{exif?.camera_model ?? "—"}</dd></div>
              <div><dt>镜头</dt><dd>{exif?.lens_model ?? "—"}</dd></div>
              <div><dt>拍摄时间</dt><dd>{detail.captured_at ? detail.captured_at.replace("T", " ") : "—"}</dd></div>
              <div><dt>尺寸</dt><dd>{exif?.width && exif?.height ? `${exif.width} × ${exif.height}` : "—"}</dd></div>
              <div><dt>曝光补偿 <ParameterHelp kind="compensation" /></dt><dd>{exif?.exposure_compensation == null ? "—" : `${exif.exposure_compensation > 0 ? "+" : ""}${exif.exposure_compensation} EV`}</dd></div>
              <div><dt>胶片模拟 <ParameterHelp kind="film" /></dt><dd>{metadataText(exif?.film_simulation)}</dd></div>
              <div><dt>GPS</dt><dd>{exif?.gps_latitude != null && exif?.gps_longitude != null ? `${exif.gps_latitude.toFixed(5)}, ${exif.gps_longitude.toFixed(5)}` : "—"}</dd></div>
            </dl>
            {informationLevel !== "compact" && <details className="metadata-details" open={informationLevel === "full"}><summary>拍摄方式与对焦</summary><dl className="exif-grid">
              <div><dt>曝光程序 <ParameterHelp kind="program" /></dt><dd>{metadataText(exif?.exposure_program)}</dd></div><div><dt>曝光模式</dt><dd>{metadataText(exif?.exposure_mode)}</dd></div>
              <div><dt>快门类型 <ParameterHelp kind="shutterType" /></dt><dd>{metadataText(exif?.shutter_type)}</dd></div><div><dt>测光模式 <ParameterHelp kind="metering" /></dt><dd>{metadataText(exif?.metering_mode)}</dd></div>
              <div><dt>白平衡 <ParameterHelp kind="whiteBalance" /></dt><dd>{metadataText(exif?.white_balance)}</dd></div><div><dt>闪光灯</dt><dd>{metadataText(exif?.flash)}</dd></div>
              <div><dt>对焦模式 <ParameterHelp kind="focus" /></dt><dd>{metadataText(exif?.focus_mode ?? exif?.af_mode)}</dd></div><div><dt>AF 区域 <ParameterHelp kind="afArea" /></dt><dd>{metadataText(exif?.af_area_mode)}</dd></div>
              <div><dt>对焦点</dt><dd>{metadataText(exif?.focus_pixel)}</dd></div><div><dt>防抖 <ParameterHelp kind="stabilization" /></dt><dd>{metadataText(exif?.image_stabilization)}</dd></div>
              <div><dt>驱动模式</dt><dd>{metadataText(exif?.drive_mode)}</dd></div><div><dt>连拍速度</dt><dd>{metadataText(exif?.drive_speed)}</dd></div>
              <div><dt>序列编号</dt><dd>{metadataText(exif?.sequence_number)}</dd></div><div><dt>包围曝光</dt><dd>{metadataText(exif?.auto_bracketing)}</dd></div>
              <div><dt>精确时间</dt><dd>{metadataText(exif?.captured_at_precise)}</dd></div><div><dt>时区</dt><dd>{metadataText(exif?.timezone_offset)}</dd></div>
            </dl></details>}
            {informationLevel === "full" && <><details className="metadata-details" open><summary>富士机内配方</summary><dl className="exif-grid">
              <div><dt>动态范围 <ParameterHelp kind="dynamicRange" /></dt><dd>{metadataText(exif?.dynamic_range)}</dd></div><div><dt>自动动态范围</dt><dd>{metadataText(exif?.auto_dynamic_range)}</dd></div>
              <div><dt>白平衡微调</dt><dd>{metadataText(exif?.white_balance_fine_tune)}</dd></div><div><dt>高光色调</dt><dd>{metadataText(exif?.highlight_tone)}</dd></div>
              <div><dt>阴影色调</dt><dd>{metadataText(exif?.shadow_tone)}</dd></div><div><dt>色彩</dt><dd>{metadataText(exif?.saturation)}</dd></div>
              <div><dt>机内锐度</dt><dd>{metadataText(exif?.camera_sharpness)}</dd></div><div><dt>降噪</dt><dd>{metadataText(exif?.noise_reduction)}</dd></div>
              <div><dt>清晰度</dt><dd>{metadataText(exif?.clarity)}</dd></div><div><dt>Color Chrome</dt><dd>{metadataText(exif?.color_chrome_effect)}</dd></div>
              <div><dt>Chrome FX Blue</dt><dd>{metadataText(exif?.color_chrome_fx_blue)}</dd></div><div><dt>颗粒</dt><dd>{[exif?.grain_effect_roughness, exif?.grain_effect_size].filter((value) => value != null).map(String).join(" · ") || "—"}</dd></div>
              <div><dt>镜头优化</dt><dd>{metadataText(exif?.lens_modulation_optimizer)}</dd></div>
            </dl></details><details className="metadata-details"><summary>文件与拍摄诊断</summary><dl className="exif-grid">
              <div><dt>方向</dt><dd>{metadataText(exif?.orientation)}</dd></div><div><dt>色彩空间</dt><dd>{metadataText(exif?.color_space)}</dd></div>
              <div><dt>位深</dt><dd>{metadataText(exif?.bits_per_sample)}</dd></div><div><dt>图像质量</dt><dd>{metadataText(exif?.image_quality)}</dd></div>
              <div><dt>RAW 压缩</dt><dd>{metadataText(exif?.raw_compression)}</dd></div><div><dt>检测人脸</dt><dd>{metadataText(exif?.faces_detected)}</dd></div>
              <div><dt>水平倾角</dt><dd>{metadataText(exif?.roll_angle)}</dd></div><div><dt>俯仰角</dt><dd>{metadataText(exif?.camera_elevation_angle)}</dd></div>
              <div><dt>模糊警告</dt><dd>{metadataText(exif?.blur_warning)}</dd></div><div><dt>对焦警告</dt><dd>{metadataText(exif?.focus_warning)}</dd></div>
              <div><dt>曝光警告</dt><dd>{metadataText(exif?.exposure_warning)}</dd></div>
            </dl></details></>}
          </div>
          <div className="detail-section"><h3>技术面板</h3>
            {detail.histogram && detail.histogram.length > 0 && <LuminanceHistogram histogram={detail.histogram} shadowClip={detail.shadow_clip_pct} highlightClip={detail.highlight_clip_pct} />}
            {detail.technical_score == null ? <p>尚未运行技术质量分析。</p> : <div className="score-bars">
              <ScoreBar label={`总分 ${Math.round(detail.technical_score)}`} score={detail.technical_score} />
              <ScoreBar label="曝光" score={detail.exposure_score} />
              <ScoreBar label="清晰度" score={detail.sharpness_score} />
              <ScoreBar label="参数" score={detail.exif_score} />
            </div>}
          </div>
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

function SimilarityGroupingEditor({ group, cancel, save, restore, restoreRevision }: {
  group: SimilarityGroupDetail;
  cancel: () => void;
  save: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<{ revision_id: number; group_ids: number[] }>;
  restore: (captureId: number) => Promise<void>;
  restoreRevision: (revisionId: number, useBefore?: boolean) => Promise<void>;
}) {
  const [buckets, setBuckets] = useState<number[][]>([group.items.map((item) => item.capture_id), []]);
  const [excluded, setExcluded] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<SimilarityRevision[]>([]);
  const historyCaptureId = group.items[0]?.capture_id;
  useEffect(() => {
    if (!historyCaptureId) return;
    getJson<{ items: SimilarityRevision[] }>(`/api/similarity-group-revisions?capture_id=${historyCaptureId}&limit=10`)
      .then((result) => setHistory(result.items)).catch(() => setHistory([]));
  }, [historyCaptureId]);
  const items = new Map(group.items.map((item) => [item.capture_id, item]));
  const move = (captureId: number, target: number | "excluded") => {
    setBuckets((current) => {
      const next = current.map((bucket) => bucket.filter((id) => id !== captureId));
      if (target !== "excluded") next[target] = [...next[target], captureId];
      return next;
    });
    setExcluded((current) => target === "excluded"
      ? [...current.filter((id) => id !== captureId), captureId]
      : current.filter((id) => id !== captureId));
  };
  const drop = (event: DragEvent, target: number | "excluded") => {
    event.preventDefault();
    const captureId = Number(event.dataTransfer.getData("text/capture-id"));
    if (captureId) move(captureId, target);
  };
  const submit = async () => {
    setSaving(true);
    try { await save(group.id, buckets.filter((bucket) => bucket.length), excluded); }
    finally { setSaving(false); }
  };
  const hasManualGrouping = group.items.some((item) => item.manual_batch_key || item.grouping_override);
  const restoreCaptureId = group.items.find((item) => item.manual_batch_key || item.grouping_override)?.capture_id;
  const undoableRevision = history.find((revision) => revision.can_undo);
  const hasSingletonGroup = buckets.some((bucket) => bucket.length === 1);
  return <div className="grouping-editor">
    <div className="grouping-editor-note"><span>拖动照片到不同分组。放入“移出分组”的照片会作为普通单张显示。</span><div>{undoableRevision && <button onClick={() => { if (window.confirm("撤销这批照片最近一次人工调整？")) void restoreRevision(undoableRevision.id, true); }}>撤销上一次调整</button>}{hasManualGrouping && restoreCaptureId && <button onClick={() => { if (window.confirm("恢复自动识别会移除这一批照片的全部人工拆分。是否继续？")) void restore(restoreCaptureId); }}>恢复自动识别</button>}</div></div>
    <div className="grouping-board">
      {buckets.map((bucket, bucketIndex) => <section className={`grouping-bucket ${bucket.length ? "" : "empty"}`} key={bucketIndex} onDragOver={(event) => event.preventDefault()} onDrop={(event) => drop(event, bucketIndex)}>
        <header><strong>{bucketIndex === 0 ? "分组 A" : `分组 ${String.fromCharCode(65 + bucketIndex)}`}</strong><span>{bucket.length} 张</span>{bucketIndex > 1 && !bucket.length && <button onClick={() => setBuckets((current) => current.filter((_, index) => index !== bucketIndex))}>删除</button>}</header>
        <div>{bucket.map((captureId) => { const item = items.get(captureId)!; return <article draggable key={captureId} onDragStart={(event) => event.dataTransfer.setData("text/capture-id", String(captureId))}><img src={item.thumbnail_url} alt={item.stem} /><span>{item.stem}</span></article>; })}{!bucket.length && <p>拖到这里建立新组</p>}</div>
      </section>)}
      <section className={`grouping-bucket grouping-excluded ${excluded.length ? "" : "empty"}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => drop(event, "excluded")}>
        <header><strong>移出分组</strong><span>{excluded.length} 张</span></header>
        <div>{excluded.map((captureId) => { const item = items.get(captureId)!; return <article draggable key={captureId} onDragStart={(event) => event.dataTransfer.setData("text/capture-id", String(captureId))}><img src={item.thumbnail_url} alt={item.stem} /><span>{item.stem}</span></article>; })}{!excluded.length && <p>拖到这里，确认前不会保存</p>}</div>
      </section>
    </div>
    <footer className="grouping-editor-footer"><button className="toolbar-button" onClick={() => setBuckets((current) => [...current, []])}>＋ 新增分组</button><span className={hasSingletonGroup ? "grouping-warning" : ""}>{hasSingletonGroup ? "相似组至少需要 2 张；单张请放入“移出分组”" : "所有调整只在点击确认后生效"}</span><button className="toolbar-button" onClick={cancel}>取消</button><button className="toolbar-button primary" disabled={saving || hasSingletonGroup} onClick={() => void submit()}>{saving ? "正在保存" : "确认调整"}</button></footer>
  </div>;
}

function SimilarityPickerModal({ group, close, openCapture, saveReview, editGrouping, saveGrouping, restoreGroupingRevision }: {
  group: SimilarityGroupDetail;
  close: () => void;
  openCapture: (captureId: number, context?: number[]) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  editGrouping: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  saveGrouping: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<{ revision_id: number; group_ids: number[] }>;
  restoreGroupingRevision: (revisionId: number, useBefore?: boolean) => Promise<void>;
}) {
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  return <ModalShell title={`${group.event_name} · 相似照片`} close={close} wide>
    {editingGroupId === group.id ? <SimilarityGroupingEditor key={group.id} group={group} cancel={() => setEditingGroupId(null)} save={saveGrouping} restore={(captureId) => editGrouping(captureId, "auto")} restoreRevision={restoreGroupingRevision} /> : <>
    <div className="similarity-picker-summary"><span>共 {group.capture_count} 张，按拍摄顺序排列</span><button className="toolbar-button" onClick={() => setEditingGroupId(group.id)}>调整分组</button></div>
    <div className="similarity-picker-grid">{group.items.map((item) => <article className={`${item.auto_pick ? "auto-pick" : ""} ${item.user_pick ? "user-pick" : ""} ${item.user_reject ? "user-reject" : ""}`} key={item.capture_id}>
      <button className="similarity-picker-photo" onClick={() => openCapture(item.capture_id, group.items.map((member) => member.capture_id))}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} />{item.auto_pick && <span>技术推荐</span>}</button>
      <div className="similarity-picker-copy"><strong>{item.stem}</strong><small>{item.technical_score == null ? "未评分" : `技术分 ${Math.round(item.technical_score)}`} · ISO {item.iso ?? "—"}</small></div>
      <div className="similarity-picker-actions"><select value={item.user_rating ?? ""} onChange={(event) => saveReview(item.capture_id, { user_rating: event.target.value ? Number(event.target.value) : null, user_pick: Boolean(item.user_pick), user_reject: Boolean(item.user_reject), user_note: item.user_note })}><option value="">星级</option>{[1, 2, 3, 4, 5].map((rating) => <option key={rating} value={rating}>{rating}★</option>)}</select><button className={item.user_pick ? "selected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: !item.user_pick, user_reject: false, user_note: item.user_note })}>入选</button><button className={item.user_reject ? "rejected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: false, user_reject: !item.user_reject, user_note: item.user_note })}>排除</button></div>
    </article>)}</div></>}
  </ModalShell>;
}

function PhotoLibraryView({ library, filters, query, updateQuery, openCapture, openGroup, editGrouping, exportPhotos, assignToAlbum, changePage, changePageSize, albumContext = false }: {
  library: LibraryCapturesResponse | null;
  filters: LibraryFilters | null;
  query: LibraryQuery;
  updateQuery: (changes: Partial<LibraryQuery>) => void;
  openCapture: (captureId: number, context?: number[]) => void;
  openGroup?: (groupId: number) => void;
  editGrouping?: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  exportPhotos: (captureIds: number[], maxEdge: number) => Promise<PhoneShareExport>;
  assignToAlbum: (albumId: number, captureIds: number[]) => Promise<void>;
  changePage: (offset: number) => void;
  changePageSize: (limit: number) => void;
  albumContext?: boolean;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectionMode, setSelectionMode] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [layout, setLayout] = useState<PhotoLayout>(() => {
    const saved = window.localStorage.getItem("tangerine-photo-layout");
    return saved === "list" || saved === "small" || saved === "large" ? saved : "medium";
  });
  const [targetAlbum, setTargetAlbum] = useState("");
  const [maxEdge, setMaxEdge] = useState(2048);
  const [exporting, setExporting] = useState(false);
  const [latestExport, setLatestExport] = useState<PhoneShareExport | null>(null);
  useEffect(() => window.localStorage.setItem("tangerine-photo-layout", layout), [layout]);
  const toggle = (captureIds: number[]) => setSelected((current) => {
    const next = new Set(current);
    const remove = captureIds.every((captureId) => next.has(captureId));
    captureIds.forEach((captureId) => remove ? next.delete(captureId) : next.add(captureId));
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
  const pageCaptureIds = Array.from(new Set(items.flatMap((item) => item.selection_capture_ids)));
  const allSelected = pageCaptureIds.length > 0 && pageCaptureIds.every((captureId) => selected.has(captureId));
  const leaveSelectionMode = () => {
    setSelected(new Set());
    setSelectionMode(false);
  };
  const clearFilters = () => updateQuery({ albumId: albumContext ? query.albumId : "", category: "", camera: "", lens: "", rating: "", selection: "", quality: "", dateFrom: "", dateTo: "", search: "", sort: "newest" });
  const activeFilters: Array<{ key: keyof LibraryQuery; label: string }> = [
    ...(!albumContext && query.albumId ? [{ key: "albumId" as const, label: query.albumId === "__unassigned__" ? "未归入相册" : filters?.albums.find((album) => String(album.id) === query.albumId)?.name ?? "相册" }] : []),
    ...(query.category ? [{ key: "category" as const, label: `类型：${query.category}` }] : []),
    ...(query.camera ? [{ key: "camera" as const, label: query.camera }] : []),
    ...(query.lens ? [{ key: "lens" as const, label: query.lens }] : []),
    ...(query.rating ? [{ key: "rating" as const, label: `${query.rating} 星` }] : []),
    ...(query.selection ? [{ key: "selection" as const, label: query.selection === "picked" ? "已入选" : query.selection === "rejected" ? "已排除" : "待选择" }] : []),
    ...(query.quality ? [{ key: "quality" as const, label: { problems: "发现问题", low: "技术分低于 70", high: "技术分 85 以上", unanalyzed: "尚未分析" }[query.quality] ?? query.quality }] : []),
    ...(query.dateFrom ? [{ key: "dateFrom" as const, label: `从 ${query.dateFrom}` }] : []),
    ...(query.dateTo ? [{ key: "dateTo" as const, label: `至 ${query.dateTo}` }] : []),
  ];
  return <>
    <section className="library-filter-shell">
      <div className="library-filter-toolbar">
        <label className="library-search"><span aria-hidden="true">⌕</span><input aria-label="搜索照片" value={query.search} onChange={(event) => updateQuery({ search: event.target.value })} placeholder="搜索文件名、相册或目录" /></label>
        <button className={`toolbar-button filter-toggle ${filtersOpen ? "active" : ""}`} onClick={() => setFiltersOpen((current) => !current)}>筛选{activeFilters.length ? <b>{activeFilters.length}</b> : null}</button>
        <label className="sort-control"><span>排序</span><select value={query.sort} onChange={(event) => updateQuery({ sort: event.target.value })}><option value="newest">最新拍摄</option><option value="oldest">最早拍摄</option><option value="name">文件名称</option><option value="rating">人工星级</option></select></label>
        {(activeFilters.length > 0 || query.search) && <button className="filter-clear" onClick={clearFilters}>全部清除</button>}
      </div>
      {activeFilters.length > 0 && <div className="active-filter-chips">{activeFilters.map((filter) => <button key={filter.key} onClick={() => updateQuery({ [filter.key]: "" })}>{filter.label}<span>×</span></button>)}</div>}
      {filtersOpen && <div className="library-filter-drawer">
        {!albumContext && <fieldset><legend>归属</legend><label><span>相册</span><select value={query.albumId} onChange={(event) => updateQuery({ albumId: event.target.value })}><option value="">全部相册</option><option value="__unassigned__">未归入相册</option>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select></label><label><span>类型</span><select value={query.category} onChange={(event) => updateQuery({ category: event.target.value })}><option value="">全部类型</option>{(filters?.album_types ?? []).map((type) => <option key={type.name}>{type.name}</option>)}</select></label></fieldset>}
        <fieldset><legend>器材</legend><label><span>相机</span><select value={query.camera} onChange={(event) => updateQuery({ camera: event.target.value })}><option value="">全部相机</option>{(filters?.cameras ?? []).map((camera) => <option key={camera}>{camera}</option>)}</select></label><label><span>镜头</span><select value={query.lens} onChange={(event) => updateQuery({ lens: event.target.value })}><option value="">全部镜头</option>{(filters?.lenses ?? []).map((lens) => <option key={lens}>{lens}</option>)}</select></label></fieldset>
        <fieldset><legend>评价</legend><label><span>人工星级</span><select value={query.rating} onChange={(event) => updateQuery({ rating: event.target.value })}><option value="">全部星级</option>{[5, 4, 3, 2, 1].map((rating) => <option key={rating} value={rating}>{rating} 星</option>)}</select></label><label><span>选片状态</span><select value={query.selection} onChange={(event) => updateQuery({ selection: event.target.value })}><option value="">全部状态</option><option value="picked">已入选</option><option value="rejected">已排除</option><option value="unreviewed">待选择</option></select></label><label><span>技术质量</span><select value={query.quality} onChange={(event) => updateQuery({ quality: event.target.value })}><option value="">全部质量</option><option value="problems">发现问题</option><option value="low">技术分低于 70</option><option value="high">技术分 85 以上</option><option value="unanalyzed">尚未分析</option></select></label></fieldset>
        <fieldset><legend>时间</legend><label><span>开始日期</span><input type="date" value={query.dateFrom} onChange={(event) => updateQuery({ dateFrom: event.target.value })} /></label><label><span>结束日期</span><input type="date" value={query.dateTo} onChange={(event) => updateQuery({ dateTo: event.target.value })} /></label></fieldset>
      </div>}
    </section>
    <section className="photo-view-toolbar">
      <div className="photo-layout-toggle" aria-label="照片显示方式">
        {([['list', '列表'], ['small', '小图'], ['medium', '中图'], ['large', '大图']] as Array<[PhotoLayout, string]>).map(([value, label]) => <button key={value} className={layout === value ? "active" : ""} onClick={() => setLayout(value)}>{label}</button>)}
      </div>
      <div className="photo-view-actions">{albumContext && <div className="burst-view-toggle"><button className={query.collapseGroups ? "active" : ""} onClick={() => updateQuery({ collapseGroups: true })}>折叠连拍</button><button className={!query.collapseGroups ? "active" : ""} onClick={() => updateQuery({ collapseGroups: false })}>展开全部</button></div>}<button className={`toolbar-button ${selectionMode ? "active" : ""}`} onClick={() => selectionMode ? leaveSelectionMode() : setSelectionMode(true)}>批量操作</button></div>
    </section>
    <section className={`selection-toolbar ${selectionMode ? "visible" : ""}`}>
      <div><strong>临时选择 {selected.size} 张</strong><button onClick={() => setSelected(allSelected ? new Set([...selected].filter((id) => !pageCaptureIds.includes(id))) : new Set([...selected, ...pageCaptureIds]))}>{allSelected ? "取消本页" : "选择本页"}</button><button onClick={() => setSelected(new Set())}>清空</button><button onClick={leaveSelectionMode}>退出批量操作</button></div>
      <div className="selection-actions"><label>归入相册<select value={targetAlbum} onChange={(event) => setTargetAlbum(event.target.value)}><option value="">选择相册</option>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select></label><button disabled={!targetAlbum} onClick={async () => { await assignToAlbum(Number(targetAlbum), Array.from(selected)); setSelected(new Set()); }}>应用</button><label>分享尺寸<select value={maxEdge} onChange={(event) => setMaxEdge(Number(event.target.value))}><option value={1080}>1080px</option><option value={2048}>2048px</option><option value={3840}>3840px</option></select></label><button className="primary-action" disabled={!selected.size || exporting} onClick={exportSelected}><span>{exporting ? "正在生成" : "导出分享包"}</span><b>↓</b></button></div>
    </section>
    {latestExport && <div className="export-success"><span>已生成 {latestExport.photo_count} 张照片 · {formatBytes(latestExport.size_bytes)} · EXIF 已移除</span><a href={latestExport.download_url} download={latestExport.filename}>再次下载</a></div>}
    <section className={`photo-library-grid layout-${layout} ${selectionMode ? "selecting" : ""}`}>
      {items.map((item) => {
        const itemSelected = item.selection_capture_ids.every((captureId) => selected.has(captureId));
        const isGroup = item.item_type === "group" && item.similarity_group_id != null;
        return <article className={`library-photo-card ${itemSelected ? "selected" : ""} ${isGroup ? "group-card" : ""}`} key={isGroup ? `group-${item.similarity_group_id}` : `photo-${item.id}`}>
        {selectionMode && <button className="photo-select" aria-label={`${itemSelected ? "取消批量选择" : "批量选择"} ${item.stem}`} onClick={() => toggle(item.selection_capture_ids)}><span>{itemSelected ? "✓" : ""}</span></button>}
        <button className="photo-open" onClick={() => isGroup && openGroup ? openGroup(item.similarity_group_id!) : openCapture(item.id, items.filter((entry) => entry.item_type === "photo").map((entry) => entry.id))}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} />{isGroup && <span className="group-stack-badge">{item.similarity_group_size} 张</span>}</button>
        <div className="photo-card-copy"><div><strong>{isGroup ? `连拍 · ${item.stem}` : item.stem}</strong><span>{item.captured_at?.slice(0, 10) ?? "日期未知"}</span></div><p>{isGroup ? `${item.similarity_group_size} 张 · ${formatBytes(item.size_bytes)} · ${item.group_pick_count ?? 0} 张入选` : `${formatBytes(item.size_bytes)} · ${item.album_name ?? "尚未归入相册"}`}</p><div className="photo-card-status"><span>{item.user_rating ? `${item.user_rating} 星` : "未评分"}</span><div>{item.grouping_override === "exclude" && <>{editGrouping && <button className="similarity-inline" onClick={() => void editGrouping(item.id, "auto")}>恢复自动分组</button>}<b>已移出连拍</b></>}{!isGroup && item.similarity_group_id && openGroup ? <button className="similarity-inline" onClick={() => openGroup(item.similarity_group_id!)}>连拍组 · {item.similarity_group_size} 张</button> : null}{item.similarity_group_id && (item.user_pick ? <b>组内入选</b> : item.user_reject ? <b className="rejected">组内排除</b> : null)}</div></div></div>
      </article>})}
      {!items.length && <div className="empty-state">图库中还没有可查看的 JPEG 照片。</div>}
    </section>
    {library && <Pagination count={library.count} limit={library.limit} offset={library.offset} onChange={changePage} onLimitChange={changePageSize} />}
  </>;
}

function LibraryView({ overview, library, albums, filters, query, updateQuery, requestedSection, task, startScan, cancelTask, updateAlbum, createAlbum, createAlbumType, renameAlbumType, deleteAlbumType, assignToAlbum, openCapture, selectedGroup, openGroup, closeGroup, saveReview, editGrouping, saveGrouping, restoreGroupingRevision, exportPhotos, changePage, changePageSize, changeAlbumPage, changeAlbumPageSize, openAlbumBursts }: {
  overview: Overview | null;
  library: LibraryCapturesResponse | null;
  albums: EventsResponse | null;
  filters: LibraryFilters | null;
  query: LibraryQuery;
  updateQuery: (changes: Partial<LibraryQuery>) => void;
  requestedSection: LibrarySection;
  task: Task | null;
  startScan: (albumId: number) => void;
  cancelTask: () => void;
  updateAlbum: (album: EventItem, changes: Partial<Pick<EventItem, "proposed_name" | "category" | "status">>) => void;
  createAlbum: (name: string, category: string) => Promise<number | null>;
  createAlbumType: (name: string) => void;
  renameAlbumType: (name: string, nextName: string) => void;
  deleteAlbumType: (name: string) => void;
  assignToAlbum: (albumId: number, captureIds: number[]) => Promise<void>;
  openCapture: (captureId: number, context?: number[]) => void;
  selectedGroup: SimilarityGroupDetail | null;
  openGroup: (groupId: number) => void;
  closeGroup: () => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  editGrouping: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  saveGrouping: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<{ revision_id: number; group_ids: number[] }>;
  restoreGroupingRevision: (revisionId: number, useBefore?: boolean) => Promise<void>;
  exportPhotos: (captureIds: number[], maxEdge: number) => Promise<PhoneShareExport>;
  changePage: (offset: number) => void;
  changePageSize: (limit: number) => void;
  changeAlbumPage: (offset: number) => void;
  changeAlbumPageSize: (limit: number) => void;
  openAlbumBursts: (albumId: number) => void;
}) {
  const [section, setSection] = useState<LibrarySection>(requestedSection);
  const [activeAlbumId, setActiveAlbumId] = useState<number | null>(null);
  const [updateOpen, setUpdateOpen] = useState(false);
  const [targetAlbum, setTargetAlbum] = useState("");
  const [newAlbumName, setNewAlbumName] = useState("");
  const [newAlbumCategory, setNewAlbumCategory] = useState("");
  const [photoInbox, setPhotoInbox] = useState<PhotoInboxStatus | null>(null);
  const activeAlbum = filters?.albums.find((album) => album.id === activeAlbumId) ?? null;
  useEffect(() => {
    if (activeAlbumId === null) setSection(requestedSection);
  }, [activeAlbumId, requestedSection]);
  const showAlbum = (albumId: number) => {
    setActiveAlbumId(albumId);
    updateQuery({ albumId: String(albumId), category: "", collapseGroups: true });
  };
  const leaveAlbum = () => {
    setActiveAlbumId(null);
    setSection("albums");
    updateQuery({ albumId: "", category: "", collapseGroups: false });
  };
  const openUpdate = () => {
    setTargetAlbum(filters?.albums[0] ? String(filters.albums[0].id) : "__new__");
    setNewAlbumName("");
    setNewAlbumCategory(filters?.album_types[0]?.name ?? "日常");
    setUpdateOpen(true);
    void getJson<PhotoInboxStatus>("/api/system/photo-inbox").then(setPhotoInbox);
  };
  const runUpdate = async () => {
    let albumId = targetAlbum === "__new__" ? null : Number(targetAlbum);
    if (targetAlbum === "__new__") {
      if (!newAlbumName.trim() || !newAlbumCategory) return;
      albumId = await createAlbum(newAlbumName.trim(), newAlbumCategory);
    }
    if (!albumId) return;
    startScan(albumId);
    setUpdateOpen(false);
  };
  useEffect(() => {
    const completedAlbumId = task?.status === "complete" ? task.result?.album_id : null;
    if (completedAlbumId) showAlbum(completedAlbumId);
  }, [task?.status, task?.result?.album_id]);
  return (
    <>
      {!activeAlbumId && <div className="library-navigation"><div className="section-tabs" role="tablist" aria-label="图库功能"><button className={section === "photos" ? "active" : ""} onClick={() => setSection("photos")}>全部照片</button><button className={section === "albums" ? "active" : ""} onClick={() => setSection("albums")}>相册管理</button></div><div className="library-maintenance"><span>上次更新 {formatDate(overview?.latest_scan?.finished_at)}</span><button className="toolbar-button primary" onClick={openUpdate} disabled={task?.status === "running"}>{task?.status === "running" ? "正在更新" : "更新图库"}</button></div></div>}
      <TaskCard task={taskBelongsTo(task, "library") ? task : null} cancel={cancelTask} />
      {activeAlbumId ? <>
        <section className="album-detail-header"><button className="album-back" onClick={leaveAlbum}>← 返回相册</button><div><span>{activeAlbum?.category ?? "相册"}</span><h2>{activeAlbum?.name ?? "相册照片"}</h2><small>{numberFormat.format(activeAlbum?.capture_count ?? library?.count ?? 0)} 张照片</small></div><div className="panel-heading-actions"><button className="toolbar-button" onClick={() => openAlbumBursts(activeAlbumId)}>处理本相册连拍</button><button className="toolbar-button" onClick={openUpdate} disabled={task?.status === "running"}>更新图库</button></div></section>
        <PhotoLibraryView library={library} filters={filters} query={query} updateQuery={updateQuery} openCapture={openCapture} openGroup={openGroup} editGrouping={editGrouping} exportPhotos={exportPhotos} assignToAlbum={assignToAlbum} changePage={changePage} changePageSize={changePageSize} albumContext />
      </> : <>
        {section === "photos" && <PhotoLibraryView library={library} filters={filters} query={query} updateQuery={updateQuery} openCapture={openCapture} openGroup={openGroup} editGrouping={editGrouping} exportPhotos={exportPhotos} assignToAlbum={assignToAlbum} changePage={changePage} changePageSize={changePageSize} />}
        {section === "albums" && <AlbumsView albums={albums} filters={filters} updateAlbum={updateAlbum} createAlbum={createAlbum} createAlbumType={createAlbumType} renameAlbumType={renameAlbumType} deleteAlbumType={deleteAlbumType} openAlbum={showAlbum} changePage={changeAlbumPage} changePageSize={changeAlbumPageSize} />}
      </>}
      {updateOpen && <ModalShell title="更新图库" close={() => setUpdateOpen(false)}><form className="editor-form" onSubmit={(event) => { event.preventDefault(); void runUpdate(); }}>
        <div className="photo-inbox-card"><span>先把相机中的新照片复制到</span><strong>{photoInbox?.path ?? "正在读取目录…"}</strong><div><button type="button" className="toolbar-button" disabled={!photoInbox?.can_open} onClick={() => void getJson("/api/system/photo-inbox/open", { method: "POST" })}>在资源管理器中打开</button><button type="button" className="toolbar-button" disabled={!photoInbox?.path} onClick={() => photoInbox?.path && void navigator.clipboard.writeText(photoInbox.path)}>复制路径</button></div>{photoInbox && !photoInbox.exists && <small>目录尚不存在，请先在活动图库中创建“待整理”文件夹。</small>}</div>
        <label><span>新增照片归入</span><select value={targetAlbum} onChange={(event) => setTargetAlbum(event.target.value)}>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}<option value="__new__">＋ 新建相册</option></select></label>
        {targetAlbum === "__new__" && <><label><span>新相册名称</span><input autoFocus value={newAlbumName} onChange={(event) => setNewAlbumName(event.target.value)} placeholder="例如：2026-08-10 青岛旅行" maxLength={180} /></label><label><span>相册类型</span><select value={newAlbumCategory} onChange={(event) => setNewAlbumCategory(event.target.value)}>{(filters?.album_types ?? []).map((type) => <option key={type.name}>{type.name}</option>)}</select></label></>}
        <div className="update-library-note">只索引新增或变化的文件。原片不会被移动、删除或改写。</div>
        <footer><button type="button" className="toolbar-button" onClick={() => setUpdateOpen(false)}>取消</button><button className="toolbar-button primary" disabled={!targetAlbum || (targetAlbum === "__new__" && !newAlbumName.trim())}>开始更新</button></footer>
      </form></ModalShell>}
      {selectedGroup && <SimilarityPickerModal group={selectedGroup} close={closeGroup} openCapture={openCapture} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} restoreGroupingRevision={restoreGroupingRevision} />}
    </>
  );
}

function HomeView({ overview, statistics, archive, activeBaseline, library, filters, task, capabilities, openPhotos, openAlbums, openAlbum, openBursts, openStatistics, continueLabel, continueWork, openUnassigned, openMaintenance, openCapture }: {
  overview: Overview | null;
  statistics: Statistics | null;
  archive: ArchiveStatus | null;
  activeBaseline: ArchiveStatus | null;
  library: LibraryCapturesResponse | null;
  filters: LibraryFilters | null;
  task: Task | null;
  capabilities: SystemCapabilities | null;
  openPhotos: () => void;
  openAlbums: () => void;
  openAlbum: (albumId: number) => void;
  openBursts: () => void;
  openStatistics: () => void;
  continueLabel: string;
  continueWork: () => void;
  openUnassigned: () => void;
  openMaintenance: () => void;
  openCapture: (captureId: number, context?: number[]) => void;
}) {
  const pendingEvents = overview?.structure.unconfirmed_event_count ?? 0;
  const unassigned = overview?.structure.unassigned_capture_count ?? 0;
  const archiveIssue = archive?.comparison && !archive.comparison.healthy;
  const activeIssue = activeBaseline?.comparison && !activeBaseline.comparison.healthy;
  const monthRows = statistics?.months ?? [];
  const latestMonth = monthRows[monthRows.length - 1] ?? null;
  const hasPending = pendingEvents > 0 || unassigned > 0 || Boolean(archiveIssue) || Boolean(activeIssue);
  const recentAlbums = (filters?.albums ?? []).slice(0, 4);
  const topCamera = statistics?.cameras[0];
  const topLens = statistics?.lenses[0];
  return <>
    <section className="home-metrics">
      <article><span>全部照片</span><strong>{overview ? numberFormat.format(overview.capture_total) : "—"}</strong><small>{overview ? formatBytes(overview.files.size_bytes) : ""}</small></article>
      <article><span>拍摄相册</span><strong>{overview?.structure.event_count ?? "—"}</strong><small>{pendingEvents} 个名称待确认</small></article>
      <article><span>最近拍摄月</span><strong>{latestMonth ? numberFormat.format(latestMonth.count) : "—"}</strong><small>{latestMonth?.month ?? "暂无拍摄日期"}</small></article>
    </section>
    {overview?.capture_total === 0 && <section className="panel welcome-panel">
      <div><span className="section-kicker">本地图库</span><h3>从你的照片目录开始</h3><p>照片保持只读，索引、评分和缩略图保存在独立工作目录。</p></div>
      <div className="welcome-capabilities"><span><b>图库</b>{capabilities?.library_root ?? "正在读取配置"}</span><span><b>元数据</b>{capabilities?.metadata.message ?? "正在检测"}</span><button className="toolbar-button primary" onClick={openPhotos}>打开照片图库</button></div>
    </section>}
    {overview && overview.capture_total > 0 && <section className="home-workspace-grid">
      <section className="home-continue-card"><span className="section-kicker">继续上次工作</span><h3>{continueLabel}</h3><p>回到最近使用的功能，当前图库和筛选状态不会被重新分析。</p><button className="primary-action" onClick={continueWork}><span>继续浏览</span><b>→</b></button><div><button onClick={openPhotos}>照片图库</button><button onClick={openBursts}>相似组选片</button><button onClick={openStatistics}>摄影统计</button></div></section>
      <section className="panel home-albums-panel"><div className="panel-heading"><div><h3>最近相册</h3></div><button className="text-action" onClick={openAlbums}>管理全部</button></div><div className="home-album-list">{recentAlbums.map((album) => <button key={album.id} onClick={() => openAlbum(album.id)}><span><strong>{album.name}</strong><small>{album.category}</small></span><b>{album.capture_count} 张</b></button>)}</div></section>
    </section>}
    <section className="home-management-grid">
      <section className="panel recent-photos-panel"><div className="panel-heading"><div><h3>最近照片</h3></div><button className="text-action" onClick={openPhotos}>查看全部</button></div><div className="recent-photo-grid">
        {(library?.items ?? []).slice(0, 8).map((item, _index, recent) => <button key={item.id} onClick={() => openCapture(item.id, recent.map((entry) => entry.id))}><img src={item.thumbnail_url} alt={item.stem} /><span>{item.stem}</span></button>)}
      </div></section>
      <section className="panel pending-panel"><div className="panel-heading"><div><h3>待处理</h3></div></div><div className="pending-list">
        {pendingEvents > 0 && <button onClick={openAlbums}><span><strong>{pendingEvents}</strong> 个相册名称待确认</span><b>整理相册</b></button>}
        {unassigned > 0 && <button onClick={openUnassigned}><span><strong>{unassigned}</strong> 张照片尚未归入相册</span><b>查看照片</b></button>}
        {archiveIssue && <button onClick={openMaintenance}><span>历史原片完整性检查存在异常</span><b>查看状态</b></button>}
        {activeIssue && <button onClick={openMaintenance}><span>活动图库完整性检查存在异常</span><b>查看状态</b></button>}
        {!hasPending && <div className="empty-state">当前没有需要及时处理的项目。</div>}
      </div></section>
    </section>
    {overview && overview.capture_total > 0 && <section className="panel home-insights"><div className="panel-heading"><div><h3>本月摄影摘要</h3></div><button className="text-action" onClick={openStatistics}>查看完整统计</button></div><div><article><span>最近月份</span><strong>{latestMonth?.month ?? "—"}</strong><small>{latestMonth ? `${numberFormat.format(latestMonth.count)} 张 · ${latestMonth.user_picks} 张入选` : "暂无数据"}</small></article><article><span>最常用相机</span><strong>{topCamera?.camera_model ?? "—"}</strong><small>{topCamera ? `${numberFormat.format(topCamera.count)} 次拍摄` : "暂无器材信息"}</small></article><article><span>最常用镜头</span><strong>{topLens?.lens_model ?? "—"}</strong><small>{topLens ? `${numberFormat.format(topLens.count)} 次拍摄` : "暂无镜头信息"}</small></article></div></section>}
    {task && task.status !== "idle" && <section className="home-current-task"><TaskCard task={task} /></section>}
  </>;
}

function AnalysisView({ analysis, preflight, quality, qualityFilter, qualitySearch, setQualityFilter, setQualitySearch, task, startQuality, startDetailBackfill, resumeDetailBackfill, startAi, saveReview, cancelTask, pauseTask, resumeAi, retryAiFailures, openCapture, changeQualityPage, changeQualityPageSize }: {
  analysis: AnalysisOverview | null;
  preflight: AiPreflight | null;
  quality: QualityResponse | null;
  qualityFilter: QualityReviewFilter;
  qualitySearch: string;
  setQualityFilter: (filter: QualityReviewFilter) => void;
  setQualitySearch: (search: string) => void;
  task: Task | null;
  startQuality: () => void;
  startDetailBackfill: () => void;
  resumeDetailBackfill: () => void;
  startAi: (mode: "benchmark" | "recommended", limit: number) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  cancelTask: () => void;
  pauseTask: () => void;
  resumeAi: (runId: number) => void;
  retryAiFailures: (runId: number) => void;
  openCapture: (captureId: number, context?: number[]) => void;
  changeQualityPage: (offset: number) => void;
  changeQualityPageSize: (limit: number) => void;
}) {
  const summary = analysis?.quality;
  const ai = analysis?.ai;
  const running = task?.status === "running" || task?.status === "paused";
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
          <div className="analysis-command-panel">
            <div className="analysis-command-group"><span>技术检测</span><button className="toolbar-button primary" onClick={startQuality} disabled={running}>分析新增照片</button></div>
            <div className="analysis-command-divider" />
            <div className="analysis-command-group"><span>详情数据</span><button className="toolbar-button" onClick={startDetailBackfill} disabled={running || (!analysis?.detail_data.metadata_pending && !analysis?.detail_data.histograms_pending)}>补全拍摄信息与直方图</button>{task?.status === "paused" && task.stage.startsWith("detail-") && <button className="toolbar-button primary" onClick={resumeDetailBackfill}>继续补全</button>}<small>{analysis ? `元数据待补 ${numberFormat.format(analysis.detail_data.metadata_pending)} · 直方图待补 ${numberFormat.format(analysis.detail_data.histograms_pending)}` : "正在读取状态"}</small></div>
            <div className="analysis-command-divider" />
            <div className="analysis-command-group model"><span>本地模型</span><button className="toolbar-button" onClick={() => startAi("benchmark", 10)} disabled={running || !summary?.analyzed || !preflight?.ready}>快速验证 · 10 张</button><label><select value={batchSize} onChange={(event) => setBatchSize(Number(event.target.value))} disabled={running}>{[25, 50, 100, 200, 500].map((size) => <option key={size} value={size}>{size} 张</option>)}</select><small>{estimatedBatchSeconds ? `约 ${formatDuration(estimatedBatchSeconds)}` : "每批数量"}</small></label><button className="toolbar-button primary" onClick={() => startAi("recommended", batchSize)} disabled={running || !summary?.analyzed || !preflight?.ready}>运行所选批次</button></div>
            {ai?.latest_run && ["failed", "cancelled", "paused"].includes(ai.latest_run.status) && <button className="toolbar-button" onClick={() => resumeAi(ai.latest_run!.id)} disabled={running}>继续上次任务</button>}
            {ai?.latest_run && ai.latest_run.status === "complete" && ai.latest_run.failed_count > 0 && <button className="toolbar-button" onClick={() => retryAiFailures(ai.latest_run!.id)} disabled={running || !preflight?.ready}>重试失败项</button>}
          </div>
        </div>
        <div className={`runtime-card ${preflight?.ready ? "ready" : ""}`}>
          <span>模型运行环境</span><strong>{preflight?.ready ? "预检通过" : "未就绪"}</strong><small>{preflight ? (preflight.ready ? `${preflight.quantization.toUpperCase()} · ${formatFileSize(preflight.model_bytes)} · ${preflight.image_max_edge ?? 1280}px · 显存上限 ${preflight.gpu_memory_limit_gb}GB` : preflight.blockers.join("；")) : analysis?.runtime.message ?? "正在检查"}</small>
          {gpu?.available && <small>{gpu.name} · GPU {gpu.utilization_percent}% · 显存 {((gpu.memory_used_mb ?? 0) / 1024).toFixed(1)} / {((gpu.memory_total_mb ?? 0) / 1024).toFixed(1)} GB · {gpu.temperature_c}°C</small>}
        </div>
      </section>
      <TaskCard task={taskBelongsTo(task, "analysis") ? task : null} cancel={cancelTask} pause={pauseTask} />
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
          {ai.recent_results.map((result) => <button key={result.id} className="ai-result-card" onClick={() => openCapture(result.capture_id, ai.recent_results.map((entry) => entry.capture_id))}>
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
          {resultPage.items.map((result) => <button key={result.id} className="ai-result-card" onClick={() => openCapture(result.capture_id, resultPage.items.map((entry) => entry.capture_id))}>
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
      <section className="panel quality-review-panel">
        <div className="panel-heading"><div><span className="section-kicker">照片复核</span><h3>问题与改进建议</h3></div><span className="batch-count">点击照片查看完整分析</span></div>
        <div className="quality-review-toolbar">
          <input value={qualitySearch} onChange={(event) => setQualitySearch(event.target.value)} placeholder="搜索照片或相册" />
          <select value={qualityFilter} onChange={(event) => setQualityFilter(event.target.value as QualityReviewFilter)}><option value="all">全部已分析</option><option value="problems">发现问题</option><option value="low_score">技术分低于 70</option><option value="with_model">已有模型建议</option><option value="without_model">等待模型建议</option><option value="unrated">尚未评分</option></select>
        </div>
        <div className="quality-review-grid">
          {(quality?.items ?? []).map((item) => (
            <article className="quality-review-card" key={item.capture_id}>
              <button className="quality-review-photo" onClick={() => openCapture(item.capture_id, (quality?.items ?? []).map((entry) => entry.capture_id))}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} /><span>{Math.round(item.technical_score)} 分 · {technicalGrade(item.technical_score)}</span></button>
              <div className="quality-review-copy"><div><strong>{item.stem}</strong><small>{item.event_name} · {item.category}{item.auto_pick ? " · 组内推荐" : ""}</small></div><p>{item.ai_result?.quality_summary ?? (item.issues[0]?.message || "未发现明确技术问题")}</p><div className="quality-advice"><b>{item.ai_result ? "模型建议" : "技术建议"}</b><span>{item.ai_result ? modelAdvice(item.ai_result) : (item.issues[0] ? technicalAdvice(item.issues[0].code) : "当前技术指标正常，可结合构图和表达继续人工判断。")}</span></div></div>
              <div className="review-controls"><button onClick={() => openCapture(item.capture_id, (quality?.items ?? []).map((entry) => entry.capture_id))}>查看详情</button>
                <select aria-label={`${item.stem} 人工星级`} value={item.user_rating ?? ""} onChange={(event) => saveReview(item.capture_id, { user_rating: event.target.value ? Number(event.target.value) : null, user_pick: Boolean(item.user_pick), user_reject: Boolean(item.user_reject), user_note: item.user_note })}>
                  <option value="">人工星级</option><option value="1">1 星</option><option value="2">2 星</option><option value="3">3 星</option><option value="4">4 星</option><option value="5">5 星</option>
                </select>
              </div>
            </article>
          ))}
          {!quality?.items.length && <div className="empty-state">当前筛选条件没有照片。尚未分析时，请先运行技术检测。</div>}
        </div>
        {quality && <Pagination count={quality.count} limit={quality.limit} offset={quality.offset} onChange={changeQualityPage} onLimitChange={changeQualityPageSize} />}
      </section>
    </>
  );
}

function Distribution({ title, rows, labelKey, onSelect, selectHint }: {
  title: string;
  rows: StatisticRow[];
  labelKey: string;
  onSelect?: (label: string) => void;
  selectHint?: string;
}) {
  const maximum = Math.max(1, ...rows.map((row) => row.count));
  return (
    <section className="panel distribution-panel">
      <div className="panel-heading"><div><span className="section-kicker">分布</span><h3>{title}</h3></div>{onSelect && <span className="batch-count">{selectHint ?? "点击跳到对应照片"}</span>}</div>
      <div className="bar-list">
        {rows.map((row, index) => {
          const content = <>
            <span title={String(row[labelKey])}>{String(row[labelKey])}</span>
            <div><i style={{ width: `${Math.max(2, row.count / maximum * 100)}%` }} /></div>
            <strong>{numberFormat.format(row.count)}</strong>
            <small>{row.average_score == null ? "未评分" : `均分 ${row.average_score}`}</small>
          </>;
          return onSelect
            ? <button type="button" className="bar-row bar-row-link" key={`${String(row[labelKey])}-${index}`} onClick={() => onSelect(String(row[labelKey]))}>{content}</button>
            : <div className="bar-row" key={`${String(row[labelKey])}-${index}`}>{content}</div>;
        })}
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

function ArchiveView({ archive, activeLibrary, createBaseline, createActiveBaseline, checkIntegrity }: {
  archive: ArchiveStatus | null;
  activeLibrary: ArchiveStatus | null;
  createBaseline: () => void;
  createActiveBaseline: () => void;
  checkIntegrity: (scope: "archive" | "active") => Promise<void>;
}) {
  const [checking, setChecking] = useState<"archive" | "active" | null>(null);
  const runCheck = async (scope: "archive" | "active") => {
    setChecking(scope);
    try { await checkIntegrity(scope); } finally { setChecking(null); }
  };
  const baselineCard = (title: string, status: ArchiveStatus | null, create: () => void, scope: "archive" | "active") => (
    <section className="panel archive-panel">
      <div className="panel-heading"><div><span className="section-kicker">{scope === "archive" ? "历史存档" : "当前使用"}</span><h3>{title}</h3></div><button className="toolbar-button" disabled={checking !== null} onClick={() => void runCheck(scope)}>{checking === scope ? "正在检查" : "立即检查"}</button></div>
      {status?.baseline ? <div className="archive-status">
        <span className={`archive-health ${status.comparison?.healthy ? "healthy" : "warning"}`}>{status.comparison?.healthy ? "上次检查正常" : status.comparison ? "上次检查发现差异" : "尚未检查"}</span>
        <strong>{status.baseline.name}</strong>
        <small>基线 {formatDate(status.baseline.created_at)} · {numberFormat.format(status.baseline.file_count)} 个文件 · {formatBytes(status.baseline.total_bytes)}</small>
        <small>上次检查 {status.comparison?.checked_at ? formatDate(status.comparison.checked_at) : "尚未执行"}</small>
        <div className="archive-counts"><div><b>{status.comparison?.missing ?? "—"}</b><span>缺失</span></div><div><b>{status.comparison?.changed ?? "—"}</b><span>变化</span></div><div><b>{status.comparison?.new ?? "—"}</b><span>新增</span></div></div>
        {!!status.comparison?.samples.length && <div className="integrity-samples">{status.comparison.samples.slice(0, 8).map((sample) => <div key={`${sample.status}-${sample.relative_path}`}><span>{sample.status}</span><strong>{sample.relative_path}</strong></div>)}</div>}
      </div> : <div className="archive-status"><p>尚未建立完整性基线。基线只记录路径、大小和修改时间，不复制或修改照片。</p><button className="primary-action" onClick={create}><span>建立基线</span><b>→</b></button></div>}
    </section>
  );
  return <>
    <section className="compact-summary"><div><span className="section-kicker">系统维护</span><h2>图库完整性</h2><p>需要时手动核对磁盘文件；日常浏览只读取上次结果，不扫描照片目录。</p></div></section>
    <section className="statistics-grid">
      {baselineCard("历史存档", archive, createBaseline, "archive")}
      {baselineCard("活动图库", activeLibrary, createActiveBaseline, "active")}
    </section>
    <section className="integrity-guidance"><strong>适合什么时候检查</strong><span>更换硬盘、恢复备份、手动整理目录、异常断电或每隔一至三个月例行检查时使用。检查只报告差异，不会修改或修复照片。</span></section>
  </>;
}

function StatisticsView({ statistics, openLibraryWith }: {
  statistics: Statistics | null;
  openLibraryWith: (changes: Partial<LibraryQuery>) => void;
}) {
  const summary = statistics?.summary;
  const selection = statistics?.selection;
  const openMonth = (month: string) => {
    const [year, monthPart] = month.split("-").map(Number);
    if (!year || !monthPart) return;
    const lastDay = new Date(year, monthPart, 0).getDate();
    openLibraryWith({ dateFrom: `${month}-01`, dateTo: `${month}-${String(lastDay).padStart(2, "0")}` });
  };
  return (
    <>
      <section className="structure-hero statistics-hero">
        <div><span className="section-kicker">摄影数据</span><h2>拍摄统计</h2><p>查看题材、器材和拍摄参数分布。</p></div>
        <div className="structure-stat"><strong>{summary ? numberFormat.format(summary.capture_count) : "—"}</strong><span>个个人拍摄单元</span></div>
      </section>
      <section className="metric-grid">
        <article><span>拍摄时间跨度</span><strong className="text-value">{summary?.first_capture?.slice(0, 10) ?? "—"}</strong><small>至 {summary?.last_capture?.slice(0, 10) ?? "—"}</small></article>
        <article><span>已完成质量分析</span><strong>{summary ? numberFormat.format(summary.quality_analyzed) : "—"}</strong><small>平均分 {summary?.average_technical_score ?? "—"}</small></article>
        <article><span>连拍入选</span><strong>{summary ? numberFormat.format(summary.user_picks) : "—"}</strong><small>组内最终选择</small></article>
        <article><span>连拍排除</span><strong>{summary ? numberFormat.format(summary.user_rejects) : "—"}</strong><small>不会删除原片</small></article>
        <article><span>选片进度</span><strong>{selection ? `${numberFormat.format(selection.groups_reviewed ?? 0)}/${numberFormat.format(selection.group_total)}` : "—"}</strong><small>已处理相似组 · 平均每组入选 {selection?.average_picks_per_group ?? "—"} 张</small></article>
      </section>
      <section className="statistics-grid">
        <Distribution title="题材占比" rows={statistics?.categories ?? []} labelKey="category" onSelect={(category) => openLibraryWith({ category })} />
        <Distribution title="主要相机" rows={statistics?.cameras ?? []} labelKey="camera_model" onSelect={(camera) => openLibraryWith({ camera })} />
        <Distribution title="主要镜头" rows={statistics?.lenses ?? []} labelKey="lens_model" onSelect={(lens) => openLibraryWith({ lens })} />
        <Distribution title="焦段习惯" rows={statistics?.focal_ranges ?? []} labelKey="bucket" />
        <Distribution title="ISO分布" rows={statistics?.iso_ranges ?? []} labelKey="bucket" />
        <Distribution title="光圈分布" rows={statistics?.aperture_ranges ?? []} labelKey="bucket" />
        <Distribution title="快门分布" rows={statistics?.shutter_ranges ?? []} labelKey="bucket" />
        <Distribution title="曝光补偿" rows={statistics?.exposure_compensation_ranges ?? []} labelKey="bucket" />
      </section>
      <section className="statistics-grid">
        <section className="panel lens-efficiency-panel">
          <div className="panel-heading"><div><span className="section-kicker">器材效能</span><h3>镜头出片率</h3></div></div>
          <div className="lens-efficiency-list">
            {(statistics?.lenses ?? []).map((lens) => <button key={lens.lens_model} onClick={() => openLibraryWith({ lens: lens.lens_model })}>
              <span>{lens.lens_model}</span>
              <em>{numberFormat.format(lens.count)} 张 · 均分 {lens.average_score ?? "—"}</em>
              <b>{lens.pick_rate == null ? "—" : `入选率 ${lens.pick_rate}%`}</b>
            </button>)}
            {!(statistics?.lenses ?? []).length && <div className="empty-state">暂无镜头数据。</div>}
          </div>
        </section>
        <section className="panel issue-stats-panel">
          <div className="panel-heading"><div><span className="section-kicker">拍摄复盘</span><h3>高频问题</h3></div><span className="batch-count">点击查看有问题的照片</span></div>
          <div className="issue-stats-list">
            {(statistics?.issues ?? []).slice(0, 8).map((issue) => <button key={issue.code} onClick={() => openLibraryWith({ quality: "problems" })}>
              <span>{issue.message}</span>
              <b>{numberFormat.format(issue.count)}</b>
            </button>)}
            {!(statistics?.issues ?? []).length && <div className="empty-state">尚未发现技术问题，或还没有运行质量分析。</div>}
          </div>
        </section>
      </section>
      <section className="panel month-panel">
        <div className="panel-heading"><div><span className="section-kicker">时间趋势</span><h3>最近拍摄月份</h3></div><span className="batch-count">点击月份跳到对应照片</span></div>
        <div className="month-strip">{(statistics?.months ?? []).slice(-24).map((month) => <button type="button" key={month.month} onClick={() => openMonth(month.month)}><span>{month.month}</span><i style={{ height: `${Math.max(8, Math.min(100, month.count / Math.max(1, ...(statistics?.months ?? []).map((item) => item.count)) * 100))}%` }} /><strong>{month.count}</strong><small>{month.average_score ?? "—"}</small></button>)}</div>
      </section>
    </>
  );
}

function LightroomView({ status, manifest, capabilities, generateManifest }: {
  status: LightroomStatus | null;
  manifest: LightroomManifest | null;
  capabilities: SystemCapabilities | null;
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
        <article><span>连拍入选</span><strong>{status ? numberFormat.format(status.user_picks) : "—"}</strong><small>准备清单中的pick字段</small></article>
        <article><span>连拍排除</span><strong>{status ? numberFormat.format(status.user_rejects) : "—"}</strong><small>只标记，不删除</small></article>
      </section>
      <section className="lightroom-grid">
        <section className="panel safety-panel"><div className="panel-heading"><div><span className="section-kicker">安全状态</span><h3>本轮只生成报告</h3></div></div><div className="safety-list"><div><b>✓</b><span><strong>照片目录保持只读</strong><small>{capabilities?.library_root ?? "当前配置的照片目录"} 不会被移动、改名或改写</small></span></div><div><b>✓</b><span><strong>原片元数据写入关闭</strong><small>不会在照片旁创建或修改 XMP 等附属文件</small></span></div><div><b>✓</b><span><strong>输出到独立工作目录</strong><small>{capabilities?.workspace_root ?? "应用工作目录"}</small></span></div><div><b>✓</b><span><strong>JPG 与 RAW 同步</strong><small>同一拍摄单元共享评级和标签</small></span></div></div></section>
        <section className="panel manifest-panel"><div className="panel-heading"><div><span className="section-kicker">最近生成</span><h3>Lightroom准备文件</h3></div></div>{manifest ? <div className="manifest-result"><strong>{numberFormat.format(manifest.capture_count)} 个拍摄单元</strong><span>{numberFormat.format(manifest.rated_count)} 个已有评级 · {formatBytes(manifest.source_bytes)} 原始文件索引</span><a href={manifest.csv_url}>下载CSV清单</a><a href={manifest.json_url}>下载完整JSON</a><small>下载的是清单，不是照片副本。</small></div> : <div className="empty-state">尚未在本次启动中生成清单。</div>}</section>
      </section>
    </>
  );
}

function SettingsView({ status, task, save }: {
  status: SettingsStatus | null;
  task: Task | null;
  save: (settings: EditableSettings) => Promise<SettingsStatus>;
}) {
  const [draft, setDraft] = useState<EditableSettings | null>(status?.configured ?? null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => setDraft(status?.configured ?? null), [status?.configured]);
  if (!draft) return <div className="empty-state">正在读取配置…</div>;
  const update = <S extends keyof EditableSettings, K extends keyof EditableSettings[S]>(section: S, key: K, value: EditableSettings[S][K]) => {
    setDraft((current) => current ? { ...current, [section]: { ...current[section], [key]: value } } : current);
  };
  const submit = async () => {
    setSaving(true);
    setNotice(null);
    try {
      const result = await save(draft);
      setNotice(result.message ?? "配置已保存，重启应用后生效。");
    } finally {
      setSaving(false);
    }
  };
  const busy = task?.status === "running" || task?.status === "paused";
  return <div className="settings-page">
    {status?.restart_required && <section className="settings-restart-banner"><strong>配置已保存，等待重启生效</strong><span>当前服务仍使用原配置；不会自动搬运照片或数据库。{status.backup_path ? ` 旧配置：${status.backup_path}` : ""}</span></section>}
    <section className="panel settings-section">
      <div className="panel-heading"><div><span className="section-kicker">存储位置</span><h3>图库与应用数据</h3></div></div>
      <div className="settings-form-grid">
        <label className="wide"><span>照片目录</span><input value={draft.library.originals} onChange={(event) => update("library", "originals", event.target.value)} /><small>必须是已存在目录。应用只读取照片，不会自动复制或迁移。</small></label>
        <label className="wide"><span>工作目录</span><input value={draft.library.workspace} onChange={(event) => update("library", "workspace", event.target.value)} /><small>数据库、报告和用户选择保存在这里；修改路径不会移动旧数据。</small></label>
        <label className="wide"><span>缓存目录</span><input value={draft.cache.root} onChange={(event) => update("cache", "root", event.target.value)} /><small>只保存可重建的缩略图和临时数据。</small></label>
        <label><span>缓存上限 GB</span><input type="number" min="1" value={draft.cache.max_size_gb} onChange={(event) => update("cache", "max_size_gb", Number(event.target.value))} /></label>
        <label><span>缩略图上限 GB</span><input type="number" min="1" value={draft.cache.thumbnail_max_size_gb} onChange={(event) => update("cache", "thumbnail_max_size_gb", Number(event.target.value))} /></label>
      </div>
      <div className="effective-settings"><span>当前实际图库 <b>{status?.effective.library_root}</b></span><span>当前实际工作目录 <b>{status?.effective.workspace_root}</b></span><small>已迁移的数据库会优先使用其活动图库记录。要连接一套全新图库，建议同时选择新的工作目录。</small></div>
    </section>
    <section className="panel settings-section">
      <div className="panel-heading"><div><span className="section-kicker">分析参数</span><h3>元数据、RAW 与连拍</h3></div></div>
      <div className="settings-form-grid">
        <label className="wide"><span>ExifTool 路径（可留空自动发现）</span><input value={draft.tools.exiftool} onChange={(event) => update("tools", "exiftool", event.target.value)} /></label>
        <label className="wide"><span>RAW 扩展名</span><input value={draft.analysis.raw_extensions.join(", ")} onChange={(event) => update("analysis", "raw_extensions", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} /><small>使用英文逗号分隔，例如 .raf, .dng, .cr3。</small></label>
        <label><span>连拍间隔秒</span><input type="number" min="0.1" max="60" step="0.1" value={draft.analysis.burst_time_gap_seconds} onChange={(event) => update("analysis", "burst_time_gap_seconds", Number(event.target.value))} /></label>
        <label><span>元数据批量大小</span><input type="number" min="1" max="1000" value={draft.analysis.metadata_batch_size} onChange={(event) => update("analysis", "metadata_batch_size", Number(event.target.value))} /></label>
      </div>
    </section>
    <section className="panel settings-section">
      <div className="panel-heading"><div><span className="section-kicker">可选能力</span><h3>本地模型</h3></div></div>
      <div className="settings-form-grid">
        <label className="wide"><span>模型 Python</span><input value={draft.models.python} onChange={(event) => update("models", "python", event.target.value)} placeholder="留空则关闭本地模型" /></label>
        <label className="wide"><span>模型目录</span><input value={draft.models.vision_language_model} onChange={(event) => update("models", "vision_language_model", event.target.value)} placeholder="留空则关闭本地模型" /></label>
        <label><span>量化方式</span><select value={draft.models.quantization} onChange={(event) => update("models", "quantization", event.target.value as "none" | "int8")}><option value="none">不量化</option><option value="int8">INT8</option></select></label>
        <label><span>显存上限 GB</span><input type="number" min="1" value={draft.models.gpu_memory_limit_gb} onChange={(event) => update("models", "gpu_memory_limit_gb", Number(event.target.value))} /></label>
        <label><span>最大输出 Tokens</span><input type="number" min="1" value={draft.models.max_new_tokens} onChange={(event) => update("models", "max_new_tokens", Number(event.target.value))} /></label>
        <label><span>图像最长边</span><input type="number" min="512" max="2048" value={draft.models.image_max_edge} onChange={(event) => update("models", "image_max_edge", Number(event.target.value))} /></label>
      </div>
    </section>
    <section className="panel settings-section safety-settings">
      <div><span className="section-kicker">固定安全边界</span><h3>这些开关不会因设置编辑而放宽</h3><p>本地离线、图库只读、禁止移动删除、禁止写入原片元数据与 XMP。</p></div>
      <div className="settings-actions"><span>{notice ?? (busy ? "后台任务运行或暂停期间不能保存配置。" : "保存时会备份旧配置，并在完整校验后原子替换。")}</span><button className="toolbar-button" onClick={() => setDraft(status?.configured ?? draft)} disabled={saving}>撤销修改</button><button className="toolbar-button primary" onClick={() => void submit()} disabled={saving || busy}>{saving ? "正在校验…" : "保存配置"}</button></div>
    </section>
  </div>;
}

function App() {
  const [view, setView] = useState<View>("home");
  const [lastWorkspaceView, setLastWorkspaceView] = useState<View>(() => {
    const saved = window.localStorage.getItem("tangerine-last-workspace") as View | null;
    return saved && saved !== "home" ? saved : "library";
  });
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = window.localStorage.getItem("tangerine-theme");
    return saved === "dark" ? "dark" : "light";
  });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [libraryCaptures, setLibraryCaptures] = useState<LibraryCapturesResponse | null>(null);
  const [libraryLandingSection, setLibraryLandingSection] = useState<LibrarySection>("photos");
  const [libraryOffset, setLibraryOffset] = useState(0);
  const [libraryQuery, setLibraryQuery] = useState<LibraryQuery>({
    pageSize: 40, albumId: "", category: "", camera: "", lens: "",
    rating: "", selection: "", quality: "", dateFrom: "", dateTo: "", search: "", sort: "newest", collapseGroups: false,
  });
  const [libraryFilters, setLibraryFilters] = useState<LibraryFilters | null>(null);
  const [albumOffset, setAlbumOffset] = useState(0);
  const [albumPageSize, setAlbumPageSize] = useState(40);
  const [events, setEvents] = useState<EventsResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisOverview | null>(null);
  const [aiPreflight, setAiPreflight] = useState<AiPreflight | null>(null);
  const [quality, setQuality] = useState<QualityResponse | null>(null);
  const [qualityOffset, setQualityOffset] = useState(0);
  const [qualityPageSize, setQualityPageSize] = useState(40);
  const [qualityFilter, setQualityFilter] = useState<QualityReviewFilter>("all");
  const [qualitySearch, setQualitySearch] = useState("");
  const [similarityGroups, setSimilarityGroups] = useState<SimilarityGroupsResponse | null>(null);
  const [groupOffset, setGroupOffset] = useState(0);
  const [groupPageSize, setGroupPageSize] = useState(40);
  const [groupReviewFilter, setGroupReviewFilter] = useState<"all" | "pending">("pending");
  const [groupAlbumId, setGroupAlbumId] = useState("");
  const [selectedGroup, setSelectedGroup] = useState<SimilarityGroupDetail | null>(null);
  const [captureDetail, setCaptureDetail] = useState<CaptureDetail | null>(null);
  const [detailContext, setDetailContext] = useState<number[]>([]);
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [equipment, setEquipment] = useState<EquipmentCatalog | null>(null);
  const [archive, setArchive] = useState<ArchiveStatus | null>(null);
  const [activeLibraryBaseline, setActiveLibraryBaseline] = useState<ArchiveStatus | null>(null);
  const [lightroomStatus, setLightroomStatus] = useState<LightroomStatus | null>(null);
  const [lightroomManifest, setLightroomManifest] = useState<LightroomManifest | null>(null);
  const [capabilities, setCapabilities] = useState<SystemCapabilities | null>(null);
  const [settingsStatus, setSettingsStatus] = useState<SettingsStatus | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const refreshSequence = useRef(0);
  const toastSequence = useRef(0);
  const reviewQueues = useRef(new Map<number, Promise<void>>());
  const reviewVersions = useRef(new Map<number, number>());
  const reviewAggregateTimer = useRef<number | null>(null);

  const pushToast = useCallback((kind: Toast["kind"], message: string, actionLabel?: string, action?: () => void) => {
    const id = ++toastSequence.current;
    setToasts((current) => [...current.slice(-3), { id, kind, message, actionLabel, action }]);
    window.setTimeout(
      () => setToasts((current) => current.filter((toast) => toast.id !== id)),
      kind === "error" ? 6000 : action ? 8000 : 2400,
    );
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("tangerine-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (view === "home") return;
    setLastWorkspaceView(view);
    window.localStorage.setItem("tangerine-last-workspace", view);
  }, [view]);
  useEffect(() => {
    if (view === "bursts") return;
    setSelectedGroup(null);
    setGroupAlbumId("");
  }, [view]);

  const refreshLibrary = useCallback(async () => {
    const requestSequence = ++refreshSequence.current;
    const libraryParameters = new URLSearchParams({
      limit: String(libraryQuery.pageSize), offset: String(libraryOffset), sort: libraryQuery.sort,
    });
    if (libraryQuery.albumId === "__unassigned__") libraryParameters.set("unassigned", "true");
    else if (libraryQuery.albumId) libraryParameters.set("album_id", libraryQuery.albumId);
    if (libraryQuery.category) libraryParameters.set("category", libraryQuery.category);
    if (libraryQuery.camera) libraryParameters.set("camera_model", libraryQuery.camera);
    if (libraryQuery.lens) libraryParameters.set("lens_model", libraryQuery.lens);
    if (libraryQuery.rating) libraryParameters.set("rating", libraryQuery.rating);
    if (libraryQuery.selection) libraryParameters.set("selection", libraryQuery.selection);
    if (libraryQuery.quality) libraryParameters.set("quality", libraryQuery.quality);
    if (libraryQuery.dateFrom) libraryParameters.set("date_from", libraryQuery.dateFrom);
    if (libraryQuery.dateTo) libraryParameters.set("date_to", libraryQuery.dateTo);
    if (libraryQuery.search.trim()) libraryParameters.set("search", libraryQuery.search.trim());
    if (libraryQuery.albumId && libraryQuery.collapseGroups) libraryParameters.set("collapse_groups", "true");
    const results = await Promise.allSettled([
      getJson<Overview>("/api/overview"),
      getJson<LibraryCapturesResponse>(`/api/library/captures?${libraryParameters.toString()}`),
      getJson<LibraryFilters>("/api/library/filters"),
      getJson<EventsResponse>(`/api/albums?limit=${albumPageSize}&offset=${albumOffset}`),
      getJson<AnalysisOverview>("/api/analysis/overview"),
      getJson<AiPreflight>("/api/ai/preflight"),
      getJson<QualityResponse>(`/api/quality?${new URLSearchParams({ limit: String(qualityPageSize), offset: String(qualityOffset), review_filter: qualityFilter, ...(qualitySearch.trim() ? { search: qualitySearch.trim() } : {}) }).toString()}`),
      getJson<SimilarityGroupsResponse>(similarityGroupsUrl(groupPageSize, groupOffset, groupReviewFilter, groupAlbumId)),
      getJson<Statistics>("/api/statistics"),
      getJson<EquipmentCatalog>("/api/equipment"),
      getJson<ArchiveStatus>("/api/archive/status"),
      getJson<ArchiveStatus>("/api/active-library/baseline/status"),
      getJson<LightroomStatus>("/api/lightroom/status"),
      getJson<SystemCapabilities>("/api/system/capabilities"),
      getJson<SettingsStatus>("/api/settings"),
    ] as const);
    if (requestSequence !== refreshSequence.current) return;
    const [overviewData, libraryData, filterData, eventData, analysisData, preflightData, qualityData, groupData, statisticsData, equipmentData, archiveData, activeBaselineData, lightroomData, capabilitiesData, settingsData] = results;
    if (overviewData.status === "fulfilled") setOverview(overviewData.value);
    if (libraryData.status === "fulfilled") setLibraryCaptures(libraryData.value);
    if (filterData.status === "fulfilled") setLibraryFilters(filterData.value);
    if (eventData.status === "fulfilled") setEvents(eventData.value);
    if (analysisData.status === "fulfilled") setAnalysis(analysisData.value);
    if (preflightData.status === "fulfilled") setAiPreflight(preflightData.value);
    if (qualityData.status === "fulfilled") setQuality(qualityData.value);
    if (groupData.status === "fulfilled") setSimilarityGroups(groupData.value);
    if (statisticsData.status === "fulfilled") setStatistics(statisticsData.value);
    if (equipmentData.status === "fulfilled") setEquipment(equipmentData.value);
    if (archiveData.status === "fulfilled") setArchive(archiveData.value);
    if (activeBaselineData.status === "fulfilled") setActiveLibraryBaseline(activeBaselineData.value);
    if (lightroomData.status === "fulfilled") setLightroomStatus(lightroomData.value);
    if (capabilitiesData.status === "fulfilled") setCapabilities(capabilitiesData.value);
    if (settingsData.status === "fulfilled") setSettingsStatus(settingsData.value);
    const failed = results.find((result) => result.status === "rejected");
    if (failed?.status === "rejected") setError(failed.reason instanceof Error ? failed.reason.message : String(failed.reason));
  }, [albumOffset, albumPageSize, groupAlbumId, groupOffset, groupPageSize, groupReviewFilter, libraryOffset, libraryQuery, qualityFilter, qualityOffset, qualityPageSize, qualitySearch]);

  useEffect(() => {
    Promise.all([refreshLibrary(), getJson<Task>("/api/tasks/current").then(setTask)]).catch(
      (reason: Error) => setError(reason.message),
    );
    // Initial full snapshot only. Page filters have scoped effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const parameters = new URLSearchParams({
        limit: String(libraryQuery.pageSize), offset: String(libraryOffset), sort: libraryQuery.sort,
      });
      if (libraryQuery.albumId === "__unassigned__") parameters.set("unassigned", "true");
      else if (libraryQuery.albumId) parameters.set("album_id", libraryQuery.albumId);
      if (libraryQuery.category) parameters.set("category", libraryQuery.category);
      if (libraryQuery.camera) parameters.set("camera_model", libraryQuery.camera);
      if (libraryQuery.lens) parameters.set("lens_model", libraryQuery.lens);
      if (libraryQuery.rating) parameters.set("rating", libraryQuery.rating);
      if (libraryQuery.selection) parameters.set("selection", libraryQuery.selection);
      if (libraryQuery.quality) parameters.set("quality", libraryQuery.quality);
      if (libraryQuery.dateFrom) parameters.set("date_from", libraryQuery.dateFrom);
      if (libraryQuery.dateTo) parameters.set("date_to", libraryQuery.dateTo);
      if (libraryQuery.search.trim()) parameters.set("search", libraryQuery.search.trim());
      if (libraryQuery.albumId && libraryQuery.collapseGroups) parameters.set("collapse_groups", "true");
      getJson<LibraryCapturesResponse>(`/api/library/captures?${parameters}`, { signal: controller.signal })
        .then(setLibraryCaptures)
        .catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    }, libraryQuery.search ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [libraryOffset, libraryQuery]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<EventsResponse>(`/api/albums?limit=${albumPageSize}&offset=${albumOffset}`, { signal: controller.signal })
      .then(setEvents).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [albumOffset, albumPageSize]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const parameters = new URLSearchParams({ limit: String(qualityPageSize), offset: String(qualityOffset), review_filter: qualityFilter });
      if (qualitySearch.trim()) parameters.set("search", qualitySearch.trim());
      getJson<QualityResponse>(`/api/quality?${parameters}`, { signal: controller.signal })
        .then(setQuality).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    }, qualitySearch ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [qualityFilter, qualityOffset, qualityPageSize, qualitySearch]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<SimilarityGroupsResponse>(similarityGroupsUrl(groupPageSize, groupOffset, groupReviewFilter, groupAlbumId), { signal: controller.signal })
      .then(setSimilarityGroups).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [groupAlbumId, groupOffset, groupPageSize, groupReviewFilter]);

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

  const startScan = async (albumId?: number) => {
    if (!albumId) return;
    setError(null);
    try {
      setTask(await getJson<Task>("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ album_id: albumId }),
      }));
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

  const startDetailBackfill = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/detail-data/backfill", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const resumeDetailBackfill = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/detail-data/backfill/resume", { method: "POST" }));
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

  const pauseTask = async () => {
    if (!task?.stage.startsWith("detail-")) {
      await pauseAi();
      return;
    }
    setError(null);
    try {
      setTask(await getJson<Task>("/api/detail-data/backfill/pause", { method: "POST" }));
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

  const applyReview = useCallback((captureId: number, review: ReviewPayload) => {
    const patchQuality = (item: QualityItem) => item.capture_id === captureId ? {
      ...item,
      user_rating: review.user_rating,
      user_pick: Number(review.user_pick),
      user_reject: Number(review.user_reject),
      user_note: review.user_note,
    } : item;
    const patchGroup = (item: GroupCapture) => item.capture_id === captureId ? {
      ...item,
      user_rating: review.user_rating,
      user_pick: Number(review.user_pick),
      user_reject: Number(review.user_reject),
      user_note: review.user_note,
    } : item;
    setQuality((current) => current ? { ...current, items: current.items.map(patchQuality) } : current);
    setSelectedGroup((current) => current ? { ...current, items: current.items.map(patchGroup) } : current);
    setLibraryCaptures((current) => current ? {
      ...current,
      items: current.items.map((item) => item.id === captureId ? {
        ...item,
        user_rating: review.user_rating,
        user_pick: Number(review.user_pick),
        user_reject: Number(review.user_reject),
        user_note: review.user_note,
      } : item),
    } : current);
    setCaptureDetail((current) => current && current.id === captureId ? {
      ...current,
      user_rating: review.user_rating,
      user_pick: Number(review.user_pick),
      user_reject: Number(review.user_reject),
      user_note: review.user_note,
    } : current);
  }, []);

  const scheduleReviewAggregateRefresh = () => {
    if (reviewAggregateTimer.current != null) window.clearTimeout(reviewAggregateTimer.current);
    reviewAggregateTimer.current = window.setTimeout(() => {
      Promise.all([
        getJson<Overview>("/api/overview"),
        getJson<Statistics>("/api/statistics"),
        getJson<LightroomStatus>("/api/lightroom/status"),
        getJson<SimilarityGroupsResponse>(similarityGroupsUrl(groupPageSize, groupOffset, groupReviewFilter, groupAlbumId)),
      ]).then(([nextOverview, nextStatistics, nextLightroom, nextGroups]) => {
        setOverview(nextOverview);
        setStatistics(nextStatistics);
        setLightroomStatus(nextLightroom);
        setSimilarityGroups(nextGroups);
      }).catch((reason: Error) => setError(reason.message));
    }, 250);
  };

  const saveReview = async (captureId: number, review: ReviewPayload) => {
    applyReview(captureId, review);
    setSimilarityGroups((current) => {
      if (!current || !selectedGroup?.items.some((item) => item.capture_id === captureId)) return current;
      const pickCount = selectedGroup.items.reduce((total, item) => total + Number(
        item.capture_id === captureId ? review.user_pick : Boolean(item.user_pick),
      ), 0);
      const rejectCount = selectedGroup.items.reduce((total, item) => total + Number(
        item.capture_id === captureId ? review.user_reject : Boolean(item.user_reject),
      ), 0);
      const status = pickCount
        ? "picked" as const
        : rejectCount >= selectedGroup.items.length ? "skipped" as const : "pending" as const;
      const before = current.items.find((item) => item.id === selectedGroup.id);
      const pendingDelta = before
        ? Number(status === "pending") - Number(before.review_status === "pending")
        : 0;
      return {
        ...current,
        pending_count: current.pending_count + pendingDelta,
        items: current.items.map((item) => item.id === selectedGroup.id
          ? { ...item, pick_count: pickCount, reject_count: rejectCount, review_status: status }
          : item),
      };
    });
    const version = (reviewVersions.current.get(captureId) ?? 0) + 1;
    reviewVersions.current.set(captureId, version);
    const previousRequest = reviewQueues.current.get(captureId) ?? Promise.resolve();
    const request = previousRequest.catch(() => undefined).then(async () => {
      try {
        await getJson(`/api/reviews/${captureId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(review),
        });
        if (reviewVersions.current.get(captureId) === version) {
          pushToast("success", "已保存评价");
          scheduleReviewAggregateRefresh();
        }
      } catch (reason) {
        if (reviewVersions.current.get(captureId) === version) {
          pushToast("error", `保存失败：${(reason as Error).message}`);
          await refreshLibrary();
        }
      }
    });
    reviewQueues.current.set(captureId, request);
    void request.finally(() => {
      if (reviewQueues.current.get(captureId) === request) reviewQueues.current.delete(captureId);
    });
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

  const restoreGroupingRevision = async (revisionId: number, useBefore = false) => {
    setError(null);
    try {
      await getJson(`/api/similarity-group-revisions/${revisionId}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ use_before: useBefore }),
      });
      setSelectedGroup(null);
      await refreshLibrary();
      pushToast("success", useBefore ? "已撤销本次分组调整" : "已恢复所选分组版本");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const editGrouping = async (captureId: number, action: "exclude" | "split_before" | "auto") => {
    setError(null);
    try {
      const result = await getJson<{ revision_id?: number }>(`/api/captures/${captureId}/similarity-override`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      setSelectedGroup(null);
      await refreshLibrary();
      if (result.revision_id) pushToast("success", action === "auto" ? "已恢复自动识别" : "分组已更新", "撤销", () => void restoreGroupingRevision(result.revision_id!, true));
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const saveGrouping = async (groupId: number, groups: number[][], excludedIds: number[]) => {
    setError(null);
    try {
      const result = await getJson<{ revision_id: number; group_ids: number[] }>("/api/similarity-groups/manual", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_group_id: groupId, groups, excluded_ids: excludedIds }),
      });
      setGroupOffset(0);
      await refreshLibrary();
      if (result.group_ids[0]) {
        setSelectedGroup(await getJson<SimilarityGroupDetail>(`/api/similarity-groups/${result.group_ids[0]}`));
      } else {
        setSelectedGroup(null);
      }
      const groupLabel = result.group_ids.length ? `已保存为 ${result.group_ids.length} 个相似组，正在显示第一组` : "照片已作为普通单张移出相似组";
      pushToast("success", groupLabel, "撤销", () => void restoreGroupingRevision(result.revision_id, true));
      return result;
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const openLibraryWith = (changes: Partial<LibraryQuery>) => {
    setLibraryLandingSection("photos");
    setLibraryOffset(0);
    setLibraryCaptures(null);
    setLibraryQuery((current) => ({ ...current, albumId: "", category: "", camera: "", lens: "", rating: "", selection: "", quality: "", dateFrom: "", dateTo: "", search: "", ...changes }));
    setView("library");
  };

  const openCapture = async (captureId: number, context?: number[]) => {
    setError(null);
    try {
      setCaptureDetail(await getJson<CaptureDetail>(`/api/captures/${captureId}`));
      if (context) setDetailContext(context);
      else setDetailContext((current) => current.includes(captureId) ? current : []);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const navigateDetail = async (direction: 1 | -1) => {
    if (!captureDetail || !detailContext.length) return;
    const index = detailContext.indexOf(captureDetail.id);
    if (index < 0) return;
    const nextId = detailContext[index + direction];
    if (nextId == null) return;
    try {
      setCaptureDetail(await getJson<CaptureDetail>(`/api/captures/${nextId}`));
    } catch (reason) {
      pushToast("error", (reason as Error).message);
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

  const checkIntegrity = async (scope: "archive" | "active") => {
    setError(null);
    try {
      const result = await getJson<ArchiveStatus>(`/api/integrity/check/${scope}`, { method: "POST" });
      if (scope === "archive") setArchive(result);
      else setActiveLibraryBaseline(result);
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
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

  const createAlbum = async (name: string, category: string): Promise<number | null> => {
    setError(null);
    try {
      const created = await getJson<{ id: number }>("/api/albums", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, category }),
      });
      setAlbumOffset(0);
      await refreshLibrary();
      return created.id;
    } catch (reason) {
      setError((reason as Error).message);
      return null;
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

  const saveSettings = async (next: EditableSettings) => {
    setError(null);
    try {
      const result = await getJson<SettingsStatus>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next),
      });
      setSettingsStatus(result);
      pushToast("success", "配置已保存，重启应用后生效");
      return result;
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
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

  const pageMeta = {
    home: ["OVERVIEW", "首页概览", ""],
    library: ["LIBRARY", "照片图库", "浏览、整理并管理全部拍摄单元"],
    bursts: ["REVIEW", "连拍选片", "比较连拍与相似画面，留下真正需要的版本"],
    analysis: ["ANALYSIS / REVIEW", "质量分析", "批量运行技术检测与本地模型，在单张详情中复核结果"],
    statistics: ["STATISTICS", "摄影统计", "从器材、参数和选片结果理解拍摄习惯"],
    equipment: ["EQUIPMENT", "设备管理", "器材档案与实际使用统计"],
    lightroom: ["OUTPUT", "后期输出", "检查评分与相册后生成 Lightroom 只读准备清单"],
    archive: ["SYSTEM / MAINTENANCE", "系统维护", "按需检查活动图库与历史存档完整性"],
    settings: ["SETTINGS", "应用设置", "随时调整目录与本地能力；保存不会移动任何照片或数据库"],
  }[view];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">T</span><div><strong>Tangerine</strong><span>Photo Assistant</span></div></div>
        <nav aria-label="主要功能">
          <span className="nav-group-label">照片管理</span>
          <button className={`nav-item ${view === "home" ? "active" : ""}`} onClick={() => setView("home")}><span>首</span>首页概览</button>
          <button className={`nav-item ${view === "library" ? "active" : ""}`} onClick={() => { setLibraryLandingSection("photos"); setView("library"); }}><span>图</span>照片图库</button>
          <button className={`nav-item ${view === "bursts" ? "active" : ""}`} onClick={() => setView("bursts")}><span>选</span>连拍选片</button>
          <span className="nav-group-label system-label">分析学习</span>
          <button className={`nav-item ${view === "analysis" ? "active" : ""}`} onClick={() => setView("analysis")}><span>析</span>质量分析</button>
          <button className={`nav-item ${view === "statistics" ? "active" : ""}`} onClick={() => setView("statistics")}><span>统</span>摄影统计</button>
          <span className="nav-group-label system-label">工具</span>
          <button className={`nav-item ${view === "equipment" ? "active" : ""}`} onClick={() => setView("equipment")}><span>器</span>设备管理</button>
          <button className={`nav-item ${view === "lightroom" ? "active" : ""}`} onClick={() => setView("lightroom")}><span>出</span>后期输出</button>
          <span className="nav-group-label system-label">系统</span>
          <button className={`nav-item ${view === "archive" ? "active" : ""}`} onClick={() => setView("archive")}><span>维</span>系统维护</button>
          <button className={`nav-item ${view === "settings" ? "active" : ""}`} onClick={() => setView("settings")}><span>设</span>应用设置</button>
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
        {view === "home" && <HomeView overview={overview} statistics={statistics} archive={archive} activeBaseline={activeLibraryBaseline} library={libraryCaptures} filters={libraryFilters} task={task} capabilities={capabilities} openPhotos={() => { setLibraryLandingSection("photos"); setView("library"); }} openAlbums={() => { setLibraryLandingSection("albums"); setView("library"); }} openAlbum={(albumId) => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: String(albumId), collapseGroups: true })); setView("library"); }} openBursts={() => setView("bursts")} openStatistics={() => setView("statistics")} continueLabel={({ library: "照片图库", bursts: "相似组选片", analysis: "质量分析", statistics: "摄影统计", equipment: "设备管理", lightroom: "后期输出", archive: "系统维护", settings: "应用设置", home: "首页概览" } as Record<View, string>)[lastWorkspaceView]} continueWork={() => setView(lastWorkspaceView)} openUnassigned={() => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: "__unassigned__", collapseGroups: false })); setView("library"); }} openMaintenance={() => setView("archive")} openCapture={openCapture} />}
        {view === "library" && <LibraryView
          overview={overview} library={libraryCaptures} albums={events} filters={libraryFilters} query={libraryQuery}
          requestedSection={libraryLandingSection}
          updateQuery={(changes) => { setLibraryOffset(0); setLibraryCaptures(null); setLibraryQuery((current) => ({ ...current, ...changes })); }}
          task={task} startScan={startScan} cancelTask={cancelTask} updateAlbum={updateEvent}
          createAlbum={createAlbum} createAlbumType={createAlbumType} renameAlbumType={renameAlbumType} deleteAlbumType={deleteAlbumType} assignToAlbum={assignToAlbum}
          openCapture={openCapture} selectedGroup={selectedGroup} openGroup={openGroup} closeGroup={() => setSelectedGroup(null)} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} restoreGroupingRevision={restoreGroupingRevision} exportPhotos={exportPhoneShare} changePage={setLibraryOffset}
          changePageSize={(limit) => { setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, pageSize: limit })); }}
          changeAlbumPage={setAlbumOffset} changeAlbumPageSize={(limit) => { setAlbumOffset(0); setAlbumPageSize(limit); }}
          openAlbumBursts={(albumId) => { setGroupOffset(0); setGroupReviewFilter("pending"); setGroupAlbumId(String(albumId)); setSelectedGroup(null); setView("bursts"); }}
        />}
        {view === "bursts" && <BurstsView groups={similarityGroups} selectedGroup={selectedGroup} task={task} startVisual={startVisual} openGroup={openGroup} closeGroup={() => setSelectedGroup(null)} openCapture={openCapture} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} restoreGroupingRevision={restoreGroupingRevision} cancelTask={cancelTask} changeGroupPage={setGroupOffset} changeGroupPageSize={(limit) => { setGroupOffset(0); setGroupPageSize(limit); }} reviewFilter={groupReviewFilter} setReviewFilter={(filter) => { setGroupOffset(0); setGroupReviewFilter(filter); }} albumId={groupAlbumId} setAlbumId={(albumId) => { setGroupOffset(0); setSelectedGroup(null); setGroupReviewFilter("pending"); setGroupAlbumId(albumId); }} />}
        {view === "analysis" && <AnalysisView analysis={analysis} preflight={aiPreflight} quality={quality} qualityFilter={qualityFilter} qualitySearch={qualitySearch} setQualityFilter={(filter) => { setQualityOffset(0); setQualityFilter(filter); }} setQualitySearch={(search) => { setQualityOffset(0); setQualitySearch(search); }} task={task} startQuality={startQuality} startDetailBackfill={startDetailBackfill} resumeDetailBackfill={resumeDetailBackfill} startAi={startAi} saveReview={saveReview} cancelTask={cancelTask} pauseTask={pauseTask} resumeAi={resumeAi} retryAiFailures={retryAiFailures} openCapture={openCapture} changeQualityPage={setQualityOffset} changeQualityPageSize={(limit) => { setQualityOffset(0); setQualityPageSize(limit); }} />}
        {view === "statistics" && <StatisticsView statistics={statistics} openLibraryWith={openLibraryWith} />}
        {view === "equipment" && <EquipmentView equipment={equipment} />}
        {view === "archive" && <ArchiveView archive={archive} activeLibrary={activeLibraryBaseline} createBaseline={createBaseline} createActiveBaseline={createActiveBaseline} checkIntegrity={checkIntegrity} />}
        {view === "lightroom" && <LightroomView status={lightroomStatus} manifest={lightroomManifest} capabilities={capabilities} generateManifest={generateManifest} />}
        {view === "settings" && <SettingsView status={settingsStatus} task={task} save={saveSettings} />}
        {captureDetail && (() => { const detailIndex = detailContext.indexOf(captureDetail.id); return <CaptureDetailPanel detail={captureDetail} close={() => setCaptureDetail(null)} saveAiReview={saveAiReview} saveReview={saveReview} navigate={(direction) => void navigateDetail(direction)} hasPrev={detailIndex > 0} hasNext={detailIndex >= 0 && detailIndex < detailContext.length - 1} />; })()}
        <div className="toast-stack" aria-live="polite">
          {toasts.map((toast) => <div key={toast.id} className={`toast ${toast.kind}`}><span>{toast.message}</span>{toast.action && <button onClick={() => { toast.action?.(); setToasts((current) => current.filter((item) => item.id !== toast.id)); }}>{toast.actionLabel}</button>}</div>)}
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
