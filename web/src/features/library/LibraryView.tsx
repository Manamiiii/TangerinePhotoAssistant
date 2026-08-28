import { useEffect, useRef, useState } from "react";
import { getJson } from "../../api";
import { ModalShell } from "../../components/ModalShell";
import { AlbumWorkspaceHeader, CollectionScopeTabs, Pagination, type AlbumWorkspaceCounts } from "../../components/Navigation";
import { TaskCard, type Task } from "../../components/TaskCard";
import { formatBytes, formatDate, formatFileSize, numberFormat } from "../../formatters";
import type { ReviewPayload } from "../analysis/types";
import type { Overview } from "../overview/types";
import type { CaptureTagDimension, DetailMode } from "../details/types";
import { captureContext } from "../details/detailNavigation";
import type { EquipmentCatalog } from "../equipment/types";
import { SimilarityGroupingEditor } from "../similarity/BurstsView";
import type { SimilarityGroupDetail } from "../similarity/types";
import type { EventItem, EventsResponse, LibraryCapturesResponse, LibraryFilters, LibraryQuery, LibrarySection, PhotoExportOptions, PhotoExportResult, PhotoInboxStatus, PhotoLayout } from "./types";

function isLibraryTask(task: Task | null) {
  if (!task || task.status === "idle") return false;
  const stage = task.stage.toLocaleLowerCase();
  return ["indexing", "metadata", "pairing", "structure"].includes(stage) || /图库更新|核对文件|扫描|相册/.test(task.message);
}

function ratingStars(rating: number | null) {
  return rating ? "★".repeat(rating) : "—";
}

function AlbumsView({ albums, filters, equipment, updateAlbum, createAlbum, createAlbumType, renameAlbumType, deleteAlbumType, openAlbum, changePage, changePageSize }: {
  albums: EventsResponse | null;
  filters: LibraryFilters | null;
  equipment: EquipmentCatalog | null;
  updateAlbum: (album: EventItem, changes: Partial<Pick<EventItem, "proposed_name" | "category" | "status" | "equipment_keys" | "equipment_count">>) => void;
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
  const [albumEquipmentKeys, setAlbumEquipmentKeys] = useState<string[]>([]);
  const [newTypeName, setNewTypeName] = useState("");
  const [editingType, setEditingType] = useState<string | null>(null);
  const [editedTypeName, setEditedTypeName] = useState("");
  const selectableAccessories = [
    ...(equipment?.accessories ?? []),
    ...(equipment?.hidden.accessory ?? []),
  ].filter((item, index, items) =>
    (item.owned || albumEquipmentKeys.includes(item.inventory_key))
    && items.findIndex((candidate) => candidate.inventory_key === item.inventory_key) === index
  );
  const openAlbumEditor = (album: EventItem | "new") => {
    setAlbumEditor(album);
    setAlbumName(album === "new" ? "" : album.proposed_name);
    setAlbumCategory(album === "new" ? (filters?.album_types[0]?.name ?? "日常") : album.category);
    setAlbumEquipmentKeys(album === "new" ? [] : album.equipment_keys);
  };
  const saveAlbum = () => {
    if (!albumName.trim() || !albumCategory) return;
    if (albumEditor === "new") createAlbum(albumName.trim(), albumCategory);
    else if (albumEditor) updateAlbum(albumEditor, { proposed_name: albumName.trim(), category: albumCategory, equipment_keys: albumEquipmentKeys, equipment_count: albumEquipmentKeys.length });
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
              <div className="event-main"><strong>{album.proposed_name}</strong><span>{album.source_count ? `${album.source_count} 个拍摄来源` : "手动创建"}{album.equipment_count ? ` · ${album.equipment_count} 件本次使用附件` : ""}</span></div>
              <div className="event-measure"><strong>{numberFormat.format(album.capture_count)}</strong><span>照片</span></div>
              <div className="album-date"><strong>{album.start_at?.slice(0, 10) ?? "—"}</strong><span>拍摄日期</span></div>
              <div className="album-row-actions"><button onClick={() => openAlbumEditor(album)}>编辑</button>{album.source_count > 0 ? <button title="打开该相册的第一个现存来源目录" onClick={() => void getJson(`/api/albums/${album.id}/open-folder`, { method: "POST" })}>打开目录</button> : <span aria-hidden="true" />}{album.status !== "confirmed" ? <button onClick={() => updateAlbum(album, { status: "confirmed" })}>确认</button> : <span aria-hidden="true" />}<button className="album-open-action" onClick={() => openAlbum(album.id)}>打开照片</button></div>
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
          {albumEditor !== "new" && <fieldset className="album-equipment-field"><legend>本次拍摄使用的附件</legend><p>仅记录 EXIF 无法确认的脚架、滤镜、闪光灯等附件。</p><div>{selectableAccessories.map((item) => <label key={item.inventory_key}><input type="checkbox" checked={albumEquipmentKeys.includes(item.inventory_key)} onChange={(event) => setAlbumEquipmentKeys((current) => event.target.checked ? [...current, item.inventory_key] : current.filter((key) => key !== item.inventory_key))} /><span>{item.display_name ?? item.model}{!item.owned ? "（当前未拥有）" : ""}</span></label>)}</div>{!selectableAccessories.length && <small>请先在设备管理中添加或标记已拥有附件。</small>}</fieldset>}
          <footer><button type="button" className="toolbar-button" onClick={() => setAlbumEditor(null)}>取消</button><button className="toolbar-button primary" disabled={!albumName.trim() || !albumCategory}>保存</button></footer>
        </form>
      </ModalShell>}
    </>
  );
}




