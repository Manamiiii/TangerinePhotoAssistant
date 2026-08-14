import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { getJson, similarityGroupsUrl } from "./api";
import { AlbumWorkspaceHeader, CollectionScopeTabs, Pagination } from "./components/Navigation";
import { TaskCard, taskForDisplay, taskReceipt, type Task } from "./components/TaskCard";
import { ModalShell } from "./components/ModalShell";
import { ArchiveView, type ArchiveStatus } from "./features/system/ArchiveView";
import { LightroomView, type LightroomManifest, type LightroomManifestScope, type LightroomStatus } from "./features/system/LightroomView";
import type { EditableSettings, SettingsStatus, SystemCapabilities } from "./features/system/types";
import { SettingsView } from "./features/system/SettingsView";
import { EquipmentView } from "./features/equipment/EquipmentView";
import type { EquipmentCatalog, EquipmentDraft, EquipmentItem, EquipmentKind } from "./features/equipment/types";
import { StatisticsView, type Statistics } from "./features/statistics/StatisticsView";
import { AnalysisView } from "./features/analysis/AnalysisView";
import type { AiPreflight, AnalysisOverview, QualityItem, QualityResponse, QualityReviewFilter, ReviewPayload } from "./features/analysis/types";
import type { GroupCapture, SimilarityGroupDetail, SimilarityGroupsResponse, SimilarityReviewFilter } from "./features/similarity/types";
import { BurstsView, SimilarityGroupingEditor } from "./features/similarity/BurstsView";
import type { CaptureDetail } from "./features/details/types";
import { CaptureDetailPanel } from "./features/details/CaptureDetailPanel";
import {
  formatBytes,
  formatDate,
  numberFormat,
} from "./formatters";
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



