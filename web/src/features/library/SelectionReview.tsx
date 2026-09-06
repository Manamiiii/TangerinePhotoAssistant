import { PhotoComparison, type ComparePhoto } from "../details/PhotoComparison";
import { useEffect, useRef, useState } from "react";
import { getJson } from "../../api";
import { ModalShell } from "../../components/ModalShell";
import { LibraryThumbnail } from "./LibraryThumbnail";

type SelectedCapture = { id: number; missing?: boolean; stem?: string; captured_at?: string | null; album_name?: string | null; jpeg_present?: number };

export function SelectionReview({ selected, remove, close }: {
  selected: Set<number>; remove: (id: number) => void; close: () => void;
}) {
  const [comparison, setComparison] = useState<ComparePhoto[]>([]);
  const [comparing, setComparing] = useState(false);
  const pair = comparison.filter((photo) => selected.has(photo.id));
  const showComparison = comparing && pair.length === 2;
  const compareButton = useRef<HTMLButtonElement>(null);
  const wasComparing = useRef(false);
  useEffect(() => {
    if (wasComparing.current && !showComparison) compareButton.current?.focus();
    wasComparing.current = showComparison;
  }, [showComparison]);
  const closeView = () => showComparison ? setComparing(false) : close();
  const [page, setPage] = useState(0);
  const [retry, setRetry] = useState(0);
  const ids = [...selected];
  const pages = Math.max(1, Math.ceil(ids.length / 40));
  const currentPage = Math.min(page, pages - 1);
  const visibleIds = ids.slice(currentPage * 40, (currentPage + 1) * 40);
  const key = visibleIds.join(",");
  const [result, setResult] = useState<{ key: string; items: SelectedCapture[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setResult(null); setError(null);
    if (!key) return () => controller.abort();
    const query = new URLSearchParams();
    key.split(",").forEach((id) => query.append("ids", id));
    void getJson<{ items: SelectedCapture[] }>(`/api/library/selection?${query}`, { signal: controller.signal, cache: "no-store" })
      .then((data) => { if (!controller.signal.aborted) setResult({ key, items: data.items }); })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [key, retry]);
  return <ModalShell title={showComparison ? "两张照片对比" : `已选照片 · ${selected.size} 张`} wide close={closeView}>
    {showComparison ? <PhotoComparison key={pair.map((photo) => photo.id).join(",")} photos={pair as [ComparePhoto, ComparePhoto]} back={() => setComparing(false)} /> : <div className="selection-review">
      <p>包含其他分页和筛选条件下已勾选的照片，按勾选顺序展示。移除只取消勾选，不修改照片。</p>
      <div className="selection-compare-actions"><span>对比候选 {pair.length} / 2</span>{pair.map((photo) => <button key={photo.id} aria-label={`移除对比 ${photo.stem ?? photo.id}`} onClick={() => setComparison(pair.filter((item) => item.id !== photo.id))}>{photo.stem ?? photo.id} ×</button>)}<button ref={compareButton} disabled={pair.length !== 2} onClick={() => setComparing(true)}>对比两张</button></div>
      {!ids.length ? <div className="empty-state">已清空选择。</div> : error ? <div className="empty-state" role="alert">清单读取失败：{error}<button onClick={() => setRetry((value) => value + 1)}>重试清单</button></div>
        : result?.key !== key ? <div className="empty-state" role="status">正在读取已选照片…</div>
        : <div className="selection-review-list">{result.items.map((item) => <article key={item.id}>
          {item.jpeg_present ? <LibraryThumbnail src={`/api/thumbnails/${item.id}?size=320`} alt={item.stem ?? `照片 ${item.id}`} /> : <span className="selection-review-unavailable">无预览</span>}
          <div><strong>{item.stem ?? `照片 ID ${item.id}`}</strong><small>{item.missing ? "索引记录已不存在" : item.album_name ?? "未归入相册"}</small><small>{item.captured_at?.slice(0, 10) ?? "日期未知"}{!item.missing && !item.jpeg_present ? " · 索引中无现存 JPG" : ""}</small></div>
          <div className="selection-review-actions"><button disabled={!item.jpeg_present || (!pair.some((photo) => photo.id === item.id) && pair.length >= 2)} aria-pressed={pair.some((photo) => photo.id === item.id)} onClick={() => setComparison(pair.some((photo) => photo.id === item.id) ? pair.filter((photo) => photo.id !== item.id) : [...pair, item])}>{pair.some((photo) => photo.id === item.id) ? "取消对比" : "加入对比"}</button><button aria-label={`取消选择 ${item.stem ?? item.id}`} onClick={() => { setComparison(pair.filter((photo) => photo.id !== item.id)); remove(item.id); }}>移除</button></div>
        </article>)}</div>}
      <footer><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>上一页</button><span>第 {currentPage + 1} / {pages} 页 · 共 {ids.length} 张</span><button disabled={currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)}>下一页</button><button onClick={close}>完成核对</button></footer>
    </div>}
  </ModalShell>;
}
