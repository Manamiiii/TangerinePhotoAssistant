import { useState } from "react";
import { formatBytes, numberFormat } from "../../formatters";

export type LightroomStatus = {
  capture_count: number;
  confirmed_events: number;
  event_count: number;
  rated_captures: number;
  user_picks: number;
  user_rejects: number;
};

export type LightroomManifest = {
  capture_count: number;
  rated_count: number;
  user_pick_count: number;
  user_reject_count: number;
  source_bytes: number;
  csv_url: string;
  json_url: string;
};

export type LightroomManifestScope = "picked" | "rated" | "album" | "all";

export function LightroomView({ status, manifest, capabilities, albums, generateManifest }: {
  status: LightroomStatus | null;
  manifest: LightroomManifest | null;
  capabilities: { library_root: string; workspace_root: string } | null;
  albums: Array<{ id: number; name: string }>;
  generateManifest: (scope: LightroomManifestScope, albumId?: number) => void;
}) {
  const [scope, setScope] = useState<LightroomManifestScope>("picked");
  const [albumId, setAlbumId] = useState("");
  return <>
    <section className="structure-hero lightroom-hero">
      <div><span className="section-kicker">Lightroom Classic</span><h2>后期准备清单</h2><p>按明确范围汇总路径、评级、选片和相册信息；只生成报告，不导入或写入照片。</p><div className="manifest-scope-controls"><label>清单范围<select value={scope} onChange={(event) => setScope(event.target.value as LightroomManifestScope)}><option value="picked">仅人工入选</option><option value="rated">已有评级</option><option value="album">指定相册</option><option value="all">全部照片及状态</option></select></label>{scope === "album" && <label>相册<select value={albumId} onChange={(event) => setAlbumId(event.target.value)}><option value="">选择相册</option>{albums.map((album) => <option key={album.id} value={album.id}>{album.name}</option>)}</select></label>}<button className="primary-action" disabled={scope === "album" && !albumId} onClick={() => generateManifest(scope, albumId ? Number(albumId) : undefined)}><span>生成准备清单</span><b>→</b></button></div></div>
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
  </>;
}