function SimilarityPickerModal({ group, close, openCapture, saveReview, editGrouping, saveGrouping, restoreGroupingRevision }: {
  group: SimilarityGroupDetail;
  close: () => void;
  openCapture: (captureId: number, context?: number[], mode?: DetailMode, immersive?: boolean) => void;
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
      <div className="similarity-picker-copy"><strong>{item.stem}</strong><small>{item.technical_score == null ? "未检测" : `健康度 ${Math.round(item.technical_score)}`} · ISO {item.iso ?? "—"}</small></div>
      <div className="similarity-picker-actions"><select value={item.user_rating ?? ""} onChange={(event) => saveReview(item.capture_id, { user_rating: event.target.value ? Number(event.target.value) : null, user_pick: Boolean(item.user_pick), user_reject: Boolean(item.user_reject), user_note: item.user_note })}><option value="">星级</option>{[1, 2, 3, 4, 5].map((rating) => <option key={rating} value={rating}>{rating}★</option>)}</select><button className={item.user_pick ? "selected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: !item.user_pick, user_reject: false, user_note: item.user_note })}>保留</button><button className={item.user_reject ? "rejected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: false, user_reject: !item.user_reject, user_note: item.user_note })}>排除</button></div>
    </article>)}</div></>}
  </ModalShell>;
}

type ManagedTag = { id: number; dimension: CaptureTagDimension; name: string; built_in: number; active: number; capture_count: number };
type SavedLibraryView = { id: string; name: string; query: LibraryQuery };
const savedViewQueryKeys: Array<keyof LibraryQuery> = [
  "pageSize", "albumId", "category", "camera", "lens", "rating", "selection",
  "quality", "tagSubject", "tagStatus", "tagProblem", "tagLocation",
  "selectionReason", "modelProblem", "reviewCondition", "dateFrom", "dateTo",
  "search", "sort", "collapseGroups",
];

function savedViewMatches(viewQuery: LibraryQuery, currentQuery: LibraryQuery) {
  return savedViewQueryKeys.every((key) => viewQuery[key] === currentQuery[key]);
}
const tagDimensionLabels: Record<CaptureTagDimension, string> = { subject: "题材", status: "工作状态", problem: "人工问题", location: "地点" };

