import { useState } from "react";
import { formatBytes, numberFormat } from "../../formatters";

export type LightroomStatus = {
  capture_count: number;
  confirmed_events: number;
  event_count: number;
  rated_captures: number;
  user_picks: number;
  user_rejects: number;
  preflight: {
    status: "not_configured" | "missing" | "no_catalog" | "catalog_open" | "ready_for_review";
    message: string;
    catalog_root: string;
    catalog_root_exists: boolean;
    catalogs: Array<{ name: string; path: string; size_bytes: number; locked: boolean; data_companion: boolean }>;
    catalog_count: number;
    locked_count: number;
    backup_root: string;
    backup_root_exists: boolean;
    xmp_write_enabled: false;
    catalog_direct_write_supported: false;
    notes: string[];
  };
};

export type LightroomManifest = {
  capture_count: number;
  rated_count: number;
  user_pick_count: number;
  user_reject_count: number;
  source_bytes: number;
  raw_sidecar_candidates: number;
  existing_xmp_count: number;
  conflict_review_count: number;
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
      <article><span>选片入选</span><strong>{status ? numberFormat.format(status.user_picks) : "—"}</strong><small>人工结论，对应准备清单 pick 字段</small></article>
      <article><span>选片排除</span><strong>{status ? numberFormat.format(status.user_rejects) : "—"}</strong><small>人工结论，只标记，不删除</small></article>
    </section>
    <section className="lightroom-grid">
      <section className="panel safety-panel"><div className="panel-heading"><div><span className="section-kicker">只读预检</span><h3>{status?.preflight.message ?? "正在检查 Lightroom 配置"}</h3></div><span className={`lightroom-preflight-badge ${status?.preflight.status ?? "not_configured"}`}>{status?.preflight.status === "ready_for_review" ? "可生成计划" : status?.preflight.status === "catalog_open" ? "目录使用中" : "待配置"}</span></div><div className="safety-list"><div><b>{status?.preflight.catalog_count ? "✓" : "·"}</b><span><strong>目录文件</strong><small>{status?.preflight.catalog_count ? `${status.preflight.catalog_count} 个 .lrcat · ${status.preflight.catalogs.map((item) => item.name).join("、")}` : status?.preflight.catalog_root || "在应用设置中填写目录文件夹"}</small></span></div><div><b>{status?.preflight.backup_root_exists ? "✓" : "·"}</b><span><strong>目录备份位置</strong><small>{status?.preflight.backup_root || "尚未配置；当前也不会自动创建备份"}</small></span></div><div><b>✓</b><span><strong>目录数据库保持只读</strong><small>不会打开或改写 .lrcat；检测到 .lock 时只提示，不删除锁文件</small></span></div><div><b>✓</b><span><strong>照片与 XMP 写入关闭</strong><small>{capabilities?.library_root ?? "当前配置的照片目录"} 不会被移动、改名或改写</small></span></div></div></section>
      <section className="panel manifest-panel"><div className="panel-heading"><div><span className="section-kicker">最近生成</span><h3>Lightroom准备文件</h3></div></div>{manifest ? <div className="manifest-result"><strong>{numberFormat.format(manifest.capture_count)} 个拍摄单元</strong><span>{numberFormat.format(manifest.rated_count)} 个已有评级 · {formatBytes(manifest.source_bytes)} 原始文件索引</span><span>{manifest.raw_sidecar_candidates} 个 RAW sidecar 候选 · {manifest.existing_xmp_count} 个已有 XMP · {manifest.conflict_review_count} 个需冲突复核</span><a href={manifest.csv_url}>下载CSV清单</a><a href={manifest.json_url}>下载完整JSON</a><small>清单按字段标注评级、旗标和关键词计划；下载的仍是报告，不是照片或 XMP。</small></div> : <div className="empty-state">尚未在本次启动中生成清单。</div>}</section>
    </section>
  </>;
}
