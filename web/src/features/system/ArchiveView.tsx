import { useEffect, useState } from "react";
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
type DiagnosticStatus = { download_url: string; size_bytes: number; integrity: string };
type IntegrityPage = {
  check_id: number | null;
  count: number;
  limit: number;
  offset: number;
  items: Array<{ relative_path: string; status: string; workflow_status: string; workflow_age_days: number | null }>;
};
type TaskIncident = {
  task_kind: string;
  task_label: string;
  error_code: string;
  message: string;
  workflow_status: string;
  workflow_age_days: number | null;
  occurrence_count: number;
};
type TaskIncidentPage = { count: number; items: TaskIncident[] };

export function ArchiveView({ archive, activeLibrary, createBaseline, createActiveBaseline, checkIntegrity, saveInvestigation }: {
  archive: ArchiveStatus | null;
  activeLibrary: ArchiveStatus | null;
  createBaseline: () => void;
  createActiveBaseline: () => void;
  checkIntegrity: (scope: "archive" | "active") => Promise<void>;
  saveInvestigation: (scope: "archive" | "active", relativePath: string, status: "pending" | "confirmed" | "ignored" | "snoozed" | "resolved") => Promise<void>;
}) {
  const [checking, setChecking] = useState<"archive" | "active" | null>(null);
  const [portableBackup, setPortableBackup] = useState<Record<string, unknown> | null>(null);
  const [portableStatus, setPortableStatus] = useState<PortableStatus | null>(null);
  const [portableError, setPortableError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [portableBusy, setPortableBusy] = useState(false);
  const [diagnosticStatus, setDiagnosticStatus] = useState<DiagnosticStatus | null>(null);
  const [diagnosticError, setDiagnosticError] = useState<string | null>(null);
  const [diagnosticBusy, setDiagnosticBusy] = useState(false);
  const [differenceScope, setDifferenceScope] = useState<"archive" | "active" | null>(null);
  const [differences, setDifferences] = useState<IntegrityPage | null>(null);
  const [differenceWorkflow, setDifferenceWorkflow] = useState("open");
  const [savingDifference, setSavingDifference] = useState<string | null>(null);
  const [taskIncidents, setTaskIncidents] = useState<TaskIncidentPage | null>(null);
  const [taskWorkflow, setTaskWorkflow] = useState("open");
  const [savingTask, setSavingTask] = useState<string | null>(null);
  const [taskIncidentError, setTaskIncidentError] = useState<string | null>(null);
  const loadTaskIncidents = async (workflow = taskWorkflow) => {
    try {
      setTaskIncidentError(null);
      setTaskIncidents(await getJson<TaskIncidentPage>(`/api/task-incidents?workflow=${workflow}`));
    } catch (reason) { setTaskIncidentError((reason as Error).message); }
  };
  useEffect(() => { void loadTaskIncidents("open"); }, []);
  const updateTaskIncident = async (taskKind: string, status: "pending" | "confirmed" | "ignored" | "snoozed") => {
    setSavingTask(taskKind);
    try {
      setTaskIncidentError(null);
      await getJson(`/api/task-incidents/${taskKind}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, snooze_days: status === "snoozed" ? 7 : null }),
      });
      await loadTaskIncidents();
    } catch (reason) { setTaskIncidentError((reason as Error).message); }
    finally { setSavingTask(null); }
  };
  const loadDifferences = async (scope: "archive" | "active", offset = 0, workflow = differenceWorkflow) => {
    setDifferenceScope(scope);
    setDifferences(await getJson<IntegrityPage>(`/api/integrity/differences/${scope}?limit=50&offset=${offset}&workflow=${workflow}`));
  };
  const updateDifference = async (relativePath: string, status: "pending" | "confirmed" | "ignored" | "snoozed" | "resolved") => {
    if (!differenceScope) return;
    setSavingDifference(relativePath);
    try {
      await saveInvestigation(differenceScope, relativePath, status);
      await loadDifferences(differenceScope, differences?.offset ?? 0);
    } catch {
      // The application-level error banner keeps the API message visible.
    } finally { setSavingDifference(null); }
  };
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
        {!!status.comparison?.samples.length && <><div className="integrity-samples">{status.comparison.samples.slice(0, 8).map((sample) => <div key={`${sample.status}-${sample.relative_path}`}><span>{sample.status}</span><strong>{sample.relative_path}</strong></div>)}</div><button className="toolbar-button" onClick={() => void loadDifferences(scope)}>调查差异</button></>}
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
  const exportDiagnostics = async () => {
    setDiagnosticBusy(true);
    try {
      setDiagnosticError(null);
      setDiagnosticStatus(await getJson<DiagnosticStatus>("/api/diagnostics/export", { method: "POST" }));
    } catch (reason) { setDiagnosticError((reason as Error).message); }
    finally { setDiagnosticBusy(false); }
  };
  return <>
    <section className="compact-summary"><div><span className="section-kicker">系统维护</span><h2>图库完整性</h2><p>需要时手动核对磁盘文件；日常浏览只读取上次结果，不扫描照片目录。</p></div></section>
    <section className="panel archive-panel task-incident-panel">
      <div className="panel-heading"><div><span className="section-kicker">运行恢复</span><h3>后台任务异常</h3></div><div className="integrity-investigation-toolbar"><select aria-label="任务异常状态" value={taskWorkflow} onChange={(event) => { const workflow = event.target.value; setTaskWorkflow(workflow); void loadTaskIncidents(workflow); }}><option value="open">当前待处理</option><option value="new">新发现</option><option value="reappeared">重新出现</option><option value="snoozed">稍后处理</option><option value="confirmed">已核对</option><option value="ignored">已忽略</option><option value="resolved">已恢复</option><option value="all">全部状态</option></select></div></div>
      <p className="task-incident-intro">这里只汇总需要处理的失败任务；相同故障会合并，同类任务成功后会自动标记为已恢复。</p>
      {!!taskIncidents?.items.length && <div className="integrity-investigation-list task-incident-list">{taskIncidents.items.map((item) => { const isOpen = ["new", "reappeared", "pending"].includes(item.workflow_status); return <article key={item.task_kind}><span className="integrity-kind">{item.task_label}</span><strong>{item.message}</strong><small>{({ new: "新发现", reappeared: "重新出现", pending: "待处理", confirmed: "已核对", ignored: "已忽略", snoozed: "稍后处理", resolved: "已恢复" } as Record<string, string>)[item.workflow_status] ?? item.workflow_status}{item.workflow_age_days ? ` · ${item.workflow_age_days} 天` : " · 今天"}{item.occurrence_count > 1 ? ` · 第 ${item.occurrence_count} 次进入队列` : ""} · {item.error_code}</small><div>{isOpen ? <><button disabled={savingTask === item.task_kind} onClick={() => void updateTaskIncident(item.task_kind, "confirmed")}>已核对</button><button disabled={savingTask === item.task_kind} onClick={() => void updateTaskIncident(item.task_kind, "snoozed")}>7天后</button><button disabled={savingTask === item.task_kind} onClick={() => void updateTaskIncident(item.task_kind, "ignored")}>忽略</button></> : <button disabled={savingTask === item.task_kind} onClick={() => void updateTaskIncident(item.task_kind, "pending")}>重新打开</button>}</div></article>; })}</div>}
      {taskIncidents && !taskIncidents.items.length && <div className="empty-state">当前状态下没有后台任务异常。</div>}
      {taskIncidentError && <div className="portable-error" role="alert">{taskIncidentError}</div>}
    </section>
    <section className="statistics-grid">
      {baselineCard("历史存档", archive, createBaseline, "archive")}
      {baselineCard("活动图库", activeLibrary, createActiveBaseline, "active")}
    </section>
    {differenceScope && differences && <section className="panel archive-panel">
      <div className="panel-heading"><div><span className="section-kicker">完整差异清单</span><h3>{differenceScope === "archive" ? "历史存档" : "活动图库"} · {numberFormat.format(differences.count)} 项</h3></div><div className="integrity-investigation-toolbar"><select aria-label="调查状态" value={differenceWorkflow} onChange={(event) => { const workflow = event.target.value; setDifferenceWorkflow(workflow); void loadDifferences(differenceScope, 0, workflow); }}><option value="open">当前待调查</option><option value="new">新发现</option><option value="reappeared">重新出现</option><option value="snoozed">稍后处理</option><option value="confirmed">已核对</option><option value="ignored">已忽略</option><option value="resolved">已解决</option><option value="all">全部状态</option></select><button className="toolbar-button" onClick={() => { setDifferenceScope(null); setDifferences(null); }}>关闭</button></div></div>
      <div className="integrity-investigation-list">{differences.items.map((item) => { const isOpen = ["new", "reappeared", "pending"].includes(item.workflow_status); return <article key={`${item.status}-${item.relative_path}`}><span className="integrity-kind">{({ missing: "缺失", changed: "变化", new: "新增", unreadable: "不可读" } as Record<string, string>)[item.status] ?? item.status}</span><strong title={item.relative_path}>{item.relative_path}</strong><small>{({ new: "新发现", reappeared: "重新出现", pending: "待调查", confirmed: "已核对", ignored: "已忽略", snoozed: "稍后处理", resolved: "已解决" } as Record<string, string>)[item.workflow_status] ?? item.workflow_status}{item.workflow_age_days ? ` · 已积压 ${item.workflow_age_days} 天` : " · 今天发现"}</small><div>{isOpen ? <><button disabled={savingDifference === item.relative_path} onClick={() => void updateDifference(item.relative_path, "confirmed")}>已核对</button><button disabled={savingDifference === item.relative_path} onClick={() => void updateDifference(item.relative_path, "snoozed")}>7天后</button><button disabled={savingDifference === item.relative_path} onClick={() => void updateDifference(item.relative_path, "ignored")}>忽略</button></> : <button disabled={savingDifference === item.relative_path} onClick={() => void updateDifference(item.relative_path, "pending")}>重新打开</button>}</div></article>; })}</div>
      {!differences.items.length && <div className="empty-state">当前调查状态下没有差异。</div>}
      {differences.count > 0 && <div className="pagination-actions"><button className="toolbar-button" disabled={differences.offset === 0} onClick={() => void loadDifferences(differenceScope, Math.max(0, differences.offset - differences.limit))}>上一页</button><span>{differences.offset + 1}–{Math.min(differences.count, differences.offset + differences.items.length)} / {differences.count}</span><button className="toolbar-button" disabled={differences.offset + differences.limit >= differences.count} onClick={() => void loadDifferences(differenceScope, differences.offset + differences.limit)}>下一页</button></div>}
    </section>}
    <section className="integrity-guidance"><strong>适合什么时候检查</strong><span>更换硬盘、恢复备份、手动整理目录、异常断电或每隔一至三个月例行检查时使用。检查只报告差异，不会修改或修复照片。</span></section>
    <section className="panel portable-data-panel"><div className="panel-heading"><div><span className="section-kicker">个人数据保护</span><h3>人工数据备份与恢复</h3></div><button className="toolbar-button primary" disabled={portableBusy} onClick={() => void exportHumanData()}>{portableBusy ? "处理中" : "导出人工数据"}</button></div><p>只包含评分、入选、备注、人工/导入标签、当前分组调整、修图方案和设备配置；不包含照片、绝对路径、GPS、缩略图或模型结果。</p>
      {portableStatus?.download_url && <div className="portable-result"><span>备份已生成 · {formatBytes(portableStatus.size_bytes ?? 0)}</span><a href={portableStatus.download_url} download>下载 JSON</a></div>}
      <div className="portable-restore"><label className="toolbar-button">选择备份文件<input type="file" accept="application/json,.json" onChange={(event) => void selectBackup(event.target.files?.[0])} /></label>{portableStatus?.valid && <><span>匹配 {portableStatus.matched_captures} 个拍摄单元 · 缺少 {portableStatus.missing_captures} 个</span><input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={portableStatus.confirmation} /><button className="toolbar-button" disabled={portableBusy || confirmation !== portableStatus.confirmation} onClick={() => void restoreHumanData()}>恢复人工数据</button></>}{portableStatus?.restored && <strong>恢复完成，操作前数据库备份已保留。</strong>}</div>
      {portableError && <div className="portable-error" role="alert">{portableError}</div>}
    </section>
    <section className="panel portable-data-panel"><div className="panel-heading"><div><span className="section-kicker">故障排查</span><h3>脱敏诊断包</h3></div><button className="toolbar-button" disabled={diagnosticBusy} onClick={() => void exportDiagnostics()}>{diagnosticBusy ? "正在生成" : "生成诊断包"}</button></div><p>仅按白名单汇总版本、运行能力、数据库完整性、数据量和任务状态；不读取或打包照片，不包含文件名、路径、GPS、设备序列号、备注、标签文字、模型提示词或结果正文。</p>
      {diagnosticStatus && <div className="portable-result"><span>诊断包已生成 · {formatBytes(diagnosticStatus.size_bytes)} · 数据库 {diagnosticStatus.integrity === "ok" ? "正常" : diagnosticStatus.integrity}</span><a href={diagnosticStatus.download_url} download>下载 ZIP</a></div>}
      {diagnosticError && <div className="portable-error" role="alert">{diagnosticError}</div>}
    </section>
  </>;
}