type PhotoInboxStatus = { path: string; exists: boolean; can_open: boolean };
type Toast = { id: number; kind: "success" | "error"; message: string; actionLabel?: string; action?: () => void };
function taskBelongsTo(task: Task | null, area: "library" | "visual" | "analysis") {
  if (!task || task.status === "idle") return false;
  const stage = task.stage.toLocaleLowerCase();
  const message = task.message;
  if (area === "visual") return ["duplicates", "fingerprints"].includes(stage) || /视觉预筛|相似分组|画面指纹|精确重复/.test(message);
  if (area === "analysis") return stage === "quality" || stage.startsWith("detail-") || stage.startsWith("ai-") || /技术质量|详情数据|扩展拍摄信息|直方图|模型任务|本地模型|Qwen/.test(message);
  return ["indexing", "metadata", "pairing", "structure"].includes(stage) || /图库更新|核对文件|扫描|相册/.test(message);
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
  const [selectionGroup, setSelectionGroup] = useState<SimilarityGroupDetail | null>(null);
  const [selectionGroupDraft, setSelectionGroupDraft] = useState<Set<number>>(new Set());
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
  const openGroupSelection = async (groupId: number) => {
    const group = await getJson<SimilarityGroupDetail>(`/api/similarity-groups/${groupId}`);
    setSelectionGroup(group);
    setSelectionGroupDraft(new Set(group.items.filter((item) => selected.has(item.capture_id)).map((item) => item.capture_id)));
  };
  const applyGroupSelection = () => {
    if (!selectionGroup) return;
    const memberIds = new Set(selectionGroup.items.map((item) => item.capture_id));
    setSelected((current) => new Set([...current].filter((id) => !memberIds.has(id)).concat([...selectionGroupDraft])));
    setSelectionGroup(null);
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
      <div className="photo-view-actions">{albumContext && <div className="burst-view-toggle"><button className={query.collapseGroups ? "active" : ""} onClick={() => updateQuery({ collapseGroups: true })}>折叠连拍</button><button className={!query.collapseGroups ? "active" : ""} onClick={() => updateQuery({ collapseGroups: false })}>展开全部</button></div>}<button className={`toolbar-button selection-entry ${selectionMode ? "active" : ""}`} onClick={() => selectionMode ? leaveSelectionMode() : setSelectionMode(true)}>{selectionMode ? "完成选择" : "选择照片"}</button></div>
    </section>
    <section className={`selection-toolbar ${selectionMode ? "visible" : ""}`}>
      <div><strong>本次选择 {selected.size} 张</strong><button onClick={() => setSelected(allSelected ? new Set([...selected].filter((id) => !pageCaptureIds.includes(id))) : new Set([...selected, ...pageCaptureIds]))}>{allSelected ? "取消本页" : "选择本页"}</button><button onClick={() => setSelected(new Set())}>清空</button><button onClick={leaveSelectionMode}>完成</button></div>
      <div className="selection-actions"><label>归入相册<select value={targetAlbum} onChange={(event) => setTargetAlbum(event.target.value)}><option value="">选择相册</option>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select></label><button disabled={!targetAlbum} onClick={async () => { await assignToAlbum(Number(targetAlbum), Array.from(selected)); setSelected(new Set()); }}>应用</button><label>分享尺寸<select value={maxEdge} onChange={(event) => setMaxEdge(Number(event.target.value))}><option value={1080}>1080px</option><option value={2048}>2048px</option><option value={3840}>3840px</option></select></label><button className="primary-action" disabled={!selected.size || exporting} onClick={exportSelected}><span>{exporting ? "正在生成" : "导出分享包"}</span><b>↓</b></button></div>
    </section>
    {latestExport && <div className="export-success"><span>已生成 {latestExport.photo_count} 张照片 · {formatBytes(latestExport.size_bytes)} · EXIF 已移除</span><a href={latestExport.download_url} download={latestExport.filename}>再次下载</a></div>}
    <section className={`photo-library-grid layout-${layout} ${selectionMode ? "selecting" : ""}`}>
      {items.map((item) => {
        const itemSelected = item.selection_capture_ids.every((captureId) => selected.has(captureId));
        const isGroup = item.item_type === "group" && item.similarity_group_id != null;
        return <article className={`library-photo-card ${itemSelected ? "selected" : ""} ${isGroup ? "group-card" : ""}`} key={isGroup ? `group-${item.similarity_group_id}` : `photo-${item.id}`}>
        {selectionMode && <button className="photo-select" aria-label={`${isGroup ? "选择组内照片" : itemSelected ? "取消选择" : "选择"} ${item.stem}`} onClick={() => isGroup ? void openGroupSelection(item.similarity_group_id!) : toggle(item.selection_capture_ids)}><span>{itemSelected ? "✓" : isGroup ? "…" : ""}</span></button>}
        <button className="photo-open" onClick={() => isGroup && selectionMode ? void openGroupSelection(item.similarity_group_id!) : isGroup && openGroup ? openGroup(item.similarity_group_id!) : openCapture(item.id, items.filter((entry) => entry.item_type === "photo").map((entry) => entry.id))}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} />{isGroup && <span className="group-stack-badge">{item.similarity_group_size} 张{selectionMode ? " · 选择组内" : ""}</span>}</button>
        <div className="photo-card-copy"><div><strong>{isGroup ? `连拍 · ${item.stem}` : item.stem}</strong><span>{item.captured_at?.slice(0, 10) ?? "日期未知"}</span></div><p>{isGroup ? `${item.similarity_group_size} 张 · ${formatBytes(item.size_bytes)} · ${item.group_pick_count ?? 0} 张入选` : `${formatBytes(item.size_bytes)} · ${item.album_name ?? "尚未归入相册"}`}</p><div className="photo-card-status"><span>{item.user_rating ? `${item.user_rating} 星` : "未评分"}</span><div>{item.grouping_override === "exclude" && <>{editGrouping && <button className="similarity-inline" onClick={() => void editGrouping(item.id, "auto")}>恢复自动分组</button>}<b>已移出连拍</b></>}{!isGroup && item.similarity_group_id && openGroup ? <button className="similarity-inline" onClick={() => openGroup(item.similarity_group_id!)}>连拍组 · {item.similarity_group_size} 张</button> : null}{item.similarity_group_id && (item.user_pick ? <b>组内入选</b> : item.user_reject ? <b className="rejected">组内排除</b> : null)}</div></div></div>
      </article>})}
      {!items.length && <div className="empty-state">图库中还没有可查看的 JPEG 照片。</div>}
    </section>
    {library && <Pagination count={library.count} limit={library.limit} offset={library.offset} onChange={changePage} onLimitChange={changePageSize} />}
    {selectionGroup && <ModalShell title={`选择组内照片 · ${selectionGroup.capture_count} 张`} close={() => setSelectionGroup(null)} wide>
      <div className="group-export-tools"><span>这只是本次归类或导出的临时选择，不会改变正式入选结果。</span><div><button onClick={() => setSelectionGroupDraft(new Set(selectionGroup.items.filter((item) => item.user_pick).map((item) => item.capture_id)))}>人工入选</button><button onClick={() => setSelectionGroupDraft(new Set(selectionGroup.items.filter((item) => item.auto_pick).map((item) => item.capture_id)))}>技术推荐</button><button onClick={() => setSelectionGroupDraft(new Set(selectionGroup.items.map((item) => item.capture_id)))}>全选</button><button onClick={() => setSelectionGroupDraft(new Set())}>清空</button></div></div>
      <div className="group-export-grid">{selectionGroup.items.map((item) => <button key={item.capture_id} className={selectionGroupDraft.has(item.capture_id) ? "selected" : ""} onClick={() => setSelectionGroupDraft((current) => { const next = new Set(current); next.has(item.capture_id) ? next.delete(item.capture_id) : next.add(item.capture_id); return next; })}><img src={item.thumbnail_url} alt={item.stem} /><span>{selectionGroupDraft.has(item.capture_id) ? "✓ " : ""}{item.stem}{item.user_pick ? " · 已入选" : item.auto_pick ? " · 技术推荐" : ""}</span></button>)}</div>
      <footer className="editor-footer"><span>已选择 {selectionGroupDraft.size} 张</span><button onClick={() => setSelectionGroup(null)}>取消</button><button className="primary" onClick={applyGroupSelection}>确认选择</button></footer>
    </ModalShell>}
  </>;
}

