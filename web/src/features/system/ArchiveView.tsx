import { useState } from "react";
import { formatBytes, formatDate, numberFormat } from "../../formatters";

export type ArchiveStatus = {
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

export function ArchiveView({ archive, activeLibrary, createBaseline, createActiveBaseline, checkIntegrity }: {
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
