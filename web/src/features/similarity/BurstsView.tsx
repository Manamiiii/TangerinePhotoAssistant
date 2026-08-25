import { useEffect, useState, type DragEvent } from "react";
import { getJson } from "../../api";
import { ModalShell } from "../../components/ModalShell";
import { AlbumWorkspaceHeader, CollectionScopeTabs, Pagination, type AlbumWorkspaceCounts } from "../../components/Navigation";
import { TaskCard, type Task } from "../../components/TaskCard";
import { formatExposure, numberFormat } from "../../formatters";
import type { ReviewPayload } from "../analysis/types";
import type { SimilarityAgeFilter, SimilarityAuditItem, SimilarityBatchPreview, SimilarityConfidenceFilter, SimilarityGroupDetail, SimilarityGroupsResponse, SimilarityReviewBatch, SimilarityReviewFilter, SimilarityRevision } from "./types";

const selectionReasonOptions = ["动作差异", "表情差异", "构图差异", "关键瞬间", "叙事补充"];

type CollectionScope = "all" | "albums";

function isVisualTask(task: Task | null) {
  if (!task || task.status === "idle") return false;
  const stage = task.stage.toLocaleLowerCase();
  return ["duplicates", "fingerprints"].includes(stage) || /视觉预筛|相似分组|画面指纹|精确重复/.test(task.message);
}

