import { useEffect, useState, type DragEvent } from "react";
import { getJson } from "../../api";
import { AlbumWorkspaceHeader, CollectionScopeTabs, Pagination } from "../../components/Navigation";
import { TaskCard, type Task } from "../../components/TaskCard";
import { formatExposure, numberFormat } from "../../formatters";
import type { ReviewPayload } from "../analysis/types";
import type { SimilarityGroupDetail, SimilarityGroupsResponse, SimilarityReviewFilter, SimilarityRevision } from "./types";

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

export function BurstsView({ groups, selectedGroup, task, startVisual, openGroup, closeGroup, openCapture, saveReview, editGrouping, saveGrouping, restoreGroupingRevision, cancelTask, changeGroupPage, changeGroupPageSize, reviewFilter, setReviewFilter, albumId, setAlbumId, openAlbumPhotos, openAlbumQuality }: {
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
  albumId: string;
  setAlbumId: (albumId: string) => void;
  openAlbumPhotos: (albumId: number) => void;
  openAlbumQuality: (albumId: number) => void;
}) {
  const [browseMode, setBrowseMode] = useState<CollectionScope>("all");
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [comparisonOrder, setComparisonOrder] = useState<"recommended" | "capture">("recommended");
  const [albumUndo, setAlbumUndo] = useState<SimilarityRevision | null>(null);
  const groupItems = groups?.items ?? [];
  const currentIndex = selectedGroup ? groupItems.findIndex((item) => item.id === selectedGroup.id) : -1;
  const nextPending = groupItems.find((item, index) => index > currentIndex && item.review_status === "pending")
    ?? groupItems.find((item, index) => index !== currentIndex && item.review_status === "pending");
  const statusLabels = { pending: "待选", picked: "已选定", skipped: "已排除" } as const;
  const tierLabels = { best: "技术最佳", alternative: "接近备选", candidate: "候选", weak: "明显技术弱项", unrated: "未评分" } as const;
  const completedCount = Math.max(0, (groups?.total_count ?? 0) - (groups?.pending_count ?? 0));
  const completionPercent = groups?.total_count ? Math.round(completedCount / groups.total_count * 100) : 0;
  const selectedAlbum = groups?.albums.find((album) => String(album.id) === albumId) ?? null;
  const comparisonItems = selectedGroup ? [...selectedGroup.items].sort((left, right) => (
    comparisonOrder === "capture"
      ? left.sequence_index - right.sequence_index
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
  }, [selectedGroup?.id]);
  return (
    <>
      <section className="structure-hero burst-hero">
        <div><span className="section-kicker">照片挑选</span><h2>相似照片分组</h2><button className="primary-action" onClick={startVisual} disabled={task?.status === "running"}><span>{task?.status === "running" ? "分析进行中" : "更新相似分组"}</span><b aria-hidden="true">→</b></button></div>
        <div className="structure-stat"><strong>{groups ? numberFormat.format(groups.pending_count) : "—"}</strong><span>组待选 / 共 {groups ? numberFormat.format(groups.total_count) : "—"} 组</span><small>已完成 {completionPercent}%</small></div>
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
          <div className="comparison-note comparison-context"><span>共 {selectedGroup.capture_count} 张 · 点击图片查看完整参数</span><div className="comparison-context-actions"><div className="burst-view-toggle" role="group" aria-label="组内照片排序"><button className={comparisonOrder === "recommended" ? "active" : ""} onClick={() => setComparisonOrder("recommended")}>推荐顺序</button><button className={comparisonOrder === "capture" ? "active" : ""} onClick={() => setComparisonOrder("capture")}>拍摄顺序</button></div><button className="toolbar-button" onClick={() => setEditingGroupId(selectedGroup.id)}>调整这一组</button></div></div>
          <div className="comparison-grid">
            {comparisonItems.map((item) => (
              <article className={`comparison-card ${item.auto_pick ? "auto-pick" : ""} ${item.user_pick ? "user-pick" : ""} ${item.user_reject ? "user-reject" : ""}`} key={item.capture_id} onClick={() => openCapture(item.capture_id, comparisonItems.map((member) => member.capture_id))}>
                <div className="photo-frame">
                  <img src={item.thumbnail_url} loading="lazy" alt={`${item.stem} 缩略图`} />
                  {item.similarity_rank && <span className="photo-rank">#{item.similarity_rank}</span>}
                  {item.auto_pick ? <span className="photo-flag">技术推荐</span> : null}
                  {item.user_pick ? <span className="photo-flag user">组内入选</span> : null}
                </div>
                <div className="photo-card-copy"><strong>{item.stem}</strong><span>{item.technical_score == null ? "尚未评分" : `技术分 ${Math.round(item.technical_score)}`} · {formatExposure(item.exposure_time)} · ISO {item.iso ?? "—"}</span><small className={`recommendation-tier ${item.recommendation_tier}`}>{tierLabels[item.recommendation_tier]}</small><small className="comparison-reason">{item.recommendation_reason}</small></div>
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
      ) : !albumId && browseMode === "albums" ? (
        <section className="panel album-selection-panel">
          <div className="panel-heading compact-list-heading"><div><h3>选择相册</h3></div><span className="batch-count">{groups?.albums.length ?? 0} 个相册包含相似组</span></div>
          <div className="similarity-album-grid">{(groups?.albums ?? []).map((album) => { const done = album.total_count - album.pending_count; const percent = album.total_count ? Math.round(done / album.total_count * 100) : 0; return <button key={album.id} onClick={() => setAlbumId(String(album.id))}><span><small>{album.category}</small><strong>{album.name}</strong></span><b><strong>{album.pending_count}</strong><small>待选</small></b><i><span style={{ width: `${percent}%` }} /></i><em>共 {album.total_count} 组 · 已完成 {percent}%</em></button>; })}</div>
          {!groups?.albums.length && <div className="empty-state">还没有可处理的相似组，请先更新相似分组。</div>}
        </section>
      ) : (<>
        {albumId && <AlbumWorkspaceHeader name={selectedAlbum?.name ?? "相册选片"} category={selectedAlbum?.category ?? "相册"} summary={`${groups?.pending_count ?? 0} 组待选 · 共 ${groups?.total_count ?? 0} 组`} current="bursts" back={() => { setBrowseMode("albums"); setAlbumId(""); }} openPhotos={() => openAlbumPhotos(Number(albumId))} openBursts={() => undefined} openQuality={() => openAlbumQuality(Number(albumId))} />}
        <section className="panel similarity-panel">
          {albumUndo && <div className="similarity-recovery-bar"><span>本相册最近一次人工分组仍可撤销</span><button className="toolbar-button" onClick={() => { if (window.confirm("撤销本相册最近一次人工分组调整？")) void restoreGroupingRevision(albumUndo.id, true); }}>撤销最近调整</button></div>}
          <div className="similarity-list-controls"><div className="burst-view-toggle" role="tablist" aria-label="选片进度筛选">{([['pending', '待选'], ['completed', '已完成'], ['adjusted', '人工调整'], ['all', '全部']] as const).map(([value, label]) => <button key={value} className={reviewFilter === value ? "active" : ""} onClick={() => setReviewFilter(value)}>{label}</button>)}</div><span className="batch-count">当前显示 {numberFormat.format(groups?.count ?? 0)} 组 · 点击进入对比</span></div>
          <div className="similarity-grid">
            {groupItems.map((group) => (
              <button className="similarity-card" key={group.id} onClick={() => openGroup(group.id)}>
                <span className="similarity-cover"><img src={group.thumbnail_url} loading="lazy" alt={`${group.event_name} 相似组封面`} /><b>{group.capture_count} 张</b><i className={`review-status-badge ${group.review_status}`}>{statusLabels[group.review_status]}</i></span>
                <span className="similarity-copy"><strong>{group.event_name}</strong><small>{group.recommended_stem ? `推荐 ${group.recommended_stem}` : "等待技术评分"}{group.average_score == null ? "" : ` · 均分 ${group.average_score}`}{group.pick_count ? ` · ${group.pick_count} 张入选` : ""}</small></span>
              </button>
            ))}
            {!groupItems.length && <div className="empty-state">{{ pending: "所有相似组都已处理完，可切换到“全部”回顾。", completed: "还没有完成选片的相似组。", adjusted: "当前没有生效中的人工分组调整。", all: "还没有相似分组，先运行相似分析。" }[reviewFilter]}</div>}
          </div>
          {groups && <Pagination count={groups.count} limit={groups.limit} offset={groups.offset} onChange={changeGroupPage} onLimitChange={changeGroupPageSize} />}
        </section>
      </>)}
    </>
  );
}
