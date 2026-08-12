import { StrictMode, useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type View = "home" | "library" | "bursts" | "analysis" | "statistics" | "equipment" | "lightroom" | "archive";
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
        <div className="task-actions"><div className="progress-track"><span style={{ width: `${progress ?? 22}%` }} className={progress === null ? "indeterminate" : ""} /></div>{pause && task.pausable && <button onClick={pause}>安全暂停</button>}{cancel && <button onClick={cancel}>安全取消</button>}</div>
      )}
      {task.status === "paused" && cancel && (
        <div className="task-actions"><div className="progress-track"><span style={{ width: `${progress ?? 0}%` }} /></div><button onClick={cancel}>取消剩余任务</button></div>
      )}
    </section>
  );
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

function BurstsView({ groups, selectedGroup, task, startVisual, openGroup, closeGroup, openCapture, saveReview, editGrouping, saveGrouping, cancelTask, changeGroupPage, changeGroupPageSize }: {
  groups: SimilarityGroupsResponse | null;
  selectedGroup: SimilarityGroupDetail | null;
  task: Task | null;
  startVisual: () => void;
  openGroup: (groupId: number) => void;
  closeGroup: () => void;
  openCapture: (captureId: number) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  editGrouping: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  saveGrouping: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<void>;
  cancelTask: () => void;
  changeGroupPage: (offset: number) => void;
  changeGroupPageSize: (limit: number) => void;
}) {
  const [editingGrouping, setEditingGrouping] = useState(false);
  return (
    <>
      <section className="structure-hero burst-hero">
        <div><span className="section-kicker">照片挑选</span><h2>相似照片分组</h2><p>比较连拍和相似画面。</p><button className="primary-action" onClick={startVisual} disabled={task?.status === "running"}><span>{task?.status === "running" ? "分析进行中" : "更新相似分组"}</span><b aria-hidden="true">→</b></button></div>
        <div className="structure-stat"><strong>{groups ? numberFormat.format(groups.count) : "—"}</strong><span>组待比较照片</span></div>
      </section>
      <TaskCard task={task} cancel={cancelTask} />
      {selectedGroup ? (
        <section className="panel comparison-panel">
          <div className="panel-heading">
            <div><span className="section-kicker">组内对比</span><h3>{selectedGroup.event_name}</h3></div>
            <div className="panel-heading-actions"><button className="toolbar-button" onClick={() => setEditingGrouping(true)}>调整分组</button><button className="secondary-action compact" onClick={closeGroup}>返回相似组</button></div>
          </div>
          {editingGrouping ? <SimilarityGroupingEditor group={selectedGroup} cancel={() => setEditingGrouping(false)} save={saveGrouping} restore={(captureId) => editGrouping(captureId, "auto")} /> : <>
          <div className="comparison-note">共 {selectedGroup.capture_count} 张 · 按拍摄顺序排列 · 点击图片查看完整参数</div>
          <div className="comparison-grid">
            {selectedGroup.items.map((item) => (
              <article className={`comparison-card ${item.auto_pick ? "auto-pick" : ""} ${item.user_pick ? "user-pick" : ""} ${item.user_reject ? "user-reject" : ""}`} key={item.capture_id} onClick={() => openCapture(item.capture_id)}>
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

function SimilarityGroupingEditor({ group, cancel, save, restore }: {
  group: SimilarityGroupDetail;
  cancel: () => void;
  save: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<void>;
  restore: (captureId: number) => Promise<void>;
}) {
  const [buckets, setBuckets] = useState<number[][]>([group.items.map((item) => item.capture_id), []]);
  const [excluded, setExcluded] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);
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
  return <div className="grouping-editor">
    <div className="grouping-editor-note"><span>拖动照片到不同分组。放入“移出分组”的照片会作为普通单张显示。</span>{hasManualGrouping && restoreCaptureId && <button onClick={() => void restore(restoreCaptureId)}>恢复自动识别</button>}</div>
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
    <footer className="grouping-editor-footer"><button className="toolbar-button" onClick={() => setBuckets((current) => [...current, []])}>＋ 新增分组</button><span>所有调整只在点击确认后生效</span><button className="toolbar-button" onClick={cancel}>取消</button><button className="toolbar-button primary" disabled={saving} onClick={() => void submit()}>{saving ? "正在保存" : "确认调整"}</button></footer>
  </div>;
}

function SimilarityPickerModal({ group, close, openCapture, saveReview, editGrouping, saveGrouping }: {
  group: SimilarityGroupDetail;
  close: () => void;
  openCapture: (captureId: number) => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  editGrouping: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  saveGrouping: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  return <ModalShell title={`${group.event_name} · 相似照片`} close={close} wide>
    {editing ? <SimilarityGroupingEditor group={group} cancel={() => setEditing(false)} save={saveGrouping} restore={(captureId) => editGrouping(captureId, "auto")} /> : <>
    <div className="similarity-picker-summary"><span>共 {group.capture_count} 张，按拍摄顺序排列</span><button className="toolbar-button" onClick={() => setEditing(true)}>调整分组</button></div>
    <div className="similarity-picker-grid">{group.items.map((item) => <article className={`${item.auto_pick ? "auto-pick" : ""} ${item.user_pick ? "user-pick" : ""} ${item.user_reject ? "user-reject" : ""}`} key={item.capture_id}>
      <button className="similarity-picker-photo" onClick={() => openCapture(item.capture_id)}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} />{item.auto_pick && <span>技术推荐</span>}</button>
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
  openCapture: (captureId: number) => void;
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
  return <>
    <section className="library-filters">
      <label className="search-filter"><span>搜索</span><input value={query.search} onChange={(event) => updateQuery({ search: event.target.value })} placeholder="文件名、相册或目录" /></label>
      {!albumContext && <label><span>相册</span><select value={query.albumId} onChange={(event) => updateQuery({ albumId: event.target.value })}><option value="">全部相册</option><option value="__unassigned__">未归入相册</option>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select></label>}
      {!albumContext && <label><span>类型</span><select value={query.category} onChange={(event) => updateQuery({ category: event.target.value })}><option value="">全部类型</option>{(filters?.album_types ?? []).map((type) => <option key={type.name}>{type.name}</option>)}</select></label>}
      <label><span>相机</span><select value={query.camera} onChange={(event) => updateQuery({ camera: event.target.value })}><option value="">全部相机</option>{(filters?.cameras ?? []).map((camera) => <option key={camera}>{camera}</option>)}</select></label>
      <label><span>镜头</span><select value={query.lens} onChange={(event) => updateQuery({ lens: event.target.value })}><option value="">全部镜头</option>{(filters?.lenses ?? []).map((lens) => <option key={lens}>{lens}</option>)}</select></label>
      <label><span>人工星级</span><select value={query.rating} onChange={(event) => updateQuery({ rating: event.target.value })}><option value="">全部星级</option>{[5, 4, 3, 2, 1].map((rating) => <option key={rating} value={rating}>{rating} 星</option>)}</select></label>
      <label><span>开始日期</span><input type="date" value={query.dateFrom} onChange={(event) => updateQuery({ dateFrom: event.target.value })} /></label>
      <label><span>结束日期</span><input type="date" value={query.dateTo} onChange={(event) => updateQuery({ dateTo: event.target.value })} /></label>
      <label><span>排序</span><select value={query.sort} onChange={(event) => updateQuery({ sort: event.target.value })}><option value="newest">最新拍摄</option><option value="oldest">最早拍摄</option><option value="name">文件名称</option><option value="rating">人工星级</option></select></label>
      <button className="toolbar-button filter-reset" onClick={() => updateQuery({ albumId: albumContext ? query.albumId : "", category: "", camera: "", lens: "", rating: "", selection: "", dateFrom: "", dateTo: "", search: "", sort: "newest" })}>清除筛选</button>
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
        <button className="photo-open" onClick={() => isGroup && openGroup ? openGroup(item.similarity_group_id!) : openCapture(item.id)}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} />{isGroup && <span className="group-stack-badge">{item.similarity_group_size} 张</span>}</button>
        <div className="photo-card-copy"><div><strong>{isGroup ? `连拍 · ${item.stem}` : item.stem}</strong><span>{item.captured_at?.slice(0, 10) ?? "日期未知"}</span></div><p>{isGroup ? `${item.similarity_group_size} 张 · ${formatBytes(item.size_bytes)} · ${item.group_pick_count ?? 0} 张入选` : `${formatBytes(item.size_bytes)} · ${item.album_name ?? "尚未归入相册"}`}</p><div className="photo-card-status"><span>{item.user_rating ? `${item.user_rating} 星` : "未评分"}</span><div>{item.grouping_override === "exclude" && <>{editGrouping && <button className="similarity-inline" onClick={() => void editGrouping(item.id, "auto")}>恢复自动分组</button>}<b>已移出连拍</b></>}{!isGroup && item.similarity_group_id && openGroup ? <button className="similarity-inline" onClick={() => openGroup(item.similarity_group_id!)}>连拍组 · {item.similarity_group_size} 张</button> : null}{item.similarity_group_id && (item.user_pick ? <b>组内入选</b> : item.user_reject ? <b className="rejected">组内排除</b> : null)}</div></div></div>
      </article>})}
      {!items.length && <div className="empty-state">图库中还没有可查看的 JPEG 照片。</div>}
    </section>
    {library && <Pagination count={library.count} limit={library.limit} offset={library.offset} onChange={changePage} onLimitChange={changePageSize} />}
  </>;
}

function LibraryView({ overview, library, albums, filters, query, updateQuery, requestedSection, task, startScan, cancelTask, updateAlbum, createAlbum, createAlbumType, renameAlbumType, deleteAlbumType, assignToAlbum, openCapture, selectedGroup, openGroup, closeGroup, saveReview, editGrouping, saveGrouping, exportPhotos, changePage, changePageSize, changeAlbumPage, changeAlbumPageSize }: {
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
  openCapture: (captureId: number) => void;
  selectedGroup: SimilarityGroupDetail | null;
  openGroup: (groupId: number) => void;
  closeGroup: () => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  editGrouping: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  saveGrouping: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<void>;
  exportPhotos: (captureIds: number[], maxEdge: number) => Promise<PhoneShareExport>;
  changePage: (offset: number) => void;
  changePageSize: (limit: number) => void;
  changeAlbumPage: (offset: number) => void;
  changeAlbumPageSize: (limit: number) => void;
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
      <TaskCard task={task} cancel={cancelTask} />
      {activeAlbumId ? <>
        <section className="album-detail-header"><button className="album-back" onClick={leaveAlbum}>← 返回相册</button><div><span>{activeAlbum?.category ?? "相册"}</span><h2>{activeAlbum?.name ?? "相册照片"}</h2><small>{numberFormat.format(activeAlbum?.capture_count ?? library?.count ?? 0)} 张照片</small></div><button className="toolbar-button" onClick={openUpdate} disabled={task?.status === "running"}>更新图库</button></section>
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
      {selectedGroup && <SimilarityPickerModal group={selectedGroup} close={closeGroup} openCapture={openCapture} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} />}
    </>
  );
}

function HomeView({ overview, statistics, archive, activeBaseline, library, task, openPhotos, openAlbums, openUnassigned, openMaintenance, openCapture }: {
  overview: Overview | null;
  statistics: Statistics | null;
  archive: ArchiveStatus | null;
  activeBaseline: ArchiveStatus | null;
  library: LibraryCapturesResponse | null;
  task: Task | null;
  openPhotos: () => void;
  openAlbums: () => void;
  openUnassigned: () => void;
  openMaintenance: () => void;
  openCapture: (captureId: number) => void;
}) {
  const pendingEvents = overview?.structure.unconfirmed_event_count ?? 0;
  const unassigned = overview?.structure.unassigned_capture_count ?? 0;
  const archiveIssue = archive?.comparison && !archive.comparison.healthy;
  const activeIssue = activeBaseline?.comparison && !activeBaseline.comparison.healthy;
  const monthRows = statistics?.months ?? [];
  const latestMonth = monthRows[monthRows.length - 1] ?? null;
  const hasPending = pendingEvents > 0 || unassigned > 0 || Boolean(archiveIssue) || Boolean(activeIssue);
  return <>
    <section className="home-metrics">
      <article><span>全部照片</span><strong>{overview ? numberFormat.format(overview.capture_total) : "—"}</strong><small>{overview ? formatBytes(overview.files.size_bytes) : ""}</small></article>
      <article><span>拍摄相册</span><strong>{overview?.structure.event_count ?? "—"}</strong><small>{pendingEvents} 个名称待确认</small></article>
      <article><span>最近拍摄月</span><strong>{latestMonth ? numberFormat.format(latestMonth.count) : "—"}</strong><small>{latestMonth?.month ?? "暂无拍摄日期"}</small></article>
    </section>
    <section className="home-management-grid">
      <section className="panel recent-photos-panel"><div className="panel-heading"><div><h3>最近照片</h3></div><button className="text-action" onClick={openPhotos}>查看全部</button></div><div className="recent-photo-grid">
        {(library?.items ?? []).slice(0, 8).map((item) => <button key={item.id} onClick={() => openCapture(item.id)}><img src={item.thumbnail_url} alt={item.stem} /><span>{item.stem}</span></button>)}
      </div></section>
      <section className="panel pending-panel"><div className="panel-heading"><div><h3>待处理</h3></div></div><div className="pending-list">
        {pendingEvents > 0 && <button onClick={openAlbums}><span><strong>{pendingEvents}</strong> 个相册名称待确认</span><b>整理相册</b></button>}
        {unassigned > 0 && <button onClick={openUnassigned}><span><strong>{unassigned}</strong> 张照片尚未归入相册</span><b>查看照片</b></button>}
        {archiveIssue && <button onClick={openMaintenance}><span>历史原片完整性检查存在异常</span><b>查看状态</b></button>}
        {activeIssue && <button onClick={openMaintenance}><span>活动图库完整性检查存在异常</span><b>查看状态</b></button>}
        {!hasPending && <div className="empty-state">当前没有需要及时处理的项目。</div>}
      </div></section>
    </section>
    {task && task.status !== "idle" && <section className="home-current-task"><TaskCard task={task} /></section>}
  </>;
}

function AnalysisView({ analysis, preflight, quality, qualityFilter, qualitySearch, setQualityFilter, setQualitySearch, task, startQuality, startAi, saveReview, cancelTask, pauseAi, resumeAi, retryAiFailures, openCapture, changeQualityPage, changeQualityPageSize }: {
  analysis: AnalysisOverview | null;
  preflight: AiPreflight | null;
  quality: QualityResponse | null;
  qualityFilter: QualityReviewFilter;
  qualitySearch: string;
  setQualityFilter: (filter: QualityReviewFilter) => void;
  setQualitySearch: (search: string) => void;
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
          <div className="analysis-command-panel">
            <div className="analysis-command-group"><span>技术检测</span><button className="toolbar-button primary" onClick={startQuality} disabled={running}>分析新增照片</button></div>
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
      <section className="panel quality-review-panel">
        <div className="panel-heading"><div><span className="section-kicker">照片复核</span><h3>问题与改进建议</h3></div><span className="batch-count">点击照片查看完整分析</span></div>
        <div className="quality-review-toolbar">
          <input value={qualitySearch} onChange={(event) => setQualitySearch(event.target.value)} placeholder="搜索照片或相册" />
          <select value={qualityFilter} onChange={(event) => setQualityFilter(event.target.value as QualityReviewFilter)}><option value="all">全部已分析</option><option value="problems">发现问题</option><option value="low_score">技术分低于 70</option><option value="with_model">已有模型建议</option><option value="without_model">等待模型建议</option><option value="unrated">尚未评分</option></select>
        </div>
        <div className="quality-review-grid">
          {(quality?.items ?? []).map((item) => (
            <article className="quality-review-card" key={item.capture_id}>
              <button className="quality-review-photo" onClick={() => openCapture(item.capture_id)}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} /><span>{Math.round(item.technical_score)} 分 · {technicalGrade(item.technical_score)}</span></button>
              <div className="quality-review-copy"><div><strong>{item.stem}</strong><small>{item.event_name} · {item.category}{item.auto_pick ? " · 组内推荐" : ""}</small></div><p>{item.ai_result?.quality_summary ?? (item.issues[0]?.message || "未发现明确技术问题")}</p><div className="quality-advice"><b>{item.ai_result ? "模型建议" : "技术建议"}</b><span>{item.ai_result ? modelAdvice(item.ai_result) : (item.issues[0] ? technicalAdvice(item.issues[0].code) : "当前技术指标正常，可结合构图和表达继续人工判断。")}</span></div></div>
              <div className="review-controls"><button onClick={() => openCapture(item.capture_id)}>查看详情</button>
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
        <article><span>连拍入选</span><strong>{summary ? numberFormat.format(summary.user_picks) : "—"}</strong><small>组内最终选择</small></article>
        <article><span>连拍排除</span><strong>{summary ? numberFormat.format(summary.user_rejects) : "—"}</strong><small>不会删除原片</small></article>
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
        <article><span>连拍入选</span><strong>{status ? numberFormat.format(status.user_picks) : "—"}</strong><small>准备清单中的pick字段</small></article>
        <article><span>连拍排除</span><strong>{status ? numberFormat.format(status.user_rejects) : "—"}</strong><small>只标记，不删除</small></article>
      </section>
      <section className="lightroom-grid">
        <section className="panel safety-panel"><div className="panel-heading"><div><span className="section-kicker">安全状态</span><h3>本轮只生成报告</h3></div></div><div className="safety-list"><div><b>✓</b><span><strong>历史原片不变</strong><small>D:\Photo继续只读保留，不移动、不改名、不改写</small></span></div><div><b>✓</b><span><strong>XMP写入关闭</strong><small>不会在原片旁创建或修改附属文件</small></span></div><div><b>✓</b><span><strong>使用活动图库</strong><small>Lightroom准备清单指向D:\PhotoLibrary\Photos</small></span></div><div><b>✓</b><span><strong>JPG与RAW同步</strong><small>同一拍摄单元共享评级和标签</small></span></div></div></section>
        <section className="panel manifest-panel"><div className="panel-heading"><div><span className="section-kicker">最近生成</span><h3>Lightroom准备文件</h3></div></div>{manifest ? <div className="manifest-result"><strong>{numberFormat.format(manifest.capture_count)} 个拍摄单元</strong><span>{numberFormat.format(manifest.rated_count)} 个已有评级 · {formatBytes(manifest.source_bytes)} 原始文件索引</span><a href={manifest.csv_url}>下载CSV清单</a><a href={manifest.json_url}>下载完整JSON</a><small>下载的是清单，不是照片副本。</small></div> : <div className="empty-state">尚未在本次启动中生成清单。</div>}</section>
      </section>
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
  const [libraryLandingSection, setLibraryLandingSection] = useState<LibrarySection>("photos");
  const [libraryOffset, setLibraryOffset] = useState(0);
  const [libraryQuery, setLibraryQuery] = useState<LibraryQuery>({
    pageSize: 40, albumId: "", category: "", camera: "", lens: "",
    rating: "", selection: "", dateFrom: "", dateTo: "", search: "", sort: "newest", collapseGroups: false,
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
  const [selectedGroup, setSelectedGroup] = useState<SimilarityGroupDetail | null>(null);
  const [captureDetail, setCaptureDetail] = useState<CaptureDetail | null>(null);
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [equipment, setEquipment] = useState<EquipmentCatalog | null>(null);
  const [archive, setArchive] = useState<ArchiveStatus | null>(null);
  const [activeLibraryBaseline, setActiveLibraryBaseline] = useState<ArchiveStatus | null>(null);
  const [lightroomStatus, setLightroomStatus] = useState<LightroomStatus | null>(null);
  const [lightroomManifest, setLightroomManifest] = useState<LightroomManifest | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refreshSequence = useRef(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("tangerine-theme", theme);
  }, [theme]);

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
    if (libraryQuery.dateFrom) libraryParameters.set("date_from", libraryQuery.dateFrom);
    if (libraryQuery.dateTo) libraryParameters.set("date_to", libraryQuery.dateTo);
    if (libraryQuery.search.trim()) libraryParameters.set("search", libraryQuery.search.trim());
    if (libraryQuery.albumId && libraryQuery.collapseGroups) libraryParameters.set("collapse_groups", "true");
    const [overviewData, libraryData, filterData, eventData, analysisData, preflightData, qualityData, groupData, statisticsData, equipmentData, archiveData, activeBaselineData, lightroomData] = await Promise.all([
      getJson<Overview>("/api/overview"),
      getJson<LibraryCapturesResponse>(`/api/library/captures?${libraryParameters.toString()}`),
      getJson<LibraryFilters>("/api/library/filters"),
      getJson<EventsResponse>(`/api/albums?limit=${albumPageSize}&offset=${albumOffset}`),
      getJson<AnalysisOverview>("/api/analysis/overview"),
      getJson<AiPreflight>("/api/ai/preflight"),
      getJson<QualityResponse>(`/api/quality?${new URLSearchParams({ limit: String(qualityPageSize), offset: String(qualityOffset), review_filter: qualityFilter, ...(qualitySearch.trim() ? { search: qualitySearch.trim() } : {}) }).toString()}`),
      getJson<SimilarityGroupsResponse>(`/api/similarity-groups?limit=${groupPageSize}&offset=${groupOffset}`),
      getJson<Statistics>("/api/statistics"),
      getJson<EquipmentCatalog>("/api/equipment"),
      getJson<ArchiveStatus>("/api/archive/status"),
      getJson<ArchiveStatus>("/api/active-library/baseline/status"),
      getJson<LightroomStatus>("/api/lightroom/status"),
    ]);
    if (requestSequence !== refreshSequence.current) return;
    setOverview(overviewData);
    setLibraryCaptures(libraryData);
    setLibraryFilters(filterData);
    setEvents(eventData);
    setAnalysis(analysisData);
    setAiPreflight(preflightData);
    setQuality(qualityData);
    setSimilarityGroups(groupData);
    setStatistics(statisticsData);
    setEquipment(equipmentData);
    setArchive(archiveData);
    setActiveLibraryBaseline(activeBaselineData);
    setLightroomStatus(lightroomData);
  }, [albumOffset, albumPageSize, groupOffset, groupPageSize, libraryOffset, libraryQuery, qualityFilter, qualityOffset, qualityPageSize, qualitySearch]);

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
      await refreshLibrary();
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

  const editGrouping = async (captureId: number, action: "exclude" | "split_before" | "auto") => {
    setError(null);
    try {
      await getJson(`/api/captures/${captureId}/similarity-override`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      setSelectedGroup(null);
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const saveGrouping = async (groupId: number, groups: number[][], excludedIds: number[]) => {
    setError(null);
    try {
      await getJson("/api/similarity-groups/manual", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_group_id: groupId, groups, excluded_ids: excludedIds }),
      });
      setSelectedGroup(null);
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
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
        {view === "home" && <HomeView overview={overview} statistics={statistics} archive={archive} activeBaseline={activeLibraryBaseline} library={libraryCaptures} task={task} openPhotos={() => { setLibraryLandingSection("photos"); setView("library"); }} openAlbums={() => { setLibraryLandingSection("albums"); setView("library"); }} openUnassigned={() => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: "__unassigned__", collapseGroups: false })); setView("library"); }} openMaintenance={() => setView("archive")} openCapture={openCapture} />}
        {view === "library" && <LibraryView
          overview={overview} library={libraryCaptures} albums={events} filters={libraryFilters} query={libraryQuery}
          requestedSection={libraryLandingSection}
          updateQuery={(changes) => { setLibraryOffset(0); setLibraryCaptures(null); setLibraryQuery((current) => ({ ...current, ...changes })); }}
          task={task} startScan={startScan} cancelTask={cancelTask} updateAlbum={updateEvent}
          createAlbum={createAlbum} createAlbumType={createAlbumType} renameAlbumType={renameAlbumType} deleteAlbumType={deleteAlbumType} assignToAlbum={assignToAlbum}
          openCapture={openCapture} selectedGroup={selectedGroup} openGroup={openGroup} closeGroup={() => setSelectedGroup(null)} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} exportPhotos={exportPhoneShare} changePage={setLibraryOffset}
          changePageSize={(limit) => { setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, pageSize: limit })); }}
          changeAlbumPage={setAlbumOffset} changeAlbumPageSize={(limit) => { setAlbumOffset(0); setAlbumPageSize(limit); }}
        />}
        {view === "bursts" && <BurstsView groups={similarityGroups} selectedGroup={selectedGroup} task={task} startVisual={startVisual} openGroup={openGroup} closeGroup={() => setSelectedGroup(null)} openCapture={openCapture} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} cancelTask={cancelTask} changeGroupPage={setGroupOffset} changeGroupPageSize={(limit) => { setGroupOffset(0); setGroupPageSize(limit); }} />}
        {view === "analysis" && <AnalysisView analysis={analysis} preflight={aiPreflight} quality={quality} qualityFilter={qualityFilter} qualitySearch={qualitySearch} setQualityFilter={(filter) => { setQualityOffset(0); setQualityFilter(filter); }} setQualitySearch={(search) => { setQualityOffset(0); setQualitySearch(search); }} task={task} startQuality={startQuality} startAi={startAi} saveReview={saveReview} cancelTask={cancelTask} pauseAi={pauseAi} resumeAi={resumeAi} retryAiFailures={retryAiFailures} openCapture={openCapture} changeQualityPage={setQualityOffset} changeQualityPageSize={(limit) => { setQualityOffset(0); setQualityPageSize(limit); }} />}
        {view === "statistics" && <StatisticsView statistics={statistics} />}
        {view === "equipment" && <EquipmentView equipment={equipment} />}
        {view === "archive" && <ArchiveView archive={archive} activeLibrary={activeLibraryBaseline} createBaseline={createBaseline} createActiveBaseline={createActiveBaseline} checkIntegrity={checkIntegrity} />}
        {view === "lightroom" && <LightroomView status={lightroomStatus} manifest={lightroomManifest} generateManifest={generateManifest} />}
        {captureDetail && <CaptureDetailPanel detail={captureDetail} close={() => setCaptureDetail(null)} saveAiReview={saveAiReview} />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