export function SimilarityGroupingEditor({ group, cancel, save, restore, restoreRevision }: {
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

export function BurstsView({ groups, selectedGroup, task, startVisual, openGroup, closeGroup, openCapture, saveReview, editGrouping, saveGrouping, restoreGroupingRevision, cancelTask, changeGroupPage, changeGroupPageSize, reviewFilter, setReviewFilter, confidenceFilter, setConfidenceFilter, ageFilter, setAgeFilter, refreshSimilarity, albumId, setAlbumId, albumWorkspaceCounts, openAlbumPhotos, openAlbumQuality }: {
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
  reviewFilter: SimilarityReviewFilter;
  setReviewFilter: (filter: SimilarityReviewFilter) => void;
  confidenceFilter: SimilarityConfidenceFilter;
  setConfidenceFilter: (filter: SimilarityConfidenceFilter) => void;
  ageFilter: SimilarityAgeFilter;
  setAgeFilter: (filter: SimilarityAgeFilter) => void;
  refreshSimilarity: () => Promise<void>;
  albumId: string;
  setAlbumId: (albumId: string) => void;
  albumWorkspaceCounts: AlbumWorkspaceCounts;
  openAlbumPhotos: (albumId: number) => void;
  openAlbumQuality: (albumId: number) => void;
}) {
  const [browseMode, setBrowseMode] = useState<CollectionScope>("all");
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [reasonEditorCaptureId, setReasonEditorCaptureId] = useState<number | null>(null);
  const [comparisonOrder, setComparisonOrder] = useState<"recommended" | "balanced" | "capture">("recommended");
  const [albumUndo, setAlbumUndo] = useState<SimilarityRevision | null>(null);
  const [batchWorkspaceOpen, setBatchWorkspaceOpen] = useState(false);
  const [batchPreview, setBatchPreview] = useState<SimilarityBatchPreview | null>(null);
  const [batchSelected, setBatchSelected] = useState<Set<number>>(new Set());
  const [reviewBatches, setReviewBatches] = useState<SimilarityReviewBatch[]>([]);
  const [auditItems, setAuditItems] = useState<SimilarityAuditItem[]>([]);
  const [batchSaving, setBatchSaving] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const groupItems = groups?.items ?? [];
  const currentIndex = selectedGroup ? groupItems.findIndex((item) => item.id === selectedGroup.id) : -1;
  const nextPending = groupItems.find((item, index) => index > currentIndex && item.review_status === "pending")
    ?? groupItems.find((item, index) => index !== currentIndex && item.review_status === "pending");
  const statusLabels = { pending: "待选", picked: "已选定", skipped: "已排除" } as const;
  const tierLabels = { best: "技术最佳", alternative: "接近备选", candidate: "候选", weak: "明显技术弱项", unrated: "未评分" } as const;
  const completedCount = Math.max(0, (groups?.total_count ?? 0) - (groups?.pending_count ?? 0));
  const completionPercent = groups?.total_count ? Math.round(completedCount / groups.total_count * 100) : 0;
  const selectedAlbum = groups?.albums.find((album) => String(album.id) === albumId) ?? null;
  const reasonEditorItem = selectedGroup?.items.find((item) => item.capture_id === reasonEditorCaptureId) ?? null;
  const comparisonItems = selectedGroup ? [...selectedGroup.items].sort((left, right) => (
    comparisonOrder === "capture"
      ? left.sequence_index - right.sequence_index
      : comparisonOrder === "balanced"
        ? (left.balanced_rank ?? 10_000) - (right.balanced_rank ?? 10_000)
          || left.sequence_index - right.sequence_index
        : (left.similarity_rank ?? 10_000) - (right.similarity_rank ?? 10_000)
        || (right.technical_score ?? -1) - (left.technical_score ?? -1)
        || left.sequence_index - right.sequence_index
  )) : [];
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
    setReasonEditorCaptureId(null);
  }, [selectedGroup?.id]);
  const loadBatchWorkspace = async () => {
    setBatchError(null);
    const albumParameter = albumId ? `&album_id=${albumId}` : "";
    try {
      const [preview, batches, audits] = await Promise.all([
        getJson<SimilarityBatchPreview>(`/api/similarity-groups/bulk-preview?limit=100${albumParameter}`),
        getJson<{ items: SimilarityReviewBatch[] }>("/api/similarity-review-batches?limit=20"),
        getJson<{ items: SimilarityAuditItem[] }>("/api/similarity-review-audits?limit=100"),
      ]);
      setBatchPreview(preview); setBatchSelected(new Set(preview.items.map((item) => item.id))); setReviewBatches(batches.items); setAuditItems(audits.items);
    } catch (reason) { setBatchError((reason as Error).message); }
  };
  const openBatchWorkspace = () => { setBatchWorkspaceOpen(true); void loadBatchWorkspace(); };
  const applyBatch = async () => {
    if (!batchPreview?.group_count || !batchSelected.size) return;
    setBatchSaving(true); setBatchError(null);
    try {
      await getJson("/api/similarity-groups/bulk-accept", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ group_ids: [...batchSelected], album_id: albumId ? Number(albumId) : null }) });
      await refreshSimilarity(); await loadBatchWorkspace();
    } catch (reason) { setBatchError((reason as Error).message); }
    finally { setBatchSaving(false); }
  };
  const undoBatch = async (batchId: number) => {
    setBatchSaving(true); setBatchError(null);
    try {
      await getJson(`/api/similarity-review-batches/${batchId}/undo`, { method: "POST" });
      await refreshSimilarity(); await loadBatchWorkspace();
    } catch (reason) { setBatchError((reason as Error).message); }
    finally { setBatchSaving(false); }
  };
  const saveAudit = async (item: SimilarityAuditItem, status: "confirmed" | "problem") => {
    setBatchSaving(true); setBatchError(null);
    try {
      await getJson(`/api/similarity-review-batches/${item.batch_id}/audits/${item.representative_capture_id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
      await loadBatchWorkspace();
    } catch (reason) { setBatchError((reason as Error).message); }
    finally { setBatchSaving(false); }
  };
  return (
    <>
      <section className="structure-hero burst-hero">
        <div><span className="section-kicker">照片挑选</span><h2>相似照片分组</h2><button className="primary-action" onClick={startVisual} disabled={task?.status === "running"}><span>{task?.status === "running" ? "分析进行中" : "更新相似分组"}</span><b aria-hidden="true">→</b></button></div>
        <div className="structure-stat"><strong>{groups ? numberFormat.format(groups.pending_count) : "—"}</strong><span>组待选 / 共 {groups ? numberFormat.format(groups.total_count) : "—"} 组</span><small>已完成 {completionPercent}%{groups?.pending_count ? ` · 预计约 ${groups.estimated_review_minutes} 分钟` : ""}</small></div>
      </section>
      <TaskCard task={isVisualTask(task) ? task : null} cancel={cancelTask} />
      {!selectedGroup && !albumId && <div className="workspace-view-nav burst-scope-nav"><CollectionScopeTabs scope={browseMode} setScope={setBrowseMode} allLabel="全部相似组" /></div>}
      {selectedGroup ? (
        <section className="panel comparison-panel">
          <div className="panel-heading comparison-heading">
            <div><button className="back-navigation" onClick={closeGroup}>← 返回相似组</button><span className="section-kicker">组内对比</span><h3>{selectedGroup.event_name}</h3></div>
            {editingGroupId !== selectedGroup.id && nextPending && <button className="toolbar-button primary next-group-action" onClick={() => openGroup(nextPending.id)}>下一组待选 →</button>}
          </div>
          {editingGroupId === selectedGroup.id ? <SimilarityGroupingEditor key={selectedGroup.id} group={selectedGroup} cancel={() => setEditingGroupId(null)} save={saveGrouping} restore={(captureId) => editGrouping(captureId, "auto")} restoreRevision={restoreGroupingRevision} /> : <>
          <div className="comparison-note comparison-context"><span>共 {selectedGroup.capture_count} 张 · 点击图片查看完整参数</span><div className="comparison-context-actions"><div className="burst-view-toggle" role="group" aria-label="组内照片排序"><button className={comparisonOrder === "recommended" ? "active" : ""} onClick={() => setComparisonOrder("recommended")}>技术推荐</button><button className={comparisonOrder === "balanced" ? "active" : ""} onClick={() => setComparisonOrder("balanced")}>兼顾差异</button><button className={comparisonOrder === "capture" ? "active" : ""} onClick={() => setComparisonOrder("capture")}>拍摄顺序</button></div><button className="toolbar-button" onClick={() => setEditingGroupId(selectedGroup.id)}>调整这一组</button></div></div>
          <div className="comparison-grid">
            {comparisonItems.map((item) => (
              <article role="button" tabIndex={0} aria-label={`查看 ${item.stem} 详情`} className={`comparison-card ${item.auto_pick ? "auto-pick" : ""} ${item.user_pick ? "user-pick" : ""} ${item.user_reject ? "user-reject" : ""}`} key={item.capture_id} onClick={() => openCapture(item.capture_id, comparisonItems.map((member) => member.capture_id))} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openCapture(item.capture_id, comparisonItems.map((member) => member.capture_id)); } }}>
                <div className="photo-frame">
                  <img src={item.thumbnail_url} loading="lazy" alt={`${item.stem} 缩略图`} />
                  {item.similarity_rank != null && item.similarity_rank > 0 ? <span className="photo-rank">#{item.similarity_rank}</span> : null}
                  {Boolean(item.auto_pick || (comparisonOrder === "balanced" && item.diversity_candidate) || item.user_pick) ? <span className="photo-flags">{item.auto_pick ? <span className="photo-flag">技术推荐</span> : null}{comparisonOrder === "balanced" && item.diversity_candidate ? <span className="photo-flag diversity">差异候选</span> : null}{item.user_pick ? <span className="photo-flag user">组内保留</span> : null}</span> : null}
                </div>
                <div className="photo-card-copy"><strong>{item.stem}</strong><span>{item.technical_score == null ? "尚未检测" : `健康度 ${Math.round(item.technical_score)}`} · {formatExposure(item.exposure_time)} · ISO {item.iso ?? "—"}</span><small className={`recommendation-tier ${item.recommendation_tier}`}>{tierLabels[item.recommendation_tier]}</small><small className="comparison-reason">{comparisonOrder === "balanced" && item.diversity_reason ? item.diversity_reason : item.recommendation_reason}</small></div>
                <div className="photo-review" onClick={(event) => event.stopPropagation()}>
                  <select aria-label={`${item.stem} 人工星级`} value={item.user_rating ?? ""} onChange={(event) => saveReview(item.capture_id, { user_rating: event.target.value ? Number(event.target.value) : null, user_pick: Boolean(item.user_pick), user_reject: Boolean(item.user_reject), user_note: item.user_note })}>
                    <option value="">星级</option><option value="1">1★</option><option value="2">2★</option><option value="3">3★</option><option value="4">4★</option><option value="5">5★</option>
                  </select>
                  <button className={item.user_pick ? "selected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: !item.user_pick, user_reject: false, user_note: item.user_note })}>保留</button>
                  <button className={item.user_reject ? "rejected" : ""} onClick={() => saveReview(item.capture_id, { user_rating: item.user_rating, user_pick: false, user_reject: !item.user_reject, user_note: item.user_note })}>排除</button>
                  <button disabled={!item.user_pick} title={item.user_pick ? "编辑保留依据" : "先将照片标记为保留"} onClick={() => setReasonEditorCaptureId(item.capture_id)}>依据{item.selection_reasons.length ? ` ${item.selection_reasons.length}` : ""}</button>
                </div>
              </article>
            ))}
          </div></>}
        </section>
      ) : !albumId && browseMode === "albums" ? (
        <section className="panel album-selection-panel">
          <div className="panel-heading compact-list-heading"><div><h3>选择相册</h3></div><span className="batch-count">{groups?.albums.length ?? 0} 个相册包含相似组</span></div>
          <div className="similarity-album-grid">{(groups?.albums ?? []).map((album) => { const done = album.total_count - album.pending_count; const percent = album.total_count ? Math.round(done / album.total_count * 100) : 0; return <button key={album.id} onClick={() => setAlbumId(String(album.id))}><span><small>{album.category}</small><strong>{album.name}</strong></span><b><strong>{album.pending_count}</strong><small>待选</small></b><i><span style={{ width: `${percent}%` }} /></i><em>共 {album.total_count} 组 · 已完成 {percent}%</em></button>; })}</div>
          {!groups?.albums.length && <div className="empty-state">还没有可处理的相似组，请先更新相似分组。</div>}
        </section>
      ) : (<>
        {albumId && <AlbumWorkspaceHeader name={selectedAlbum?.name ?? "相册选片"} category={selectedAlbum?.category ?? "相册"} summary={`${groups?.pending_count ?? 0} 组待选 · 共 ${groups?.total_count ?? 0} 组`} counts={albumWorkspaceCounts} current="bursts" back={() => { setBrowseMode("albums"); setAlbumId(""); }} openPhotos={() => openAlbumPhotos(Number(albumId))} openBursts={() => undefined} openQuality={() => openAlbumQuality(Number(albumId))} />}
        <section className="panel similarity-panel">
          {albumUndo && <div className="similarity-recovery-bar"><span>本相册最近一次人工分组仍可撤销</span><button className="toolbar-button" onClick={() => { if (window.confirm("撤销本相册最近一次人工分组调整？")) void restoreGroupingRevision(albumUndo.id, true); }}>撤销最近调整</button></div>}
          <div className="similarity-list-controls"><div className="similarity-filter-cluster"><div className="burst-view-toggle" role="tablist" aria-label="选片进度筛选">{([['pending', '待选'], ['completed', '已完成'], ['adjusted', '人工调整'], ['all', '全部']] as const).map(([value, label]) => <button key={value} className={reviewFilter === value ? "active" : ""} onClick={() => setReviewFilter(value)}>{label}</button>)}</div><label>置信度<select value={confidenceFilter} onChange={(event) => setConfidenceFilter(event.target.value as SimilarityConfidenceFilter)}><option value="all">全部</option><option value="low">需重点看 · {groups?.confidence_counts.low ?? 0}</option><option value="medium">一般 · {groups?.confidence_counts.medium ?? 0}</option><option value="high">高 · {groups?.confidence_counts.high ?? 0}</option></select></label><label>拍摄距今<select value={ageFilter} onChange={(event) => setAgeFilter(event.target.value as SimilarityAgeFilter)}><option value="all">全部</option><option value="older">半年以上</option><option value="month">1–6 个月</option><option value="recent">30 天内</option></select></label></div><div className="similarity-scale-actions"><span className="batch-count">当前 {numberFormat.format(groups?.count ?? 0)} 组</span><button className="toolbar-button" onClick={openBatchWorkspace}>批量预览</button></div></div>
          <div className="similarity-grid">
            {groupItems.map((group) => (
              <button className="similarity-card" key={group.id} onClick={() => openGroup(group.id)}>
                <span className="similarity-cover"><img src={group.thumbnail_url} loading="lazy" alt={`${group.event_name} 相似组封面`} /><b>{group.capture_count} 张</b><i className={`review-status-badge ${group.review_status}`}>{statusLabels[group.review_status]}</i></span>
                <span className="similarity-copy"><strong>{group.event_name}</strong><small>{group.recommended_stem ? `推荐 ${group.recommended_stem}` : "等待技术评分"}{group.average_score == null ? "" : ` · 均分 ${group.average_score}`}{group.pick_count ? ` · ${group.pick_count} 张入选` : ""}</small><em className={`similarity-confidence ${group.confidence_level}`}>{group.confidence_level === "high" ? "高置信" : group.confidence_level === "medium" ? "一般" : "需重点看"}{group.pending_age_days != null ? ` · 拍摄距今 ${group.pending_age_days} 天` : ""}</em></span>
              </button>
            ))}
            {!groupItems.length && <div className="empty-state">{{ pending: "所有相似组都已处理完，可切换到“全部”回顾。", completed: "还没有完成选片的相似组。", adjusted: "当前没有生效中的人工分组调整。", all: "还没有相似分组，先运行相似分析。" }[reviewFilter]}</div>}
          </div>
          {groups && <Pagination count={groups.count} limit={groups.limit} offset={groups.offset} onChange={changeGroupPage} onLimitChange={changeGroupPageSize} />}
        </section>
      </>)}
      {reasonEditorItem && <ModalShell title={`${reasonEditorItem.stem} · 保留依据`} close={() => setReasonEditorCaptureId(null)}>
        <div className="selection-reason-editor"><p>可多选，用于复盘你的选片偏好，不会修改照片文件。</p><div className="detail-selection-reasons">{selectionReasonOptions.map((reason) => <button key={reason} className={reasonEditorItem.selection_reasons.includes(reason) ? "selected" : ""} onClick={() => saveReview(reasonEditorItem.capture_id, { user_rating: reasonEditorItem.user_rating, user_pick: true, user_reject: false, user_note: reasonEditorItem.user_note, selection_reasons: reasonEditorItem.selection_reasons.includes(reason) ? reasonEditorItem.selection_reasons.filter((itemReason) => itemReason !== reason) : [...reasonEditorItem.selection_reasons, reason] })}>{reason}</button>)}</div></div>
        <footer className="editor-footer"><button className="primary" onClick={() => setReasonEditorCaptureId(null)}>完成</button></footer>
      </ModalShell>}
      {batchWorkspaceOpen && <ModalShell title="相似组批量处理" close={() => setBatchWorkspaceOpen(false)}>
        <div className="similarity-batch-workspace">
          <section><div className="similarity-batch-heading"><div><strong>低风险推荐预览</strong><small>仅把技术推荐标为组内保留；点击卡片可取消本组。</small></div><div className="similarity-batch-selection"><span>已选 {batchSelected.size} / {batchPreview?.group_count ?? 0} 组 · 抽检 {batchSelected.size ? Math.ceil(batchSelected.size * .05) : 0} 组</span>{Boolean(batchPreview?.group_count) && <><button onClick={() => setBatchSelected(new Set(batchPreview?.items.map((item) => item.id)))}>全选</button><button onClick={() => setBatchSelected(new Set())}>清空</button></>}</div></div><div className="similarity-batch-preview">{(batchPreview?.items ?? []).map((item) => <button className={batchSelected.has(item.id) ? "selected" : ""} onClick={() => setBatchSelected((current) => { const next = new Set(current); if (next.has(item.id)) next.delete(item.id); else next.add(item.id); return next; })} key={item.id}><img src={item.thumbnail_url} loading="lazy" alt={item.recommended_stem ?? item.event_name} /><span><strong>{item.event_name}</strong><small>{item.capture_count} 张 · 推荐领先 {item.score_margin} 分</small></span><b>{batchSelected.has(item.id) ? "✓" : ""}</b></button>)}</div>{batchPreview && !batchPreview.group_count && <div className="empty-state">当前范围没有满足高置信条件的待选组。</div>}<footer><span>不会排除其他照片；应用前重新校验，可从批次历史撤销。</span><button className="toolbar-button primary" disabled={batchSaving || !batchSelected.size} onClick={() => void applyBatch()}>{batchSaving ? "处理中" : `处理 ${batchSelected.size} 组`}</button></footer></section>
          {!!auditItems.length && <section><div className="similarity-batch-heading"><div><strong>5% 稳定抽检</strong><small>只核对批量结论，不要求重看全部照片。</small></div></div><div className="similarity-audit-list">{auditItems.map((item) => <article key={`${item.batch_id}-${item.representative_capture_id}`}><button disabled={!item.group_id} onClick={() => { if (item.group_id) { setBatchWorkspaceOpen(false); openGroup(item.group_id); } }}><img src={item.thumbnail_url} alt={item.stem} /><span><strong>{item.stem}</strong><small>{item.album_name ?? "未归入相册"}</small></span></button><span className={`audit-state ${item.audit_status}`}>{item.audit_status === "pending" ? "待抽检" : item.audit_status === "confirmed" ? "结论正确" : "发现问题"}</span><div><button disabled={batchSaving} onClick={() => void saveAudit(item, "confirmed")}>正确</button><button disabled={batchSaving} onClick={() => void saveAudit(item, "problem")}>有问题</button></div></article>)}</div></section>}
          {!!reviewBatches.length && <section><div className="similarity-batch-heading"><div><strong>最近批次</strong><small>人工修改过批次结果后，为避免覆盖新结论将不再允许撤销。</small></div></div><div className="similarity-batch-history">{reviewBatches.map((batch) => <article key={batch.id}><span><strong>{batch.album_name ?? "全部相册"} · {batch.group_count} 组</strong><small>{batch.created_at.replace("T", " ").slice(0, 16)} · 抽检待办 {batch.pending_audit_count}</small></span><b>{batch.status === "undone" ? "已撤销" : "已应用"}</b>{batch.can_undo && <button disabled={batchSaving} onClick={() => void undoBatch(batch.id)}>撤销批次</button>}</article>)}</div></section>}
          {batchError && <div className="portable-error" role="alert">{batchError}</div>}
        </div>
      </ModalShell>}
    </>
  );
}