function TagManager({ close, changed }: { close: () => void; changed: () => void }) {
  const [items, setItems] = useState<ManagedTag[]>([]);
  const [dimension, setDimension] = useState<CaptureTagDimension>("subject");
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<ManagedTag | null>(null);
  const [editingName, setEditingName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = async () => setItems((await getJson<{ items: ManagedTag[] }>("/api/tag-definitions")).items);
  useEffect(() => { void load(); }, []);
  const mutate = async (path: string, method: "POST" | "PUT" | "DELETE", body?: object) => {
    try {
      setError(null);
      await getJson(path, { method, ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
      await load();
      changed();
    } catch (reason) { setError((reason as Error).message); }
  };
  const visible = items.filter((item) => item.dimension === dimension);
  return <ModalShell title="管理分类与状态" close={close} wide>
    <div className="tag-manager">
      <p>题材、问题和地点可多选；工作状态每张只保留一个。内置标签可以停用但不会删除，自定义标签可改名；正在使用的标签只能停用，以免丢失照片上的已有标记。</p>
      <div className="section-tabs">{(Object.entries(tagDimensionLabels) as Array<[CaptureTagDimension, string]>).map(([value, label]) => <button key={value} className={dimension === value ? "active" : ""} onClick={() => setDimension(value)}>{label}</button>)}</div>
      <form onSubmit={(event) => { event.preventDefault(); if (newName.trim()) { void mutate("/api/tag-definitions", "POST", { dimension, name: newName.trim() }); setNewName(""); } }}><input value={newName} maxLength={40} placeholder={`新增${tagDimensionLabels[dimension]}标签`} onChange={(event) => setNewName(event.target.value)} /><button className="toolbar-button primary" disabled={!newName.trim()}>新增</button></form>
      <div className="tag-manager-list">{visible.map((item) => <div className={!item.active ? "inactive" : ""} key={item.id}>
        {editing?.id === item.id ? <input autoFocus value={editingName} maxLength={40} onChange={(event) => setEditingName(event.target.value)} /> : <span><strong>{item.name}</strong><small>{item.built_in ? "内置" : "自定义"} · {item.capture_count} 张照片{!item.active ? " · 已停用" : ""}</small></span>}
        <div>{editing?.id === item.id ? <><button onClick={() => { if (editingName.trim()) void mutate(`/api/tag-definitions/${item.id}`, "PUT", { name: editingName.trim() }); setEditing(null); }}>保存</button><button onClick={() => setEditing(null)}>取消</button></> : <>{!item.built_in && <button onClick={() => { setEditing(item); setEditingName(item.name); }}>改名</button>}<button onClick={() => void mutate(`/api/tag-definitions/${item.id}`, "PUT", { active: !item.active })}>{item.active ? "停用" : "恢复"}</button>{!item.built_in && item.capture_count === 0 && <button className="danger-text" onClick={() => void mutate(`/api/tag-definitions/${item.id}`, "DELETE")}>删除</button>}</>}</div>
      </div>)}</div>
      {error && <div className="portable-error" role="alert">{error}</div>}
    </div>
  </ModalShell>;
}

function PhotoLibraryView({ library, filters, query, updateQuery, openCapture, openGroup, editGrouping, exportPhotos, assignToAlbum, batchTag, batchReview, changePage, changePageSize, albumContext = false, refreshLibrary }: {
  library: LibraryCapturesResponse | null;
  filters: LibraryFilters | null;
  query: LibraryQuery;
  updateQuery: (changes: Partial<LibraryQuery>) => void;
  openCapture: (captureId: number, context?: number[], mode?: DetailMode, immersive?: boolean) => void;
  openGroup?: (groupId: number) => void;
  editGrouping?: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  exportPhotos: (captureIds: number[], options: PhotoExportOptions) => Promise<PhotoExportResult>;
  assignToAlbum: (albumId: number, captureIds: number[]) => Promise<void>;
  batchTag: (captureIds: number[], dimension: CaptureTagDimension, name: string, action: "add" | "remove") => Promise<void>;
  batchReview: (captureIds: number[], rating: number | null, selection: "picked" | "rejected" | "clear" | null) => Promise<void>;
  changePage: (offset: number) => void;
  changePageSize: (limit: number) => void;
  albumContext?: boolean;
  refreshLibrary?: () => void;
}) {
  const selectionLimit = 500;
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [selectionWarning, setSelectionWarning] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [searchDraft, setSearchDraft] = useState(query.search);
  const updateQueryRef = useRef(updateQuery);
  const [layout, setLayout] = useState<PhotoLayout>(() => {
    const saved = window.localStorage.getItem("tangerine-photo-layout");
    return saved === "list" || saved === "small" || saved === "large" ? saved : "medium";
  });
  const [targetAlbum, setTargetAlbum] = useState("");
  const [maxEdge, setMaxEdge] = useState(2048);
  const [includeJpeg, setIncludeJpeg] = useState(true);
  const [includeRaw, setIncludeRaw] = useState(false);
  const [originalJpeg, setOriginalJpeg] = useState(false);
  const [batchRating, setBatchRating] = useState("");
  const [exporting, setExporting] = useState(false);
  const [latestExport, setLatestExport] = useState<PhotoExportResult | null>(null);
  const [selectionGroup, setSelectionGroup] = useState<SimilarityGroupDetail | null>(null);
  const [selectionGroupDraft, setSelectionGroupDraft] = useState<Set<number>>(new Set());
  const [batchTagEditor, setBatchTagEditor] = useState(false);
  const [batchTagDimension, setBatchTagDimension] = useState<CaptureTagDimension>("subject");
  const [batchTagName, setBatchTagName] = useState("");
  const [batchTagAction, setBatchTagAction] = useState<"add" | "remove">("add");
  const [batchTagSaving, setBatchTagSaving] = useState(false);
  const [tagManagerOpen, setTagManagerOpen] = useState(false);
  const [savedViews, setSavedViews] = useState<SavedLibraryView[]>(() => {
    try {
      const parsed = JSON.parse(window.localStorage.getItem("tangerine-saved-library-views") ?? "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch { return []; }
  });
  const [saveViewOpen, setSaveViewOpen] = useState(false);
  const [savedViewsOpen, setSavedViewsOpen] = useState(false);
  const [saveViewName, setSaveViewName] = useState("");
  const savedViewsMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => { updateQueryRef.current = updateQuery; }, [updateQuery]);
  useEffect(() => { setSearchDraft(query.search); }, [query.search]);
  useEffect(() => {
    if (searchDraft === query.search) return;
    const timeout = window.setTimeout(() => updateQueryRef.current({ search: searchDraft }), 300);
    return () => window.clearTimeout(timeout);
  }, [searchDraft, query.search]);
  useEffect(() => window.localStorage.setItem("tangerine-photo-layout", layout), [layout]);
  useEffect(() => window.localStorage.setItem("tangerine-saved-library-views", JSON.stringify(savedViews)), [savedViews]);
  useEffect(() => {
    if (!savedViewsOpen) return;
    const closeMenu = (event: PointerEvent) => {
      if (!savedViewsMenuRef.current?.contains(event.target as Node)) {
        setSavedViewsOpen(false);
        setSaveViewOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSavedViewsOpen(false);
        setSaveViewOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeMenu);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeMenu);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [savedViewsOpen]);
  const toggle = (captureIds: number[]) => {
    const next = new Set(selected);
    const remove = captureIds.every((captureId) => next.has(captureId));
    const additions = captureIds.filter((captureId) => !next.has(captureId));
    if (!remove && next.size + additions.length > selectionLimit) {
      setSelectionWarning(`单次批量操作最多选择 ${selectionLimit} 张；请先处理当前选择。`);
      return;
    }
    captureIds.forEach((captureId) => remove ? next.delete(captureId) : next.add(captureId));
    setSelectionWarning(null);
    setSelected(next);
  };
  const exportSelected = async () => {
    if (!selected.size) return;
    setExporting(true);
    try {
      const result = await exportPhotos(Array.from(selected), { includeJpeg, includeRaw, originalJpeg, maxEdge });
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
  const unselectedPageCount = pageCaptureIds.filter((captureId) => !selected.has(captureId)).length;
  const canSelectPage = selected.size + unselectedPageCount <= selectionLimit;
  const leaveSelectionMode = () => {
    setSelected(new Set());
    setSelectionWarning(null);
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
    const next = new Set([...selected].filter((id) => !memberIds.has(id)).concat([...selectionGroupDraft]));
    if (next.size > selectionLimit) {
      setSelectionWarning(`单次批量操作最多选择 ${selectionLimit} 张；请先处理当前选择。`);
      return;
    }
    setSelected(next);
    setSelectionWarning(null);
    setSelectionGroup(null);
  };
  const clearFilters = () => updateQuery({ albumId: albumContext ? query.albumId : "", category: "", camera: "", lens: "", rating: "", selection: "", quality: "", tagSubject: "", tagStatus: "", tagProblem: "", tagLocation: "", selectionReason: "", modelProblem: "", reviewCondition: "", dateFrom: "", dateTo: "", search: "", sort: "newest" });
  const saveCurrentView = () => {
    const name = saveViewName.trim();
    if (!name) return;
    setSavedViews((current) => [
      ...current.filter((view) => view.name.toLocaleLowerCase() !== name.toLocaleLowerCase()),
      { id: `${Date.now()}`, name, query: { ...query } },
    ]);
    setSaveViewName("");
    setSaveViewOpen(false);
    setSavedViewsOpen(false);
  };
  const savedViewSummary = (viewQuery: LibraryQuery) => {
    const filtersInView = [viewQuery.albumId, viewQuery.category, viewQuery.camera, viewQuery.lens, viewQuery.rating, viewQuery.selection, viewQuery.quality, viewQuery.tagSubject, viewQuery.tagStatus, viewQuery.tagProblem, viewQuery.tagLocation, viewQuery.selectionReason, viewQuery.modelProblem, viewQuery.reviewCondition, viewQuery.dateFrom, viewQuery.dateTo, viewQuery.search].filter(Boolean).length;
    const sortLabel = ({ newest: "最新拍摄", oldest: "最早拍摄", name: "文件名称", rating: "人工星级" } as Record<string, string>)[viewQuery.sort] ?? "自定义排序";
    return `${filtersInView ? `${filtersInView} 项条件` : "全部照片"} · ${sortLabel}`;
  };
  const activeSavedViewId = savedViews.find((view) => savedViewMatches(view.query, query))?.id ?? null;
  const activeFilters: Array<{ key: keyof LibraryQuery; label: string }> = [
    ...(!albumContext && query.albumId ? [{ key: "albumId" as const, label: query.albumId === "__unassigned__" ? "未归入相册" : filters?.albums.find((album) => String(album.id) === query.albumId)?.name ?? "相册" }] : []),
    ...(query.category ? [{ key: "category" as const, label: `类型：${query.category}` }] : []),
    ...(query.camera ? [{ key: "camera" as const, label: query.camera }] : []),
    ...(query.lens ? [{ key: "lens" as const, label: query.lens }] : []),
    ...(query.rating ? [{ key: "rating" as const, label: `${query.rating} 星` }] : []),
    ...(query.selection ? [{ key: "selection" as const, label: query.selection === "picked" ? "相似组：已保留" : query.selection === "rejected" ? "相似组：已排除" : "相似组：未选择" }] : []),
    ...(query.quality ? [{ key: "quality" as const, label: { problems: "发现问题", low: "健康度低于 70", high: "健康度 85 以上", unanalyzed: "尚未分析" }[query.quality] ?? query.quality }] : []),
    ...(query.tagSubject ? [{ key: "tagSubject" as const, label: `题材：${query.tagSubject}` }] : []),
    ...(query.tagStatus ? [{ key: "tagStatus" as const, label: `状态：${query.tagStatus}` }] : []),
    ...(query.tagProblem ? [{ key: "tagProblem" as const, label: `问题：${query.tagProblem}` }] : []),
    ...(query.tagLocation ? [{ key: "tagLocation" as const, label: `地点：${query.tagLocation}` }] : []),
    ...(query.selectionReason ? [{ key: "selectionReason" as const, label: `相似组保留依据：${query.selectionReason}` }] : []),
    ...(query.modelProblem ? [{ key: "modelProblem" as const, label: `模型观察：${query.modelProblem}` }] : []),
    ...(query.reviewCondition ? [{ key: "reviewCondition" as const, label: `关联条件：${query.reviewCondition.split("|")[1] ?? query.reviewCondition}` }] : []),
    ...(query.dateFrom ? [{ key: "dateFrom" as const, label: `从 ${query.dateFrom}` }] : []),
    ...(query.dateTo ? [{ key: "dateTo" as const, label: `至 ${query.dateTo}` }] : []),
  ];
  return <>
    <section className="library-filter-shell">
      <div className="library-filter-toolbar">
        <label className="library-search"><span aria-hidden="true">⌕</span><input aria-label="搜索照片" value={searchDraft} onChange={(event) => setSearchDraft(event.target.value)} placeholder="搜索文件名、相册或目录" /></label>
        <button className={`toolbar-button filter-toggle ${filtersOpen ? "active" : ""}`} onClick={() => setFiltersOpen((current) => !current)}>筛选{activeFilters.length ? <b>{activeFilters.length}</b> : null}</button>
        <label className="sort-control"><select aria-label="照片排序" value={query.sort} onChange={(event) => updateQuery({ sort: event.target.value })}><option value="newest">最新拍摄</option><option value="oldest">最早拍摄</option><option value="name">文件名称</option><option value="rating">人工星级</option></select></label>
        <div className="saved-view-menu" ref={savedViewsMenuRef}>
          <button className={`toolbar-button ${savedViewsOpen ? "active" : ""}`} aria-haspopup="menu" aria-expanded={savedViewsOpen} onClick={() => { setSavedViewsOpen((current) => !current); setSaveViewOpen(false); }}>管理视图{savedViews.length ? <b>{savedViews.length}</b> : null}</button>
          {savedViewsOpen && <div className="saved-view-popover" role="menu">
            <div className="saved-view-heading"><span>常用视图</span><small>保存并快速恢复筛选</small></div>
            {savedViews.length > 0 ? <div className="saved-view-list">{savedViews.map((view) => <div className="saved-view-row" key={view.id}><button role="menuitem" onClick={() => { updateQuery(view.query); setSavedViewsOpen(false); }}><strong>{view.name}</strong><small>{savedViewSummary(view.query)}</small></button><button className="saved-view-delete" aria-label={`删除视图 ${view.name}`} title="删除" onClick={() => setSavedViews((current) => current.filter((item) => item.id !== view.id))}>×</button></div>)}</div> : <p className="saved-view-empty">还没有保存的视图。</p>}
            {saveViewOpen ? <form onSubmit={(event) => { event.preventDefault(); saveCurrentView(); }}><input autoFocus value={saveViewName} maxLength={40} placeholder="例如：最近未评分" onChange={(event) => setSaveViewName(event.target.value)} /><div><button type="button" onClick={() => setSaveViewOpen(false)}>取消</button><button className="primary" disabled={!saveViewName.trim()}>保存</button></div></form> : <button className="saved-view-create" onClick={() => setSaveViewOpen(true)}>＋ 保存当前筛选</button>}
          </div>}
        </div>
        {(activeFilters.length > 0 || query.search) && <button className="filter-clear" onClick={clearFilters}>全部清除</button>}
      </div>
      {savedViews.length > 0 && <div className="saved-view-shortcuts" aria-label="常用视图快捷入口"><span>常用</span><div>{savedViews.map((view) => <button key={view.id} className={activeSavedViewId === view.id ? "active" : ""} aria-pressed={activeSavedViewId === view.id} title={savedViewSummary(view.query)} onClick={() => updateQuery(view.query)}><strong>{view.name}</strong><small>{savedViewSummary(view.query)}</small></button>)}</div></div>}
      {activeFilters.length > 0 && <div className="active-filter-chips">{activeFilters.map((filter) => <button key={filter.key} onClick={() => updateQuery({ [filter.key]: "" })}>{filter.label}<span>×</span></button>)}</div>}
      {filtersOpen && <div className="library-filter-drawer"><div className="filter-drawer-heading"><span>筛选照片</span><button type="button" onClick={() => setTagManagerOpen(true)}>管理分类与状态</button></div>
        {!albumContext && <fieldset><legend>归属</legend><label><span>相册</span><select value={query.albumId} onChange={(event) => updateQuery({ albumId: event.target.value })}><option value="">全部相册</option><option value="__unassigned__">未归入相册</option>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select></label><label><span>类型</span><select value={query.category} onChange={(event) => updateQuery({ category: event.target.value })}><option value="">全部类型</option>{(filters?.album_types ?? []).map((type) => <option key={type.name}>{type.name}</option>)}</select></label></fieldset>}
        <fieldset><legend>器材</legend><label><span>相机</span><select value={query.camera} onChange={(event) => updateQuery({ camera: event.target.value })}><option value="">全部相机</option>{(filters?.cameras ?? []).map((camera) => <option key={camera}>{camera}</option>)}</select></label><label><span>镜头</span><select value={query.lens} onChange={(event) => updateQuery({ lens: event.target.value })}><option value="">全部镜头</option>{(filters?.lenses ?? []).map((lens) => <option key={lens}>{lens}</option>)}</select></label></fieldset>
        <fieldset><legend>评价</legend><label><span>人工星级</span><select value={query.rating} onChange={(event) => updateQuery({ rating: event.target.value })}><option value="">全部星级</option>{[5, 4, 3, 2, 1].map((rating) => <option key={rating} value={rating}>{rating} 星</option>)}</select></label><label><span>相似组结论</span><select value={query.selection} onChange={(event) => updateQuery({ selection: event.target.value })}><option value="">全部结论</option><option value="picked">已保留</option><option value="rejected">已排除</option><option value="unreviewed">未选择</option></select></label><label><span>技术健康度</span><select value={query.quality} onChange={(event) => updateQuery({ quality: event.target.value })}><option value="">全部结果</option><option value="problems">发现问题</option><option value="low">健康度低于 70</option><option value="high">健康度 85 以上</option><option value="unanalyzed">尚未分析</option></select></label><label><span>模型观察</span><select value={query.modelProblem} onChange={(event) => updateQuery({ modelProblem: event.target.value })}><option value="">全部观察</option>{(filters?.model_problems ?? []).map((problem) => <option key={problem.name} value={problem.name}>{problem.name}（{problem.capture_count}）</option>)}</select></label></fieldset>
        <fieldset><legend>标签</legend>{([['subject', 'tagSubject', '题材'], ['status', 'tagStatus', '工作状态'], ['problem', 'tagProblem', '人工问题'], ['location', 'tagLocation', '地点']] as Array<[CaptureTagDimension, keyof LibraryQuery, string]>).map(([dimension, key, label]) => <label key={dimension}><span>{label}</span><select value={String(query[key])} onChange={(event) => updateQuery({ [key]: event.target.value })}><option value="">全部</option>{(filters?.tags ?? []).filter((tag) => tag.dimension === dimension).map((tag) => <option key={tag.name} value={tag.name}>{tag.name}（{tag.capture_count}）</option>)}</select></label>)}<label><span>相似组保留依据</span><select value={query.selectionReason} onChange={(event) => updateQuery({ selectionReason: event.target.value })}><option value="">全部</option>{["动作差异", "表情差异", "构图差异", "关键瞬间", "叙事补充"].map((reason) => <option key={reason}>{reason}</option>)}</select></label></fieldset>
        <fieldset><legend>时间</legend><label><span>开始日期</span><input type="date" value={query.dateFrom} onChange={(event) => updateQuery({ dateFrom: event.target.value })} /></label><label><span>结束日期</span><input type="date" value={query.dateTo} onChange={(event) => updateQuery({ dateTo: event.target.value })} /></label></fieldset>
      </div>}
    </section>
    <section className="photo-view-toolbar">
      <div className="photo-layout-toggle" aria-label="照片显示方式">
        {([['list', '列表'], ['small', '小图'], ['medium', '中图'], ['large', '大图']] as Array<[PhotoLayout, string]>).map(([value, label]) => <button key={value} className={layout === value ? "active" : ""} onClick={() => setLayout(value)}>{label}</button>)}
      </div>
      <div className="photo-view-actions">{albumContext && <div className="burst-view-toggle"><button className={query.collapseGroups ? "active" : ""} onClick={() => updateQuery({ collapseGroups: true })}>折叠连拍</button><button className={!query.collapseGroups ? "active" : ""} onClick={() => updateQuery({ collapseGroups: false })}>展开全部</button></div>}<button className={`toolbar-button selection-entry ${selectionMode ? "active" : ""}`} onClick={() => selectionMode ? leaveSelectionMode() : setSelectionMode(true)}>{selectionMode ? "退出批量管理" : "批量管理"}</button></div>
    </section>
    <section className={`selection-toolbar ${selectionMode ? "visible" : ""}`}>
      <div className="batch-selection-summary"><strong>已选 {selected.size} / {selectionLimit} 张</strong><small className={selectionWarning ? "warning" : undefined} role="status">{selectionWarning ?? "只处理逐页明确勾选的照片，不会自动应用到全部筛选结果。"}</small><button disabled={!allSelected && !canSelectPage} title={!allSelected && !canSelectPage ? `本页全选会超过 ${selectionLimit} 张上限` : undefined} onClick={() => { setSelected(allSelected ? new Set([...selected].filter((id) => !pageCaptureIds.includes(id))) : new Set([...selected, ...pageCaptureIds])); setSelectionWarning(null); }}>{allSelected ? "取消本页" : "选择本页"}</button><button onClick={() => { setSelected(new Set()); setSelectionWarning(null); }}>清空</button></div>
      <div className="selection-actions">
        <button disabled={!selected.size} title="为所选照片添加或移除题材、工作状态、问题和地点标签" onClick={() => setBatchTagEditor(true)}>标签与状态</button>
        <div className="batch-review-action"><select aria-label="批量星级" value={batchRating} onChange={(event) => setBatchRating(event.target.value)}><option value="">设置星级…</option><option value="0">清除星级</option>{[1, 2, 3, 4, 5].map((rating) => <option key={rating} value={rating}>{"★".repeat(rating)}</option>)}</select><button disabled={!selected.size || !batchRating} onClick={async () => { await batchReview(Array.from(selected), Number(batchRating), null); setBatchRating(""); }}>应用星级</button></div>
        <div className="batch-album-action"><select aria-label="目标相册" value={targetAlbum} onChange={(event) => setTargetAlbum(event.target.value)}><option value="">选择目标相册…</option>{(filters?.albums ?? []).map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select><button disabled={!targetAlbum || !selected.size} onClick={async () => { await assignToAlbum(Number(targetAlbum), Array.from(selected)); setSelected(new Set()); }}>归入相册</button></div>
        <div className="batch-export-options" aria-label="导出文件类型">
          <label><input type="checkbox" checked={includeJpeg} onChange={(event) => setIncludeJpeg(event.target.checked)} />JPG</label>
          <label><input type="checkbox" checked={includeRaw} onChange={(event) => setIncludeRaw(event.target.checked)} />RAW</label>
          {includeJpeg && <select aria-label="JPG 尺寸" value={originalJpeg ? "original" : String(maxEdge)} onChange={(event) => { setOriginalJpeg(event.target.value === "original"); if (event.target.value !== "original") setMaxEdge(Number(event.target.value)); }}><option value="original">JPG 原文件（含 EXIF）</option><option value="1080">JPG · 1080px</option><option value="2048">JPG · 2048px</option><option value="3840">JPG · 3840px</option></select>}
        </div>
        <button className="toolbar-button primary export-share-button" disabled={!selected.size || exporting || (!includeJpeg && !includeRaw)} onClick={exportSelected}>{exporting ? "正在生成" : "生成导出 ZIP"}</button>
      </div>
    </section>
    {latestExport && <div className="export-success"><span>已生成 {latestExport.photo_count} 张 · JPG {latestExport.jpeg_count} · RAW {latestExport.raw_count} · {formatBytes(latestExport.size_bytes)}{latestExport.missing_raw_count ? ` · ${latestExport.missing_raw_count} 张无 RAW` : ""}</span><a href={latestExport.download_url} download={latestExport.filename}>再次下载</a></div>}
    {layout === "list" && <div className="photo-list-header" aria-hidden="true"><span>照片</span><span>拍摄时间</span><span>相册 / 相似组</span><span>大小</span><span>评价</span></div>}
    <section className={`photo-library-grid layout-${layout} ${selectionMode ? "selecting" : ""}`}>
      {items.map((item) => {
        const itemSelected = item.selection_capture_ids.every((captureId) => selected.has(captureId));
        const isGroup = item.item_type === "group" && item.similarity_group_id != null;
        return <article data-capture-id={item.id} tabIndex={-1} className={`library-photo-card ${itemSelected ? "selected" : ""} ${isGroup ? "group-card" : ""}`} key={isGroup ? `group-${item.similarity_group_id}` : `photo-${item.id}`}>
        {selectionMode && <button className="photo-select" aria-label={`${isGroup ? "选择组内照片" : itemSelected ? "取消选择" : "选择"} ${item.stem}`} onClick={() => isGroup ? void openGroupSelection(item.similarity_group_id!) : toggle(item.selection_capture_ids)}><span>{itemSelected ? "✓" : isGroup ? "…" : ""}</span></button>}
        <button className="photo-open" onClick={() => isGroup && selectionMode ? void openGroupSelection(item.similarity_group_id!) : openCapture(item.id, captureContext(items), undefined, true)}><img src={item.thumbnail_url} loading="lazy" decoding="async" alt={item.stem} />{isGroup && <span className="group-stack-badge">{item.similarity_group_size} 张{selectionMode ? " · 选择组内" : ""}</span>}</button>
        {isGroup && !selectionMode && openGroup && <button className="group-expand-button" onClick={() => openGroup(item.similarity_group_id!)}>展开组</button>}
        {layout === "list" ? <div className="photo-card-copy photo-list-copy"><div className="photo-list-identity"><strong>{isGroup ? `相似组 · ${item.stem}` : item.stem}</strong><small>{[item.camera_model, item.lens_model, item.pairing_status === "paired" ? "JPG + RAW" : null].filter(Boolean).join(" · ") || "器材信息未知"}</small></div><time>{item.captured_at ? item.captured_at.replace("T", " ").slice(0, 16) : "时间未知"}</time><div className="photo-list-context"><span>{item.album_name ?? "未归入相册"}</span>{isGroup ? <button className="similarity-inline" onClick={() => openGroup?.(item.similarity_group_id!)}>相似组 {item.similarity_group_size} 张</button> : item.similarity_group_id && openGroup ? <button className="similarity-inline" onClick={() => openGroup(item.similarity_group_id!)}>相似组 {item.similarity_group_size} 张</button> : null}</div><span className="photo-list-size">{formatFileSize(item.size_bytes)}</span><div className="photo-list-review" title={item.user_rating ? `${item.user_rating} 星` : "未评分"}><span className={item.user_rating ? "rating-stars" : "rating-empty"}>{ratingStars(item.user_rating)}</span>{item.similarity_group_id && (item.user_pick ? <b>保留</b> : item.user_reject ? <b className="rejected">排除</b> : null)}{item.technical_score != null ? <small>技术 {Math.round(item.technical_score)}</small> : <small>未分析</small>}</div></div> : <div className="photo-card-copy"><div className="photo-card-heading"><strong>{isGroup ? `相似组 · ${item.stem}` : item.stem}</strong><span>{item.captured_at?.slice(0, 10) ?? "日期未知"}</span></div><p className="photo-card-context">{item.album_name ?? "未归入相册"}<span>{isGroup ? `${item.similarity_group_size} 张相似照片` : formatBytes(item.size_bytes)}</span></p><small className="photo-card-equipment">{[item.camera_model, item.lens_model, item.pairing_status === "paired" ? "JPG + RAW" : null].filter(Boolean).join(" · ") || "器材信息未知"}</small><div className="photo-card-status"><span className={item.user_rating ? "rating-stars" : "rating-empty"}>{ratingStars(item.user_rating)}</span><div>{item.grouping_override === "exclude" && <>{editGrouping && <button className="similarity-inline" onClick={() => void editGrouping(item.id, "auto")}>恢复自动分组</button>}<b>已移出相似组</b></>}{!isGroup && item.similarity_group_id && openGroup ? <button className="similarity-inline" onClick={() => openGroup(item.similarity_group_id!)}>相似组 {item.similarity_group_size} 张</button> : null}{item.similarity_group_id && (item.user_pick ? <b>保留</b> : item.user_reject ? <b className="rejected">排除</b> : null)}</div></div></div>}
      </article>})}
      {!items.length && <div className="empty-state" aria-live="polite">{library === null ? "正在加载照片…" : "图库中还没有可查看的 JPEG 照片。"}</div>}
    </section>
    {library && <Pagination count={library.count} limit={library.limit} offset={library.offset} onChange={changePage} onLimitChange={changePageSize} />}
    {selectionGroup && <ModalShell title={`选择组内照片 · ${selectionGroup.capture_count} 张`} close={() => setSelectionGroup(null)} wide>
      <div className="group-export-tools"><span>这只是本次归类或导出的临时选择，不会改变正式入选结果。</span><div><button onClick={() => setSelectionGroupDraft(new Set(selectionGroup.items.filter((item) => item.user_pick).map((item) => item.capture_id)))}>人工入选</button><button onClick={() => setSelectionGroupDraft(new Set(selectionGroup.items.filter((item) => item.auto_pick).map((item) => item.capture_id)))}>技术推荐</button><button onClick={() => setSelectionGroupDraft(new Set(selectionGroup.items.map((item) => item.capture_id)))}>全选</button><button onClick={() => setSelectionGroupDraft(new Set())}>清空</button></div></div>
      <div className="group-export-grid">{selectionGroup.items.map((item) => <button key={item.capture_id} className={selectionGroupDraft.has(item.capture_id) ? "selected" : ""} onClick={() => setSelectionGroupDraft((current) => { const next = new Set(current); next.has(item.capture_id) ? next.delete(item.capture_id) : next.add(item.capture_id); return next; })}><img src={item.thumbnail_url} alt={item.stem} /><span>{selectionGroupDraft.has(item.capture_id) ? "✓ " : ""}{item.stem}{item.user_pick ? " · 已入选" : item.auto_pick ? " · 技术推荐" : ""}</span></button>)}</div>
      <footer className="editor-footer"><span>已选择 {selectionGroupDraft.size} 张</span><button onClick={() => setSelectionGroup(null)}>取消</button><button className="primary" onClick={applyGroupSelection}>确认选择</button></footer>
    </ModalShell>}
    {batchTagEditor && <ModalShell title={`批量标记 · ${selected.size} 张`} close={() => setBatchTagEditor(false)}><form className="editor-form" onSubmit={async (event) => { event.preventDefault(); if (!batchTagName.trim()) return; setBatchTagSaving(true); try { await batchTag(Array.from(selected), batchTagDimension, batchTagName.trim(), batchTagAction); setBatchTagEditor(false); setBatchTagName(""); } finally { setBatchTagSaving(false); } }}><label><span>操作</span><select value={batchTagAction} onChange={(event) => setBatchTagAction(event.target.value as "add" | "remove")}><option value="add">添加标签</option><option value="remove">移除人工标签</option></select></label><label><span>维度</span><select value={batchTagDimension} onChange={(event) => { setBatchTagDimension(event.target.value as CaptureTagDimension); setBatchTagName(""); }}><option value="subject">题材</option><option value="status">工作状态</option><option value="problem">人工问题</option><option value="location">地点</option></select></label><label><span>标签</span><input list="batch-tag-options" value={batchTagName} maxLength={40} placeholder={batchTagAction === "add" ? "选择或输入标签" : "选择要移除的标签"} onChange={(event) => setBatchTagName(event.target.value)} /><datalist id="batch-tag-options">{(filters?.tags ?? []).filter((tag) => tag.dimension === batchTagDimension).map((tag) => <option key={tag.name} value={tag.name} />)}</datalist></label>{batchTagDimension === "status" && batchTagAction === "add" && <p>设置新状态会替换所选照片原有的人工工作状态。</p>}<footer><button type="button" className="toolbar-button" onClick={() => setBatchTagEditor(false)}>取消</button><button className="toolbar-button primary" disabled={!batchTagName.trim() || batchTagSaving}>{batchTagSaving ? "保存中…" : "应用"}</button></footer></form></ModalShell>}
    {tagManagerOpen && <TagManager close={() => setTagManagerOpen(false)} changed={() => void refreshLibrary?.()} />}
  </>;
}

export function LibraryView({ overview, library, albums, filters, equipment, query, updateQuery, requestedSection, task, startScan, cancelTask, updateAlbum, createAlbum, createAlbumType, renameAlbumType, deleteAlbumType, assignToAlbum, batchTag, batchReview, openCapture, selectedGroup, openGroup, closeGroup, saveReview, editGrouping, saveGrouping, restoreGroupingRevision, exportPhotos, changePage, changePageSize, changeAlbumPage, changeAlbumPageSize, albumWorkspaceCounts, openAlbumBursts, openAlbumQuality, refreshLibrary }: {
  overview: Overview | null;
  library: LibraryCapturesResponse | null;
  albums: EventsResponse | null;
  filters: LibraryFilters | null;
  equipment: EquipmentCatalog | null;
  query: LibraryQuery;
  updateQuery: (changes: Partial<LibraryQuery>) => void;
  requestedSection: LibrarySection;
  task: Task | null;
  startScan: (albumId: number) => void;
  cancelTask: () => void;
  updateAlbum: (album: EventItem, changes: Partial<Pick<EventItem, "proposed_name" | "category" | "status" | "equipment_keys" | "equipment_count">>) => void;
  createAlbum: (name: string, category: string) => Promise<number | null>;
  createAlbumType: (name: string) => void;
  renameAlbumType: (name: string, nextName: string) => void;
  deleteAlbumType: (name: string) => void;
  assignToAlbum: (albumId: number, captureIds: number[]) => Promise<void>;
  batchTag: (captureIds: number[], dimension: CaptureTagDimension, name: string, action: "add" | "remove") => Promise<void>;
  batchReview: (captureIds: number[], rating: number | null, selection: "picked" | "rejected" | "clear" | null) => Promise<void>;
  openCapture: (captureId: number, context?: number[], mode?: DetailMode, immersive?: boolean) => void;
  selectedGroup: SimilarityGroupDetail | null;
  openGroup: (groupId: number) => void;
  closeGroup: () => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  editGrouping: (captureId: number, action: "exclude" | "split_before" | "auto") => Promise<void>;
  saveGrouping: (groupId: number, groups: number[][], excludedIds: number[]) => Promise<{ revision_id: number; group_ids: number[] }>;
  restoreGroupingRevision: (revisionId: number, useBefore?: boolean) => Promise<void>;
  exportPhotos: (captureIds: number[], options: PhotoExportOptions) => Promise<PhotoExportResult>;
  changePage: (offset: number) => void;
  changePageSize: (limit: number) => void;
  changeAlbumPage: (offset: number) => void;
  changeAlbumPageSize: (limit: number) => void;
  albumWorkspaceCounts: AlbumWorkspaceCounts;
  openAlbumBursts: (albumId: number) => void;
  openAlbumQuality: (albumId: number) => void;
  refreshLibrary: () => void;
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
  }, [requestedSection]);
  useEffect(() => {
    if (query.albumId && query.albumId !== "__unassigned__") {
      setActiveAlbumId(Number(query.albumId));
    } else {
      setActiveAlbumId(null);
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
      <TaskCard task={isLibraryTask(task) ? task : null} cancel={cancelTask} />
      {activeAlbumId ? <>
        <AlbumWorkspaceHeader name={activeAlbum?.name ?? "相册照片"} category={activeAlbum?.category ?? "相册"} summary={`${numberFormat.format(activeAlbum?.capture_count ?? library?.count ?? 0)} 张照片`} counts={albumWorkspaceCounts} current="library" back={leaveAlbum} openPhotos={() => undefined} openBursts={() => openAlbumBursts(activeAlbumId)} openQuality={() => openAlbumQuality(activeAlbumId)} />
        <PhotoLibraryView library={library} filters={filters} query={query} updateQuery={updateQuery} openCapture={openCapture} openGroup={openGroup} editGrouping={editGrouping} exportPhotos={exportPhotos} assignToAlbum={assignToAlbum} batchTag={batchTag} batchReview={batchReview} changePage={changePage} changePageSize={changePageSize} albumContext refreshLibrary={refreshLibrary} />
      </> : <>
        {section === "photos" && <PhotoLibraryView library={library} filters={filters} query={query} updateQuery={updateQuery} openCapture={openCapture} openGroup={openGroup} editGrouping={editGrouping} exportPhotos={exportPhotos} assignToAlbum={assignToAlbum} batchTag={batchTag} batchReview={batchReview} changePage={changePage} changePageSize={changePageSize} refreshLibrary={refreshLibrary} />}
        {section === "albums" && <AlbumsView albums={albums} filters={filters} equipment={equipment} updateAlbum={updateAlbum} createAlbum={createAlbum} createAlbumType={createAlbumType} renameAlbumType={renameAlbumType} deleteAlbumType={deleteAlbumType} openAlbum={showAlbum} changePage={changeAlbumPage} changePageSize={changeAlbumPageSize} />}
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
