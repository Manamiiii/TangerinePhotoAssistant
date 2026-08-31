import { numberFormat } from "../formatters";
import { useEffect, useState } from "react";

export function Pagination({ count, limit, offset, onChange, onLimitChange }: {
  count: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(count / limit));
  const currentPage = Math.min(pageCount, Math.floor(offset / limit) + 1);
  const [pageDraft, setPageDraft] = useState(String(currentPage));
  useEffect(() => setPageDraft(String(currentPage)), [currentPage]);
  const goToPage = (page: number) => onChange(
    (Math.max(1, Math.min(pageCount, Math.trunc(page))) - 1) * limit
  );
  const commitPage = () => {
    const value = Number(pageDraft);
    if (pageDraft.trim() && Number.isFinite(value)) goToPage(value);
    setPageDraft(String(pageDraft.trim() && Number.isFinite(value) ? Math.max(1, Math.min(pageCount, Math.trunc(value))) : currentPage));
  };
  return <div className="pagination-controls" aria-label="分页">
    <label>每页<select value={limit} onChange={(event) => onLimitChange(Number(event.target.value))}>
      {[20, 40, 80, 120, 200].map((size) => <option key={size} value={size}>{size}</option>)}
    </select></label>
    <div className="pagination-buttons">
      <button disabled={currentPage === 1} onClick={() => goToPage(1)} aria-label="第一页">«</button>
      <button disabled={currentPage === 1} onClick={() => goToPage(currentPage - 1)} aria-label="上一页">‹</button>
      <label>第<input type="text" inputMode="numeric" aria-label="跳转页码" title="输入页码，按回车跳转" value={pageDraft} onChange={(event) => setPageDraft(event.target.value)} onBlur={commitPage} onKeyDown={(event) => { if (event.key === "Enter") commitPage(); if (event.key === "Escape") setPageDraft(String(currentPage)); }} />页</label>
      <span>/ {numberFormat.format(pageCount)} 页</span>
      <button disabled={currentPage === pageCount} onClick={() => goToPage(currentPage + 1)} aria-label="下一页">›</button>
      <button disabled={currentPage === pageCount} onClick={() => goToPage(pageCount)} aria-label="最后一页">»</button>
    </div>
    <span>共 {numberFormat.format(count)} 条</span>
  </div>;
}

export function CollectionScopeTabs({ scope, setScope, allLabel = "全部" }: {
  scope: "all" | "albums";
  setScope: (scope: "all" | "albums") => void;
  allLabel?: string;
}) {
  return <div className="collection-scope-tabs" role="tablist" aria-label="浏览范围">
    <button role="tab" aria-selected={scope === "all"} className={scope === "all" ? "active" : ""} onClick={() => setScope("all")}>{allLabel}</button>
    <button role="tab" aria-selected={scope === "albums"} className={scope === "albums" ? "active" : ""} onClick={() => setScope("albums")}>相册</button>
  </div>;
}

export type AlbumWorkspaceCounts = {
  photos: number;
  similarityGroups: number;
  qualityResults: number;
};

export function AlbumWorkspaceHeader({ name, category, summary, counts, current, back, openPhotos, openBursts, openQuality }: {
  name: string;
  category: string;
  summary: string;
  counts: AlbumWorkspaceCounts;
  current: "library" | "bursts" | "analysis";
  back: () => void;
  openPhotos: () => void;
  openBursts: () => void;
  openQuality: () => void;
}) {
  const destinations = [
    ["library", "相册照片", counts.photos, openPhotos],
    ["bursts", "相似选片", counts.similarityGroups, openBursts],
    ["analysis", "质量结果", counts.qualityResults, openQuality],
  ] as const;
  return <section className="album-workspace-header">
    <button className="album-back" onClick={back}>← 返回相册列表</button>
    <div className="album-workspace-title"><span>{category}</span><h2>{name}</h2><small>{summary}</small></div>
    <nav aria-label="当前相册视图">{destinations.map(([value, label, count, open]) => {
      const unavailable = count === 0 && current !== value;
      return <button key={value} aria-current={current === value ? "page" : undefined} className={current === value ? "active" : ""} disabled={unavailable} title={unavailable ? `当前相册暂无${label}` : undefined} onClick={open}><span>{label}</span><b>{numberFormat.format(count)}</b></button>;
    })}</nav>
  </section>;
}
