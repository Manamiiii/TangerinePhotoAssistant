import { useEffect, useState } from "react";
import { getJson } from "../../api";
import { VersionPanel } from "./VersionPanel";
import type { Task } from "../../components/TaskCard";
import type { DirectoryPickerResult, EditableSettings, SettingsStatus } from "./types";

type StorageField = ["library", "originals"] | ["library", "workspace"] | ["cache", "root"];

export function SettingsView({ status, task, save, firstRun = false, onDirtyChange }: {
  status: SettingsStatus | null;
  task: Task | null;
  save: (settings: EditableSettings) => Promise<SettingsStatus>;
  firstRun?: boolean;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [draft, setDraft] = useState<EditableSettings | null>(status?.configured ?? null);
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [guided, setGuided] = useState(firstRun);
  const [step, setStep] = useState(1);
  useEffect(() => setDraft(status?.configured ?? null), [status?.configured]);
  useEffect(() => { if (firstRun) setGuided(true); }, [firstRun]);
  const dirty = Boolean(draft && status?.configured && JSON.stringify(draft) !== JSON.stringify(status.configured));
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  useEffect(() => {
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [dirty]);
  if (!draft) return <div className="empty-state">正在读取配置…</div>;

  const update = <S extends keyof EditableSettings, K extends keyof EditableSettings[S]>(section: S, key: K, value: EditableSettings[S][K]) => setDraft((current) => current ? { ...current, [section]: { ...current[section], [key]: value } } : current);
  const submit = async () => {
    setSaving(true);
    setNotice(null);
    try {
      const result = await save(draft);
      setNotice(result.message ?? "配置已保存，重启应用后生效。");
    } finally {
      setSaving(false);
    }
  };
  const chooseDirectory = async ([section, key]: StorageField, title: string, current: string) => {
    setPicking(`${section}.${key}`);
    setNotice(null);
    try {
      const result = await getJson<DirectoryPickerResult>("/api/system/directory-picker", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial_path: current, title }),
      });
      if (!result.cancelled && result.path) update(section, key as never, result.path as never);
    } finally {
      setPicking(null);
    }
  };
  const busy = task?.status === "running" || task?.status === "paused";
  const pickerReady = status?.effective.features.directory_picker ?? false;
  const setupSteps: Array<[number, string]> = [[1, "存储位置"], [2, "可选能力"], [3, "确认安全边界"]];
  const pathInput = (field: StorageField, label: string, value: string, help: string) => {
    const [section, key] = field;
    const fieldId = `${section}.${key}`;
    return <label className="wide"><span>{label}</span><div className="settings-path-input"><input value={value} onChange={(event) => update(section, key as never, event.target.value as never)} /><button className="toolbar-button" type="button" disabled={!pickerReady || picking !== null} onClick={() => void chooseDirectory(field, `选择${label}`, value)}>{picking === fieldId ? "选择中…" : "选择目录"}</button></div><small>{help}{!pickerReady ? " 当前环境不支持原生选择器，也可以直接填写绝对路径。" : ""}</small></label>;
  };
  const storageFields = <div className="settings-form-grid">
    {pathInput(["library", "originals"], "照片目录", draft.library.originals, "必须是已存在目录。应用只读取照片，不会自动复制或迁移。")}
    {pathInput(["library", "workspace"], "工作目录", draft.library.workspace, "数据库、报告和用户选择保存在这里；修改路径不会移动旧数据。")}
    {pathInput(["cache", "root"], "缓存目录", draft.cache.root, "只保存可重建的缩略图和临时数据。")}
    <label><span>缓存上限 GB</span><input type="number" min="1" value={draft.cache.max_size_gb} onChange={(event) => update("cache", "max_size_gb", Number(event.target.value))} /></label><label><span>缩略图上限 GB</span><input type="number" min="1" value={draft.cache.thumbnail_max_size_gb} onChange={(event) => update("cache", "thumbnail_max_size_gb", Number(event.target.value))} /></label>
  </div>;

  if (guided) return <div className="settings-page setup-wizard">
    {status?.restart_required && <section className="settings-restart-banner"><strong>配置已保存，等待重启生效</strong><span>当前服务仍使用原配置；不会自动搬运照片或数据库。{status.backup_path ? ` 旧配置：${status.backup_path}` : ""}</span></section>}
    <section className="panel setup-wizard-shell">
      <div className="setup-wizard-heading"><div><span className="section-kicker">首次使用</span><h2>连接你的本地照片库</h2><p>只建立本地索引。设置过程中不会扫描、复制或修改照片。</p></div><button className="text-action" onClick={() => setGuided(false)}>打开完整设置</button></div>
      <nav className="setup-steps" aria-label="首次设置步骤">{setupSteps.map(([value, label]) => <button key={value} className={step === value ? "active" : step > value ? "complete" : ""} onClick={() => setStep(value)}><b>{step > value ? "✓" : value}</b><span>{label}</span></button>)}</nav>
      {step === 1 && <section className="setup-step"><div className="setup-step-intro"><h3>选择三个相互独立的位置</h3><p>照片目录保持只读；工作数据和可重建缓存与原片分开。</p></div>{storageFields}</section>}
      {step === 2 && <section className="setup-step"><div className="setup-step-intro"><h3>可选能力现在可以跳过</h3><p>没有 ExifTool 或本地模型也能浏览、评分和选片，稍后可以随时补充。</p></div><div className="setup-capability-grid"><article><span>基础元数据</span><strong>内置可用</strong><small>JPEG 常用 EXIF 与基本浏览</small></article><article><span>完整元数据</span><strong>{draft.tools.exiftool ? "已填写路径" : "暂不启用"}</strong><small>ExifTool 用于 RAW 与厂商扩展信息</small></article><article><span>本地模型</span><strong>{draft.models.vision_language_model && draft.models.python ? "已填写路径" : "暂不启用"}</strong><small>不配置也不会影响核心图库功能</small></article></div><div className="settings-form-grid setup-optional-fields"><label className="wide"><span>ExifTool 路径（可留空）</span><input value={draft.tools.exiftool} onChange={(event) => update("tools", "exiftool", event.target.value)} /></label><label className="wide"><span>模型 Python（可留空）</span><input value={draft.models.python} onChange={(event) => update("models", "python", event.target.value)} /></label><label className="wide"><span>本地模型目录（可留空）</span><input value={draft.models.vision_language_model} onChange={(event) => update("models", "vision_language_model", event.target.value)} /></label></div></section>}
      {step === 3 && <section className="setup-step"><div className="setup-step-intro"><h3>确认后保存配置</h3><p>路径将在重启应用后生效。首次扫描仍需由你在照片图库中手动启动。</p></div><div className="setup-summary"><span><b>照片目录</b>{draft.library.originals}</span><span><b>工作目录</b>{draft.library.workspace}</span><span><b>缓存目录</b>{draft.cache.root}</span></div><div className="setup-safety-list"><span>✓ 核心功能保持本地离线</span><span>✓ 原始照片保持只读</span><span>✓ 不移动、不删除、不写 XMP</span><span>✓ 不会自动启动模型分析</span></div></section>}
      <footer className="setup-wizard-actions"><span>{notice ?? (busy ? "后台任务运行或暂停期间不能保存配置。" : step === 3 ? "保存会先校验路径并备份当前配置。" : "所有选项稍后都能在应用设置中修改。")}</span><div>{step > 1 && <button className="toolbar-button" onClick={() => setStep((current) => current - 1)}>上一步</button>}{step < 3 ? <button className="toolbar-button primary" onClick={() => setStep((current) => current + 1)}>下一步</button> : <button className="toolbar-button primary" onClick={() => void submit()} disabled={saving || busy}>{saving ? "正在校验…" : "保存配置"}</button>}</div></footer>
    </section>
  </div>;

  return <div className="settings-page">
    <VersionPanel />
    {firstRun && <section className="setup-return-banner"><span>图库尚未完成首次索引。</span><button className="text-action" onClick={() => { setStep(1); setGuided(true); }}>返回首次设置向导</button></section>}
    {status?.restart_required && <section className="settings-restart-banner"><strong>配置已保存，等待重启生效</strong><span>当前服务仍使用原配置；不会自动搬运照片或数据库。{status.backup_path ? ` 旧配置：${status.backup_path}` : ""}</span></section>}
    <section className="panel settings-section"><div className="panel-heading"><div><span className="section-kicker">存储位置</span><h3>图库与应用数据</h3></div></div>{storageFields}<div className="effective-settings"><span>当前实际图库 <b>{status?.effective.library_root}</b></span><span>当前实际工作目录 <b>{status?.effective.workspace_root}</b></span><small>已迁移的数据库会优先使用其活动图库记录。要连接一套全新图库，建议同时选择新的工作目录。</small></div><div className="settings-folder-actions"><span>在资源管理器中打开当前实际目录</span><div>{([['library', '照片目录'], ['workspace', '工作目录'], ['cache', '缓存目录'], ['reports', '报告目录']] as const).map(([kind, label]) => <button key={kind} className="toolbar-button" type="button" onClick={() => void getJson(`/api/system/folders/${kind}/open`, { method: "POST" })}>{label}</button>)}</div></div></section>
    <section className="panel settings-section"><div className="panel-heading"><div><span className="section-kicker">分析参数</span><h3>元数据、RAW 与连拍</h3></div></div><div className="settings-form-grid"><label className="wide"><span>ExifTool 路径（可留空自动发现）</span><input value={draft.tools.exiftool} onChange={(event) => update("tools", "exiftool", event.target.value)} /></label><label className="wide"><span>RAW 扩展名</span><input value={draft.analysis.raw_extensions.join(", ")} onChange={(event) => update("analysis", "raw_extensions", event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} /><small>使用英文逗号分隔，例如 .raf, .dng, .cr3。</small></label><label><span>连拍间隔秒</span><input type="number" min="0.1" max="60" step="0.1" value={draft.analysis.burst_time_gap_seconds} onChange={(event) => update("analysis", "burst_time_gap_seconds", Number(event.target.value))} /></label><label><span>元数据批量大小</span><input type="number" min="1" max="1000" value={draft.analysis.metadata_batch_size} onChange={(event) => update("analysis", "metadata_batch_size", Number(event.target.value))} /></label><label><span>每日建议复核量</span><input type="number" min="5" max="200" value={draft.workflow.daily_review_budget} onChange={(event) => update("workflow", "daily_review_budget", Number(event.target.value))} /><small>首页只把这部分积压列为今日建议。</small></label></div></section>
    <section className="panel settings-section"><div className="panel-heading"><div><span className="section-kicker">只读衔接</span><h3>Lightroom Classic</h3></div></div><div className="settings-form-grid"><label className="wide"><span>Lightroom 目录所在文件夹</span><input value={draft.lightroom.catalog_root} onChange={(event) => update("lightroom", "catalog_root", event.target.value)} placeholder="例如 C:\\Users\\用户名\\Pictures\\Lightroom" /><small>用于发现 .lrcat、.lrcat-data 和目录锁；应用不会打开或写入目录数据库。</small></label><label className="wide"><span>Lightroom 目录备份文件夹</span><input value={draft.lightroom.catalog_backup_root} onChange={(event) => update("lightroom", "catalog_backup_root", event.target.value)} placeholder="建议位于不同磁盘" /><small>当前仅检查配置与目录是否存在，不会自动创建或复制备份。</small></label></div></section>
    <section className="panel settings-section"><div className="panel-heading"><div><span className="section-kicker">可选能力</span><h3>本地模型</h3></div></div><div className="settings-form-grid"><label className="wide"><span>模型 Python</span><input value={draft.models.python} onChange={(event) => update("models", "python", event.target.value)} placeholder="留空则关闭本地模型" /></label><label className="wide"><span>模型目录</span><input value={draft.models.vision_language_model} onChange={(event) => update("models", "vision_language_model", event.target.value)} placeholder="留空则关闭本地模型" /></label><label><span>量化方式</span><select value={draft.models.quantization} onChange={(event) => update("models", "quantization", event.target.value as "none" | "int8")}><option value="none">不量化</option><option value="int8">INT8</option></select></label><label><span>显存上限 GB</span><input type="number" min="1" value={draft.models.gpu_memory_limit_gb} onChange={(event) => update("models", "gpu_memory_limit_gb", Number(event.target.value))} /></label><label><span>最大输出 Tokens</span><input type="number" min="1" value={draft.models.max_new_tokens} onChange={(event) => update("models", "max_new_tokens", Number(event.target.value))} /></label><label><span>图像最长边</span><input type="number" min="512" max="2048" value={draft.models.image_max_edge} onChange={(event) => update("models", "image_max_edge", Number(event.target.value))} /></label></div></section>
    <section className="panel settings-section safety-settings"><div><span className="section-kicker">固定安全边界</span><h3>这些开关不会因设置编辑而放宽</h3><p>本地离线、图库只读、禁止移动删除、禁止写入原片元数据与 XMP。</p></div><div className="settings-actions"><span>{notice ?? (dirty ? "有尚未保存的修改。" : busy ? "后台任务运行或暂停期间不能保存配置。" : "保存时会备份旧配置，并在完整校验后原子替换。")}</span><button className="toolbar-button" onClick={() => setDraft(status?.configured ?? draft)} disabled={saving || !dirty}>撤销修改</button><button className="toolbar-button primary" onClick={() => void submit()} disabled={saving || busy || !dirty}>{saving ? "正在校验…" : dirty ? "保存配置" : "已保存"}</button></div></section>
  </div>;
}
