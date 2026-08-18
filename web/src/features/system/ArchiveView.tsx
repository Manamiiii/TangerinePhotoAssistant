import { useState } from "react";
import { getJson } from "../../api";
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
type PortableStatus = { download_url?: string; size_bytes?: number; valid?: boolean; matched_captures?: number; missing_captures?: number; confirmation?: string; restored?: boolean };

export function ArchiveView({ archive, activeLibrary, createBaseline, createActiveBaseline, checkIntegrity }: {
  archive: ArchiveStatus | null;
  activeLibrary: ArchiveStatus | null;
  createBaseline: () => void;
  createActiveBaseline: () => void;
  checkIntegrity: (scope: "archive" | "active") => Promise<void>;
}) {
  const [checking, setChecking] = useState<"archive" | "active" | null>(null);
  const [portableBackup, setPortableBackup] = useState<Record<string, unknown> | null>(null);
  const [portableStatus, setPortableStatus] = useState<PortableStatus | null>(null);
  const [portableError, setPortableError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [portableBusy, setPortableBusy] = useState(false);
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
  const exportHumanData = async () => {
    setPortableBusy(true);
    try { setPortableError(null); setPortableStatus(await getJson<PortableStatus>("/api/human-data/export", { method: "POST" })); }
    catch (reason) { setPortableError((reason as Error).message); }
    finally { setPortableBusy(false); }
  };
  const selectBackup = async (file: File | undefined) => {
    if (!file) return;
    setPortableBusy(true);
    try {
      const backup = JSON.parse(await file.text()) as Record<string, unknown>;
      setPortableBackup(backup);
      setPortableError(null); setPortableStatus(await getJson<PortableStatus>("/api/human-data/restore/preflight", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(backup) }));
      setConfirmation("");
    } catch (reason) { setPortableError((reason as Error).message); setPortableStatus(null); } finally { setPortableBusy(false); }
  };
  const restoreHumanData = async () => {
    if (!portableBackup) return;
    setPortableBusy(true);
    try { setPortableError(null); setPortableStatus(await getJson<PortableStatus>("/api/human-data/restore", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ backup: portableBackup, confirmation }) })); }
    catch (reason) { setPortableError((reason as Error).message); }
    finally { setPortableBusy(false); }
  };
  return <>
    <section className="compact-summary"><div><span className="section-kicker">系统维护</span><h2>图库完整性</h2><p>需要时手动核对磁盘文件；日常浏览只读取上次结果，不扫描照片目录。</p></div></section>
    <section className="statistics-grid">
      {baselineCard("历史存档", archive, createBaseline, "archive")}
      {baselineCard("活动图库", activeLibrary, createActiveBaseline, "active")}
    </section>
    <section className="integrity-guidance"><strong>适合什么时候检查</strong><span>更换硬盘、恢复备份、手动整理目录、异常断电或每隔一至三个月例行检查时使用。检查只报告差异，不会修改或修复照片。</span></section>
    <section className="panel portable-data-panel"><div className="panel-heading"><div><span className="section-kicker">个人数据保护</span><h3>人工数据备份与恢复</h3></div><button className="toolbar-button primary" disabled={portableBusy} onClick={() => void exportHumanData()}>{portableBusy ? "处理中" : "导出人工数据"}</button></div><p>只包含评分、入选、备注、人工/导入标签、当前分组调整、修图方案和设备配置；不包含照片、绝对路径、GPS、缩略图或模型结果。</p>
      {portableStatus?.download_url && <div className="portable-result"><span>备份已生成 · {formatBytes(portableStatus.size_bytes ?? 0)}</span><a href={portableStatus.download_url} download>下载 JSON</a></div>}
      <div className="portable-restore"><label className="toolbar-button">选择备份文件<input type="file" accept="application/json,.json" onChange={(event) => void selectBackup(event.target.files?.[0])} /></label>{portableStatus?.valid && <><span>匹配 {portableStatus.matched_captures} 个拍摄单元 · 缺少 {portableStatus.missing_captures} 个</span><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={portableStatus.confirmation} /><button className="toolbar-button" disabled={portableBusy || confirmation !== portableStatus.confirmation} onClick={() => void restoreHumanData()}>恢复人工数据</button></>}{portableStatus?.restored && <strong>恢复完成，操作前数据库备份已保留。</strong>}</div>
      {portableError && <div className="portable-error" role="alert">{portableError}</div>}
    </section>
  </>;
}
