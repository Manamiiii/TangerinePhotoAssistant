import { numberFormat } from "../formatters";

export function Pagination({ count, limit, offset, onChange, onLimitChange }: {
  count: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
}) {
  const pageCount = Math.max(1, Math.ceil(count / limit));
  const currentPage = Math.min(pageCount, Math.floor(offset / limit) + 1);
  const goToPage = (page: number) => onChange(
    (Math.max(1, Math.min(pageCount, page)) - 1) * limit
  );
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

export function AlbumWorkspaceHeader({ name, category, summary, current, back, openPhotos, openBursts, openQuality }: {
  name: string;
  category: string;
  summary: string;
  current: "library" | "bursts" | "analysis";
  back: () => void;
  openPhotos: () => void;
  openBursts: () => void;
  openQuality: () => void;
}) {
  const destinations = [
    ["library", "相册照片", openPhotos],
    ["bursts", "相似组选片", openBursts],
    ["analysis", "质量结果", openQuality],
  ] as const;
  return <section className="album-workspace-header">
    <button className="album-back" onClick={back}>← 返回相册列表</button>
    <div className="album-workspace-title"><span>{category}</span><h2>{name}</h2><small>{summary}</small></div>
    <nav aria-label="在当前相册内切换功能" title="保持当前相册范围，切换照片、相似组选片和质量结果">{destinations.map(([value, label, open]) => <button key={value} aria-current={current === value ? "page" : undefined} className={current === value ? "active" : ""} onClick={open}>{label}</button>)}</nav>
  </section>;
}