function LibraryView({ overview, library, albums, filters, query, updateQuery, requestedSection, task, startScan, cancelTask, updateAlbum, createAlbum, createAlbumType, renameAlbumType, deleteAlbumType, assignToAlbum, openCapture, selectedGroup, openGroup, closeGroup, saveReview, editGrouping, saveGrouping, restoreGroupingRevision, exportPhotos, changePage, changePageSize, changeAlbumPage, changeAlbumPageSize, openAlbumBursts, openAlbumQuality }: {
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
  openAlbumQuality: (albumId: number) => void;
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
  useEffect(() => {
    if (query.albumId && query.albumId !== "__unassigned__") {
      setActiveAlbumId(Number(query.albumId));
    }
  }, [query.albumId]);
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
      {!activeAlbumId && <div className="library-navigation workspace-view-nav"><CollectionScopeTabs scope={section === "photos" ? "all" : "albums"} setScope={(scope) => setSection(scope === "all" ? "photos" : "albums")} /><div className="library-maintenance"><span>上次更新 {formatDate(overview?.latest_scan?.finished_at)}</span><button className="toolbar-button primary" onClick={openUpdate} disabled={task?.status === "running"}>{task?.status === "running" ? "正在更新" : "更新图库"}</button></div></div>}
      <TaskCard task={taskBelongsTo(task, "library") ? task : null} cancel={cancelTask} />
      {activeAlbumId ? <>
        <AlbumWorkspaceHeader name={activeAlbum?.name ?? "相册照片"} category={activeAlbum?.category ?? "相册"} summary={`${numberFormat.format(activeAlbum?.capture_count ?? library?.count ?? 0)} 张照片`} current="library" back={leaveAlbum} openPhotos={() => undefined} openBursts={() => openAlbumBursts(activeAlbumId)} openQuality={() => openAlbumQuality(activeAlbumId)} />
        <div className="album-context-actions"><button className="toolbar-button" onClick={openUpdate} disabled={task?.status === "running"}>更新图库</button></div>
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

function HomeView({ overview, statistics, archive, activeBaseline, library, filters, similarity, task, capabilities, openPhotos, openAlbums, openAlbum, openBursts, openStatistics, continueLabel, continueWork, openUnassigned, openMaintenance, openCapture }: {
  overview: Overview | null;
  statistics: Statistics | null;
  archive: ArchiveStatus | null;
  activeBaseline: ArchiveStatus | null;
  library: LibraryCapturesResponse | null;
  filters: LibraryFilters | null;
  similarity: SimilarityGroupsResponse | null;
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
  const pendingSimilarity = similarity?.pending_count ?? 0;
  const monthRows = statistics?.months ?? [];
  const latestMonth = monthRows[monthRows.length - 1] ?? null;
  const hasPending = pendingEvents > 0 || unassigned > 0 || pendingSimilarity > 0 || Boolean(archiveIssue) || Boolean(activeIssue);
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
      <section className="home-continue-card"><span className="section-kicker">继续上次工作</span><h3>{continueLabel}</h3><button className="primary-action" onClick={continueWork}><span>继续浏览</span><b>→</b></button><div><button onClick={openPhotos}>照片图库</button><button onClick={openBursts}>相似组选片</button><button onClick={openStatistics}>摄影统计</button></div></section>
      <section className="panel home-albums-panel"><div className="panel-heading"><div><h3>最近相册</h3></div><button className="text-action" onClick={openAlbums}>管理全部</button></div><div className="home-album-list">{recentAlbums.map((album) => <button key={album.id} onClick={() => openAlbum(album.id)}><span><strong>{album.name}</strong><small>{album.category}</small></span><b>{album.capture_count} 张</b></button>)}</div></section>
    </section>}
    <section className="home-management-grid">
      <section className="panel recent-photos-panel"><div className="panel-heading"><div><h3>最近照片</h3></div><button className="text-action" onClick={openPhotos}>查看全部</button></div><div className="recent-photo-grid">
        {(library?.items ?? []).slice(0, 8).map((item, _index, recent) => <button key={item.id} onClick={() => openCapture(item.id, recent.map((entry) => entry.id))}><img src={item.thumbnail_url} alt={item.stem} /><span>{item.stem}</span></button>)}
      </div></section>
      <section className="panel pending-panel"><div className="panel-heading"><div><h3>待处理</h3></div></div><div className="pending-list">
        {pendingEvents > 0 && <button onClick={openAlbums}><span><strong>{pendingEvents}</strong> 个相册名称待确认</span><b>整理相册</b></button>}
        {pendingSimilarity > 0 && <button onClick={openBursts}><span><strong>{numberFormat.format(pendingSimilarity)}</strong> 组相似照片待挑选</span><b>继续选片</b></button>}
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
  const [qualityAlbumId, setQualityAlbumId] = useState("");
  const [similarityGroups, setSimilarityGroups] = useState<SimilarityGroupsResponse | null>(null);
  const [groupOffset, setGroupOffset] = useState(0);
  const [groupPageSize, setGroupPageSize] = useState(40);
  const [groupReviewFilter, setGroupReviewFilter] = useState<SimilarityReviewFilter>("pending");
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
      getJson<QualityResponse>(`/api/quality?${new URLSearchParams({ limit: String(qualityPageSize), offset: String(qualityOffset), review_filter: qualityFilter, ...(qualitySearch.trim() ? { search: qualitySearch.trim() } : {}), ...(qualityAlbumId ? { album_id: qualityAlbumId } : {}) }).toString()}`),
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
  }, [albumOffset, albumPageSize, groupAlbumId, groupOffset, groupPageSize, groupReviewFilter, libraryOffset, libraryQuery, qualityAlbumId, qualityFilter, qualityOffset, qualityPageSize, qualitySearch]);

  useEffect(() => {
    Promise.all([refreshLibrary(), getJson<Task>("/api/tasks/current").then((result) => setTask(taskForDisplay(result)))]).catch(
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
      if (qualityAlbumId) parameters.set("album_id", qualityAlbumId);
      getJson<QualityResponse>(`/api/quality?${parameters}`, { signal: controller.signal })
        .then(setQuality).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    }, qualitySearch ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [qualityAlbumId, qualityFilter, qualityOffset, qualityPageSize, qualitySearch]);

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

  useEffect(() => {
    if (task?.status !== "complete" && task?.status !== "cancelled") return;
    const completedId = task.id;
    const timer = window.setTimeout(() => {
      window.localStorage.setItem("tangerine-task-receipt", taskReceipt(task));
      setTask((current) => current?.id === completedId && (current.status === "complete" || current.status === "cancelled")
        ? { ...current, status: "idle", stage: "idle", message: "等待任务" }
        : current);
    }, 8000);
    return () => window.clearTimeout(timer);
  }, [task?.id, task?.status]);

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

  const generateManifest = async (scope: LightroomManifestScope, albumId?: number) => {
    setError(null);
    try {
      setLightroomManifest(await getJson<LightroomManifest>("/api/lightroom/manifest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope, album_id: albumId ?? null }) }));
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

  const changeEquipmentOwnership = async (kind: "camera" | "lens" | "accessory", key: string, owned: boolean) => {
    setError(null);
    try {
      const result = await getJson<EquipmentCatalog>("/api/equipment/ownership", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, key, owned }),
      });
      setEquipment(result);
      pushToast("success", owned ? "已加入我的设备" : "已标记为未拥有");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const saveEquipmentItem = async (draft: EquipmentDraft) => {
    setError(null);
    try {
      const payload = {
        ...draft,
        filter_thread_mm: draft.filter_thread_mm ? Number(draft.filter_thread_mm) : null,
        thread_mm: draft.thread_mm ? Number(draft.thread_mm) : null,
      };
      const result = await getJson<EquipmentCatalog>("/api/equipment/items", {
        method: draft.key ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setEquipment(result);
      pushToast("success", draft.key ? "设备信息已更新" : "设备已添加");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const deleteEquipmentItem = async (kind: EquipmentKind, item: EquipmentItem) => {
    setError(null);
    try {
      const result = await getJson<EquipmentCatalog>("/api/equipment/items", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, key: item.inventory_key }),
      });
      setEquipment(result);
      pushToast("success", "设备已从管理清单移除");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const changeEquipmentVisibility = async (kind: EquipmentKind, item: EquipmentItem, visible: boolean) => {
    setError(null);
    try {
      const result = await getJson<EquipmentCatalog>("/api/equipment/visibility", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, key: item.inventory_key, visible }),
      });
      setEquipment(result);
      pushToast("success", visible ? "设备已恢复显示" : "设备已隐藏，可在页面底部恢复");
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
        {view === "home" && <HomeView overview={overview} statistics={statistics} archive={archive} activeBaseline={activeLibraryBaseline} library={libraryCaptures} filters={libraryFilters} similarity={similarityGroups} task={task} capabilities={capabilities} openPhotos={() => { setLibraryLandingSection("photos"); setView("library"); }} openAlbums={() => { setLibraryLandingSection("albums"); setView("library"); }} openAlbum={(albumId) => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: String(albumId), collapseGroups: true })); setView("library"); }} openBursts={() => setView("bursts")} openStatistics={() => setView("statistics")} continueLabel={({ library: "照片图库", bursts: "相似组选片", analysis: "质量分析", statistics: "摄影统计", equipment: "设备管理", lightroom: "后期输出", archive: "系统维护", settings: "应用设置", home: "首页概览" } as Record<View, string>)[lastWorkspaceView]} continueWork={() => setView(lastWorkspaceView)} openUnassigned={() => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: "__unassigned__", collapseGroups: false })); setView("library"); }} openMaintenance={() => setView("archive")} openCapture={openCapture} />}
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
          openAlbumQuality={(albumId) => { setQualityOffset(0); setQualityAlbumId(String(albumId)); setView("analysis"); }}
        />}
        {view === "bursts" && <BurstsView groups={similarityGroups} selectedGroup={selectedGroup} task={task} startVisual={startVisual} openGroup={openGroup} closeGroup={() => setSelectedGroup(null)} openCapture={openCapture} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} restoreGroupingRevision={restoreGroupingRevision} cancelTask={cancelTask} changeGroupPage={setGroupOffset} changeGroupPageSize={(limit) => { setGroupOffset(0); setGroupPageSize(limit); }} reviewFilter={groupReviewFilter} setReviewFilter={(filter) => { setGroupOffset(0); setGroupReviewFilter(filter); }} albumId={groupAlbumId} setAlbumId={(albumId) => { setGroupOffset(0); setSelectedGroup(null); setGroupReviewFilter("pending"); setGroupAlbumId(albumId); }} openAlbumPhotos={(albumId) => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: String(albumId), collapseGroups: true })); setView("library"); }} openAlbumQuality={(albumId) => { setQualityOffset(0); setQualityAlbumId(String(albumId)); setView("analysis"); }} />}
        {view === "analysis" && <AnalysisView analysis={analysis} preflight={aiPreflight} quality={quality} qualityFilter={qualityFilter} qualitySearch={qualitySearch} setQualityFilter={(filter) => { setQualityOffset(0); setQualityFilter(filter); }} setQualitySearch={(search) => { setQualityOffset(0); setQualitySearch(search); }} qualityAlbumId={qualityAlbumId} setQualityAlbumId={(albumId) => { setQualityOffset(0); setQualityAlbumId(albumId); }} openAlbumPhotos={(albumId) => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: String(albumId), collapseGroups: true })); setView("library"); }} openAlbumBursts={(albumId) => { setGroupOffset(0); setGroupReviewFilter("pending"); setGroupAlbumId(String(albumId)); setSelectedGroup(null); setView("bursts"); }} task={task} startQuality={startQuality} startDetailBackfill={startDetailBackfill} resumeDetailBackfill={resumeDetailBackfill} startAi={startAi} saveReview={saveReview} cancelTask={cancelTask} pauseTask={pauseTask} resumeAi={resumeAi} retryAiFailures={retryAiFailures} openCapture={openCapture} changeQualityPage={setQualityOffset} changeQualityPageSize={(limit) => { setQualityOffset(0); setQualityPageSize(limit); }} />}
        {view === "statistics" && <StatisticsView statistics={statistics} openLibraryWith={openLibraryWith} />}
        {view === "equipment" && <EquipmentView equipment={equipment} changeOwnership={changeEquipmentOwnership} saveItem={saveEquipmentItem} deleteItem={deleteEquipmentItem} changeVisibility={changeEquipmentVisibility} />}
        {view === "archive" && <ArchiveView archive={archive} activeLibrary={activeLibraryBaseline} createBaseline={createBaseline} createActiveBaseline={createActiveBaseline} checkIntegrity={checkIntegrity} />}
        {view === "lightroom" && <LightroomView status={lightroomStatus} manifest={lightroomManifest} capabilities={capabilities} albums={libraryFilters?.albums ?? []} generateManifest={generateManifest} />}
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
