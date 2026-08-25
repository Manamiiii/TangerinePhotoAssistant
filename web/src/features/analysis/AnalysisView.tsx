import { useEffect, useState } from "react";
import { getJson } from "../../api";
import { ModalShell } from "../../components/ModalShell";
import { AlbumWorkspaceHeader, CollectionScopeTabs, Pagination, type AlbumWorkspaceCounts } from "../../components/Navigation";
import { TaskCard, type Task } from "../../components/TaskCard";
import { formatDate, formatDuration, formatFileSize, numberFormat, technicalAdvice } from "../../formatters";
import type { AiPreflight, AiResultsResponse, AnalysisOverview, GpuStatus, QualityItem, QualityResponse, QualityReviewFilter, ReviewPayload } from "./types";

type CollectionScope = "all" | "albums";

function isAnalysisTask(task: Task | null) {
  if (!task || task.status === "idle") return false;
  const stage = task.stage.toLocaleLowerCase();
  return stage === "quality" || stage.startsWith("detail-") || stage.startsWith("ai-") || /技术质量|详情数据|扩展拍摄信息|直方图|模型任务|本地模型|Qwen/.test(task.message);
}

function modelAdvice(result: QualityItem["ai_result"]) {
  const shooting = result?.shooting_advice?.[0];
  if (shooting) return [shooting.suggestion, shooting.reason].filter(Boolean).join("：");
  const lightroom = result?.lightroom_suggestions?.[0];
  if (lightroom) return [lightroom.adjustment, lightroom.direction, lightroom.reason].filter(Boolean).join(" · ");
  return "打开详情查看完整模型分析。";
}

export function AnalysisView({ analysis, preflight, quality, qualityFilter, qualitySearch, setQualityFilter, setQualitySearch, qualityAlbumId, setQualityAlbumId, albumWorkspaceCounts, openAlbumPhotos, openAlbumBursts, task, startQuality, startDetailBackfill, resumeDetailBackfill, startAi, syncAnalysisSubjectTags, clearAnalysisSubjectTags, saveReview, cancelTask, pauseTask, resumeAi, retryAiFailures, openCapture, changeQualityPage, changeQualityPageSize }: {
  analysis: AnalysisOverview | null;
  preflight: AiPreflight | null;
  quality: QualityResponse | null;
  qualityFilter: QualityReviewFilter;
  qualitySearch: string;
  setQualityFilter: (filter: QualityReviewFilter) => void;
  setQualitySearch: (search: string) => void;
  qualityAlbumId: string;
  setQualityAlbumId: (albumId: string) => void;
  albumWorkspaceCounts: AlbumWorkspaceCounts;
  openAlbumPhotos: (albumId: number) => void;
  openAlbumBursts: (albumId: number) => void;
  task: Task | null;
  startQuality: () => void;
  startDetailBackfill: () => void;
  resumeDetailBackfill: () => void;
  startAi: (mode: "benchmark" | "recommended", limit: number) => void;
  syncAnalysisSubjectTags: () => void;
  clearAnalysisSubjectTags: () => void;
  saveReview: (captureId: number, review: ReviewPayload) => void;
  cancelTask: () => void;
  pauseTask: () => void;
  resumeAi: (runId: number) => void;
  retryAiFailures: (runId: number) => void;
  openCapture: (captureId: number, context?: number[]) => void;
  changeQualityPage: (offset: number) => void;
  changeQualityPageSize: (limit: number) => void;
}) {
  const summary = analysis?.quality;
  const ai = analysis?.ai;
  const running = task?.status === "running" || task?.status === "paused";
  const [batchSize, setBatchSize] = useState(100);
  const [resultOffset, setResultOffset] = useState(0);
  const [resultLimit, setResultLimit] = useState(40);
  const [resultVersion, setResultVersion] = useState("all");
  const [resultVerdict, setResultVerdict] = useState("all");
  const [resultAudit, setResultAudit] = useState("risk");
  const [resultPage, setResultPage] = useState<AiResultsResponse | null>(null);
  const [gpu, setGpu] = useState<GpuStatus | null>(null);
  const [healthHelpOpen, setHealthHelpOpen] = useState(false);
  const [analysisTab, setAnalysisTab] = useState<"quality" | "model" | "history">("quality");
  const [qualityBrowseMode, setQualityBrowseMode] = useState<CollectionScope>("all");
  const selectedQualityAlbum = quality?.albums.find((album) => String(album.id) === qualityAlbumId) ?? null;
  useEffect(() => {
    if (qualityAlbumId) setAnalysisTab("quality");
  }, [qualityAlbumId]);
  const estimatedBatchSeconds = ai?.latest_run?.average_seconds_per_photo
    ? ai.latest_run.average_seconds_per_photo * batchSize
    : null;
  useEffect(() => {
    let active = true;
    const parameters = new URLSearchParams({ limit: String(resultLimit), offset: String(resultOffset) });
    if (resultVersion !== "all") parameters.set("prompt_version", resultVersion);
    if (resultVerdict !== "all") parameters.set("verdict", resultVerdict);
    if (resultAudit !== "all") parameters.set("audit", resultAudit);
    getJson<AiResultsResponse>(`/api/ai/results?${parameters.toString()}`)
      .then((page) => { if (active) setResultPage(page); })
      .catch(() => { if (active) setResultPage(null); });
    return () => { active = false; };
  }, [resultLimit, resultOffset, resultVersion, resultVerdict, resultAudit, ai?.completed_analysis_count]);
  useEffect(() => {
    let active = true;
    const refresh = () => getJson<GpuStatus>("/api/system/gpu")
      .then((status) => { if (active) setGpu(status); })
      .catch(() => { if (active) setGpu(null); });
    void refresh();
    const timer = running ? window.setInterval(refresh, 5000) : null;
    return () => {
      active = false;
      if (timer != null) window.clearInterval(timer);
    };
  }, [running]);
  return (
    <div className="page-stack analysis-page">
      <section className="structure-hero analysis-hero">
        <div>
          <span className="section-kicker">分层分析</span>
          <h2>照片质量与问题</h2>
          <p>技术检测覆盖全部个人照片；Qwen3-VL 只处理代表帧和问题候选。模型结果仅作复核建议，不会自动删除或改写 Lightroom。</p>
        </div>
        <div className={`runtime-card ${preflight?.ready ? "ready" : ""}`}>
          <span>模型运行环境</span><strong>{preflight?.ready ? "预检通过" : "未就绪"}</strong><small>{preflight ? (preflight.ready ? `${preflight.quantization.toUpperCase()} · ${formatFileSize(preflight.model_bytes)} · ${preflight.image_max_edge ?? 1280}px · 显存上限 ${preflight.gpu_memory_limit_gb}GB` : preflight.blockers.join("；")) : analysis?.runtime.message ?? "正在检查"}</small>
          {gpu?.available && <small>{gpu.name} · GPU {gpu.utilization_percent}% · 显存 {((gpu.memory_used_mb ?? 0) / 1024).toFixed(1)} / {((gpu.memory_total_mb ?? 0) / 1024).toFixed(1)} GB · {gpu.temperature_c}°C</small>}
        </div>
      </section>
      <TaskCard task={isAnalysisTask(task) ? task : null} cancel={cancelTask} pause={pauseTask} />
      <section className="analysis-action-grid">
        <article className="panel analysis-action-card"><span className="section-kicker">不使用 GPU</span><h3>技术质量检测</h3><p>检查曝光、清晰度与拍摄参数，未变化的照片会复用已有结果。</p><strong>{summary ? `${numberFormat.format(summary.analyzed)} 张已完成` : "正在读取"}</strong><button className="toolbar-button primary" onClick={startQuality} disabled={running}>检测新增或变化照片</button></article>
        <article className="panel analysis-action-card"><span className="section-kicker">拍摄信息</span><h3>详情数据补全</h3><p>补充扩展 EXIF、机内配方和 JPG 亮度直方图，不修改照片。</p><strong>{analysis ? `元数据待补 ${numberFormat.format(analysis.detail_data.metadata_pending)} · 直方图待补 ${numberFormat.format(analysis.detail_data.histograms_pending)}` : "正在读取"}</strong>{task?.status === "paused" && task.stage.startsWith("detail-") ? <button className="toolbar-button primary" onClick={resumeDetailBackfill}>继续补全</button> : <button className="toolbar-button" onClick={startDetailBackfill} disabled={running || (!analysis?.detail_data.metadata_pending && !analysis?.detail_data.histograms_pending)}>{analysis && !analysis.detail_data.metadata_pending && !analysis.detail_data.histograms_pending ? "当前无需补全" : "补全详情数据"}</button>}</article>
        <article className="panel analysis-action-card model"><span className="section-kicker">使用本机 GPU</span><h3>本地模型分析</h3><p>分析画面内容、可见问题和后期建议；仅保存建议，需人工复核。</p><strong>{preflight?.ready ? `${numberFormat.format(ai?.candidates?.recommended_available ?? 0)} 张推荐候选` : preflight?.blockers.join("；") ?? "正在预检"}</strong><div><button className="toolbar-button" onClick={() => startAi("benchmark", 10)} disabled={running || !summary?.analyzed || !preflight?.ready}>验证 10 张</button><label><select value={batchSize} onChange={(event) => setBatchSize(Number(event.target.value))} disabled={running}>{[25, 50, 100, 200, 500].map((size) => <option key={size} value={size}>{size} 张</option>)}</select><small>{estimatedBatchSeconds ? `约 ${formatDuration(estimatedBatchSeconds)}` : "批次"}</small></label><button className="toolbar-button primary" onClick={() => startAi("recommended", batchSize)} disabled={running || !summary?.analyzed || !preflight?.ready}>运行批次</button></div></article>
      </section>
      {(analysis?.subject_tags.eligible_captures ?? 0) > 0 && <section className="panel analysis-tag-sync">
        <div><span className="section-kicker">题材标签</span><strong>分析来源 {numberFormat.format(analysis?.subject_tags.tagged_captures ?? 0)} / {numberFormat.format(analysis?.subject_tags.eligible_captures ?? 0)} 张</strong><small>{numberFormat.format(analysis?.subject_tags.subject_count ?? 0)} 种题材 · 不覆盖人工标签</small></div>
        <div><button className="toolbar-button primary" onClick={syncAnalysisSubjectTags} disabled={running}>同步已有结果</button><button className="toolbar-button" onClick={clearAnalysisSubjectTags} disabled={running || !analysis?.subject_tags.tag_links}>清除分析题材</button></div>
      </section>}
      {ai?.latest_run && ["failed", "cancelled", "paused"].includes(ai.latest_run.status) && <section className="analysis-recovery"><span>上次模型任务尚未完整结束。</span><button className="toolbar-button" onClick={() => resumeAi(ai.latest_run!.id)} disabled={running}>继续上次任务</button></section>}
      {ai?.latest_run && ai.latest_run.status === "complete" && ai.latest_run.failed_count > 0 && <section className="analysis-recovery"><span>上次任务有 {ai.latest_run.failed_count} 张失败。</span><button className="toolbar-button" onClick={() => retryAiFailures(ai.latest_run!.id)} disabled={running || !preflight?.ready}>重试失败项</button></section>}
      <section className="metric-grid">
        <article><span>技术分析完成</span><strong>{summary ? numberFormat.format(summary.analyzed) : "—"}</strong><small>{summary?.errors ?? 0} 个读取错误</small></article>
        <article><span className="metric-label-with-help">平均技术健康度<button type="button" aria-label="解释技术健康度" onClick={() => setHealthHelpOpen(true)}>?</button></span><strong>{summary?.average_score ?? "—"}</strong><small>低于 70 时建议优先复核</small></article>
        <article><span>组内推荐</span><strong>{summary ? numberFormat.format(summary.recommended_picks) : "—"}</strong><small>每个相似组一个候选</small></article>
        <article><span>模型分析完成</span><strong>{ai ? numberFormat.format(ai.analyzed_capture_count) : "—"}</strong><small>{ai?.latest_run ? `${ai.latest_run.model_id} · ${ai.latest_run.status}${ai.latest_run.average_seconds_per_photo ? ` · ${ai.latest_run.average_seconds_per_photo.toFixed(1)}秒/张` : ""}` : "尚未启动"}</small></article>
      </section>
      <div className="workspace-view-nav analysis-content-nav">
        <nav className="analysis-tabs" aria-label="质量分析内容">
          {([['quality', '照片复核'], ['model', '模型结果'], ['history', '运行记录']] as const).map(([value, label]) => <button role="tab" aria-selected={analysisTab === value} key={value} className={analysisTab === value ? "active" : ""} onClick={() => setAnalysisTab(value)}>{label}</button>)}
        </nav>
        {analysisTab === "quality" && !qualityAlbumId && <CollectionScopeTabs scope={qualityBrowseMode} setScope={setQualityBrowseMode} allLabel="全部照片" />}
      </div>
      {analysisTab === "history" && ai?.result_audit?.latest && <details className="panel advanced-diagnostics"><summary>模型质量与运行诊断</summary><section className="metric-grid ai-audit-metrics">
        <article><span>当前提示词结果</span><strong>{numberFormat.format(ai.result_audit.latest.result_count)}</strong><small>{ai.result_audit.latest.prompt_version}</small></article>
        <article><span>发现具体问题</span><strong>{numberFormat.format(ai.result_audit.latest.with_visible_problems)}</strong><small>有画面证据才展开建议</small></article>
        <article><span>过度自信输出</span><strong>{numberFormat.format(ai.result_audit.latest.overconfident)}</strong><small>置信度 ≥ 0.99，v3 将自动校准</small></article>
        <article><span>结构/逻辑警告</span><strong>{numberFormat.format(ai.result_audit.latest.schema_errors ?? 0)}</strong><small>缺字段、枚举或参数方向需复核</small></article>
        <article><span>危险操作提及</span><strong>{numberFormat.format(ai.result_audit.latest.unsafe_action_mentions ?? 0)}</strong><small>只提示人工复核，系统不会执行</small></article>
        <article><span>当前版本均速</span><strong>{ai.result_audit.latest.average_seconds_per_photo == null ? "—" : `${ai.result_audit.latest.average_seconds_per_photo.toFixed(1)} 秒`}</strong><small>{numberFormat.format(ai.result_audit.latest.timed_count)} 张有效计时</small></article>
        <article><span>人工复核</span><strong>{numberFormat.format(ai.result_audit.latest.reviewed)}</strong><small>准确 {ai.result_audit.latest.verdicts.accurate} · 部分 {ai.result_audit.latest.verdicts.partial} · 不准确 {ai.result_audit.latest.verdicts.inaccurate}</small></article>
        <article><span>风险优先队列</span><strong>{numberFormat.format(ai.result_audit.latest.risk_count)}</strong><small>低置信度、结构异常、危险提及或过度自信{ai.result_audit.latest.pending_audit_metadata ? ` · ${ai.result_audit.latest.pending_audit_metadata} 条后台分类中` : ""}</small></article>
      </section></details>}
      {analysisTab === "history" && !!ai?.result_audit?.versions?.length && <section className="panel ai-version-panel">
        <div className="panel-heading"><div><span className="section-kicker">版本比较</span><h3>提示词质量与速度</h3></div><span className="batch-count">结构异常只提示人工复核</span></div>
        <div className="ai-version-table">
          <div className="ai-version-row ai-version-header"><span>版本</span><span>结果</span><span>均速</span><span>平均置信度</span><span>结构/逻辑警告</span><span>危险提及</span></div>
          {ai.result_audit.versions.map((version) => <div className="ai-version-row" key={version.prompt_version}>
            <strong>{version.prompt_version}</strong><span>{numberFormat.format(version.result_count)}</span><span>{version.average_seconds_per_photo == null ? "—" : `${version.average_seconds_per_photo.toFixed(1)}秒`}</span><span>{version.average_confidence ?? "—"}</span><span>{version.schema_errors}</span><span>{version.unsafe_action_mentions}</span>
          </div>)}
        </div>
      </section>}
      {analysisTab === "model" && <section className="panel ai-results-panel">
        <div className="panel-heading"><div><span className="section-kicker">分页复核</span><h3>{resultAudit === "risk" ? "高风险复核队列" : resultAudit === "sample" ? "5% 稳定抽样队列" : "全部模型结果"}</h3></div><span className="batch-count">{resultPage ? `${numberFormat.format(resultPage.count)} 条` : "正在读取"}</span></div>
        <div className="ai-results-toolbar">
          <label>提示词版本<select value={resultVersion} onChange={(event) => { setResultVersion(event.target.value); setResultOffset(0); }}>
            <option value="all">全部版本</option>
            {(ai?.result_audit?.versions ?? []).map((item) => <option key={item.prompt_version} value={item.prompt_version}>{item.prompt_version}</option>)}
          </select></label>
          <label>人工复核<select value={resultVerdict} onChange={(event) => { setResultVerdict(event.target.value); setResultOffset(0); }}>
            <option value="all">全部</option><option value="unreviewed">未复核</option><option value="accurate">准确</option><option value="partial">部分准确</option><option value="inaccurate">不准确</option>
          </select></label>
          <label>审计队列<select value={resultAudit} onChange={(event) => { setResultAudit(event.target.value); setResultOffset(0); }}>
            <option value="risk">高风险优先</option><option value="sample">5% 稳定抽样</option><option value="all">全部记录</option>
          </select></label>
        </div>
        {!!resultPage?.items.length && <div className="ai-result-grid">
          {resultPage.items.map((result) => <button key={result.id} className="ai-result-card" onClick={() => openCapture(result.capture_id, resultPage.items.map((entry) => entry.capture_id))}>
            <img src={result.thumbnail_url} loading="lazy" alt={`${result.stem} 缩略图`} />
            <span><strong>{result.stem} · {result.subject_type ?? "未分类"}</strong><small>{result.quality_summary ?? "没有摘要"}</small><em className={result.review_flags?.length ? "result-review-warning" : ""}>{result.review_flags?.length ? "需优先人工复核" : `${result.visible_problem_count} 个问题`} · {result.prompt_version} · {result.user_verdict ?? "未复核"}</em></span>
          </button>)}
        </div>}
        {resultPage && !resultPage.items.length && <div className="empty-state">当前筛选条件没有模型结果。</div>}
        {resultPage && <Pagination count={resultPage.count} limit={resultPage.limit} offset={resultPage.offset} onChange={setResultOffset} onLimitChange={(limit) => { setResultOffset(0); setResultLimit(limit); }} />}
      </section>}
      {analysisTab === "history" && !!ai?.recent_runs.length && (
        <section className="panel ai-history-panel">
          <div className="panel-heading"><div><span className="section-kicker">运行记录</span><h3>模型任务历史</h3></div><span className="batch-count">保留模型、量化和提示词版本</span></div>
          <div className="ai-run-list">
            {ai.recent_runs.map((run) => (
              <article className="ai-run-row" key={run.id}>
                <div><strong>#{run.id} · {run.model_id}</strong><span>{run.mode} · {formatDate(run.started_at)}{run.backup_count ? ` · ${run.backup_count} 份数据库备份` : ""}{run.report_available && <> · <a href={`/api/ai/runs/${run.id}/report.csv`}>CSV</a> · <a href={`/api/ai/runs/${run.id}/report.json`}>JSON</a> · <a href={`/api/reports/ai-run-${run.id}.log`}>日志</a></>}</span></div>
                <div><strong>{run.completed_count} / {run.requested_count}</strong><span>完成 / 计划</span></div>
                <div><strong>{run.success_rate == null ? "—" : `${run.success_rate}%`}</strong><span>成功率</span></div>
                <div><strong>{run.average_seconds_per_photo == null ? "—" : `${run.average_seconds_per_photo.toFixed(1)}秒`}</strong><span>平均每张</span></div>
                <div><strong>{run.status}</strong><span>{run.failed_count ? `${run.failed_count} 个失败` : "无失败"}</span></div>
              </article>
            ))}
          </div>
          {!!ai.latest_failures.length && (
            <div className="ai-failure-list">
              <strong>最近任务失败清单</strong>
              {ai.latest_failures.map((failure) => (
                <div key={failure.id}><span>{failure.stem} · 尝试 {failure.attempt_count} 次</span><small>{failure.error ?? "未知错误"}</small></div>
              ))}
            </div>
          )}
        </section>
      )}
      {analysisTab === "quality" && qualityAlbumId && <AlbumWorkspaceHeader name={selectedQualityAlbum?.name ?? "相册质量"} category={selectedQualityAlbum?.category ?? "相册"} summary={`${numberFormat.format(selectedQualityAlbum?.analyzed_count ?? quality?.count ?? 0)} 张已分析 · ${numberFormat.format(selectedQualityAlbum?.problem_count ?? 0)} 张有问题`} counts={albumWorkspaceCounts} current="analysis" back={() => { setQualityBrowseMode("albums"); setQualityAlbumId(""); }} openPhotos={() => openAlbumPhotos(Number(qualityAlbumId))} openBursts={() => openAlbumBursts(Number(qualityAlbumId))} openQuality={() => undefined} />}
      {analysisTab === "quality" && !qualityAlbumId && qualityBrowseMode === "albums" && <section className="panel album-selection-panel quality-album-panel">
        <div className="panel-heading compact-list-heading"><div><h3>选择相册</h3></div><span className="batch-count">{quality?.albums.length ?? 0} 个相册已有质量数据</span></div>
        <div className="quality-album-grid">{(quality?.albums ?? []).map((album) => <button key={album.id} onClick={() => setQualityAlbumId(String(album.id))}><span><small>{album.category}</small><strong>{album.name}</strong></span><div><b>{numberFormat.format(album.analyzed_count)}</b><small>已分析</small></div><dl><div><dt>{numberFormat.format(album.problem_count)}</dt><dd>有问题</dd></div><div><dt>{numberFormat.format(album.model_count)}</dt><dd>模型完成</dd></div></dl></button>)}</div>
        {!quality?.albums.length && <div className="empty-state">还没有可按相册查看的质量结果，请先运行技术检测。</div>}
      </section>}
      {analysisTab === "quality" && (Boolean(qualityAlbumId) || qualityBrowseMode === "all") && <section className="panel quality-review-panel">
        <div className="panel-heading"><div><span className="section-kicker">照片复核</span><h3>问题与改进建议</h3></div><span className="batch-count">点击照片查看完整分析</span></div>
        <div className="quality-review-toolbar">
          <input value={qualitySearch} onChange={(event) => setQualitySearch(event.target.value)} placeholder="搜索照片或相册" />
          <select value={qualityFilter} onChange={(event) => setQualityFilter(event.target.value as QualityReviewFilter)}><option value="all">全部已分析</option><option value="problems">发现问题</option><option value="low_score">技术健康度低于 70</option><option value="with_model">已有模型结果</option><option value="without_model">等待模型分析</option><option value="unrated">尚未评分</option></select>
        </div>
        <div className="quality-review-grid">
          {(quality?.items ?? []).map((item) => {
            const technicalSummary = item.issues[0]?.message || "未发现明确技术问题";
            const technicalSuggestion = item.issues[0] ? technicalAdvice(item.issues[0].code) : "当前技术指标正常，可结合构图和表达继续人工判断。";
            return (
            <article className="quality-review-card" key={item.capture_id}>
              <button className="quality-review-photo" onClick={() => openCapture(item.capture_id, (quality?.items ?? []).map((entry) => entry.capture_id))}><img src={item.thumbnail_url} loading="lazy" alt={item.stem} /><span>技术健康度 {Math.round(item.technical_score)} · {item.issues.length ? `${item.issues.length} 项需复核` : "未见明显故障"}</span></button>
              <div className="quality-review-copy"><div><strong>{item.stem}</strong><small>{item.event_name} · {item.category}{item.auto_pick ? " · 组内推荐" : ""}</small></div><div className="quality-source technical"><b>技术检测</b><span>{technicalSummary}</span><small>{technicalSuggestion}</small></div>{item.ai_result && <div className="quality-source model"><b>模型补充</b><span>{item.ai_result.quality_summary ?? "模型已完成分析"}</span><small>{modelAdvice(item.ai_result)}</small></div>}</div>
              <div className="review-controls"><button onClick={() => openCapture(item.capture_id, (quality?.items ?? []).map((entry) => entry.capture_id))}>查看详情</button>
                <select aria-label={`${item.stem} 人工星级`} value={item.user_rating ?? ""} onChange={(event) => saveReview(item.capture_id, { user_rating: event.target.value ? Number(event.target.value) : null, user_pick: Boolean(item.user_pick), user_reject: Boolean(item.user_reject), user_note: item.user_note })}>
                  <option value="">人工星级</option><option value="1">1 星</option><option value="2">2 星</option><option value="3">3 星</option><option value="4">4 星</option><option value="5">5 星</option>
                </select>
              </div>
            </article>
          );})}
          {!quality?.items.length && <div className="empty-state">当前筛选条件没有照片。尚未分析时，请先运行技术检测。</div>}
        </div>
        {quality && <Pagination count={quality.count} limit={quality.limit} offset={quality.offset} onChange={changeQualityPage} onLimitChange={changeQualityPageSize} />}
      </section>}
      {healthHelpOpen && <ModalShell title="技术健康度是什么？" close={() => setHealthHelpOpen(false)}>
        <div className="technical-health-help"><p>它用于发现明显的基础技术风险，不是照片的综合质量或审美评分。</p><dl><div><dt>曝光 34%</dt><dd>检查整体亮度以及大面积亮部、暗部裁切。</dd></div><div><dt>全局细节 46%</dt><dd>检查画面整体边缘信息；浅景深、柔焦和运动画面仍需人工判断。</dd></div><div><dt>参数风险 20%</dt><dd>结合焦距、快门和 ISO 提示手抖、动作模糊或高感风险。</dd></div></dl><strong>不评价</strong><p>构图、表情、时机、主体价值和个人审美。高分只表示没有检测到明显基础故障。</p></div>
        <footer className="editor-footer"><button className="primary" onClick={() => setHealthHelpOpen(false)}>知道了</button></footer>
      </ModalShell>}
    </div>
  );
}
