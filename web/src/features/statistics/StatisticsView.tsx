import { useState } from "react";
import { numberFormat } from "../../formatters";

export type StatisticRow = { count: number; average_score: number | null } & Record<string, string | number | null>;
export type Statistics = {
  summary: {
    capture_count: number;
    first_capture: string | null;
    last_capture: string | null;
    shooting_days: number;
    album_count: number;
    quality_analyzed: number;
    average_technical_score: number | null;
    user_picks: number;
    user_rejects: number;
  };
  selection_benchmark: {
    reviewed_groups: number | null;
    top1_hits: number | null;
    top2_hits: number | null;
    top1_rate: number | null;
    top2_rate: number | null;
  };
  selection_reasons: Array<{ reason: string; count: number }>;
  shooting_review_summary: {
    reviewed_captures: number;
    with_observations: number | null;
    with_next_time: number | null;
    with_editing: number | null;
    average_confidence: number | null;
  };
  shooting_review_problems: Array<{
    problem: string;
    count: number;
    average_confidence: number | null;
    repairability: "limited" | "partial" | "unknown";
    repairability_label: string;
  }>;
  conditional_review_insights: Array<{
    condition_key: string;
    dimension: string;
    dimension_label: string;
    condition: string;
    problem: string;
    sample_count: number;
    problem_count: number;
    problem_rate: number;
    baseline_rate: number;
    lift: number;
  }>;
  growth_summary: {
    rated_count: number;
    high_rated_count: number;
    high_rating_rate: number | null;
    quality_count: number;
    technical_failure_count: number;
    technical_failure_rate: number | null;
    repeat_base_count: number;
    similar_capture_count: number;
    repeat_capture_rate: number | null;
    selection_decisions: number;
    selected_count: number;
    selection_keep_rate: number | null;
  };
  growth_months: Array<StatisticRow & {
    month: string;
    rated_count: number;
    high_rated_count: number;
    high_rating_rate: number | null;
    quality_count: number;
    technical_failure_count: number;
    technical_failure_rate: number | null;
    similar_capture_count: number;
    repeat_capture_rate: number | null;
    selection_decisions: number;
    selected_count: number;
    selection_keep_rate: number | null;
  }>;
  growth_subjects: Array<StatisticRow & {
    subject: string;
    rated_count: number;
    high_rated_count: number;
    high_rating_rate: number | null;
    quality_count: number;
    technical_failure_count: number;
    technical_failure_rate: number | null;
    similar_capture_count: number;
    repeat_capture_rate: number | null;
  }>;
  selection_efficiency: {
    completed_sessions: number;
    average_active_seconds: number | null;
    average_decisions: number | null;
  };
  edit_feedback: {
    reviewed_recipes: number;
    accepted_count: number;
    dismissed_count: number;
    draft_count: number;
  };
  categories: StatisticRow[];
  months: Array<StatisticRow & { month: string; user_picks: number }>;
  cameras: Array<StatisticRow & { camera_model: string }>;
  lenses: Array<StatisticRow & { lens_model: string; user_picks: number; pick_rate: number | null }>;
  focal_ranges: Array<StatisticRow & { bucket: string }>;
  iso_ranges: Array<StatisticRow & { bucket: string }>;
  aperture_ranges: Array<StatisticRow & { bucket: string }>;
  shutter_ranges: Array<StatisticRow & { bucket: string }>;
  exposure_compensation_ranges: Array<StatisticRow & { bucket: string }>;
  ratings: Array<{ rating: number; count: number; user_rated: number }>;
  issues: Array<{ code: string; message: string; count: number }>;
};

type StatisticsLibraryQuery = {
  category?: string;
  camera?: string;
  lens?: string;
  quality?: string;
  dateFrom?: string;
  dateTo?: string;
  selectionReason?: string;
  modelProblem?: string;
  reviewCondition?: string;
  tagSubject?: string;
};

function Distribution({ title, rows, labelKey, onSelect, selectHint, valueMode = "count" }: {
  title: string;
  rows: StatisticRow[];
  labelKey: string;
  onSelect?: (label: string) => void;
  selectHint?: string;
  valueMode?: "count" | "percent";
}) {
  const maximum = Math.max(1, ...rows.map((row) => row.count));
  const total = Math.max(1, rows.reduce((sum, row) => sum + row.count, 0));
  return (
    <section className="panel distribution-panel">
      <div className="panel-heading"><div><span className="section-kicker">分布</span><h3>{title}</h3></div>{onSelect && <span className="batch-count">{selectHint ?? "点击跳到对应照片"}</span>}</div>
      <div className="bar-list">
        {rows.map((row, index) => {
          const content = <>
            <span title={String(row[labelKey])}>{String(row[labelKey])}</span>
            <div><i style={{ width: `${Math.max(2, row.count / (valueMode === "percent" ? total : maximum) * 100)}%` }} /></div>
            <strong>{valueMode === "percent" ? `${(row.count / total * 100).toFixed(1)}%` : numberFormat.format(row.count)}</strong>
            <small>{row.average_score == null ? "未评分" : `均分 ${row.average_score}`}</small>
          </>;
          return onSelect
            ? <button type="button" className="bar-row bar-row-link" key={`${String(row[labelKey])}-${index}`} onClick={() => onSelect(String(row[labelKey]))}>{content}</button>
            : <div className="bar-row" key={`${String(row[labelKey])}-${index}`}>{content}</div>;
        })}
      </div>
    </section>
  );
}

export function StatisticsView({ statistics, openLibraryWith }: {
  statistics: Statistics | null;
  openLibraryWith: (changes: StatisticsLibraryQuery) => void;
}) {
  const [statisticsView, setStatisticsView] = useState<"overview" | "parameters" | "time">("overview");
  const [distributionMode, setDistributionMode] = useState<"count" | "percent">("percent");
  const summary = statistics?.summary;
  const qualityCoverage = summary?.capture_count
    ? Math.round(summary.quality_analyzed / summary.capture_count * 100)
    : 0;
  const openMonth = (month: string) => {
    const [year, monthPart] = month.split("-").map(Number);
    if (!year || !monthPart) return;
    const lastDay = new Date(year, monthPart, 0).getDate();
    openLibraryWith({ dateFrom: `${month}-01`, dateTo: `${month}-${String(lastDay).padStart(2, "0")}` });
  };
  return (
    <>
      <section className="structure-hero statistics-hero">
        <div><span className="section-kicker">摄影数据</span><h2>拍摄统计</h2></div>
        <div className="structure-stat"><strong>{summary ? numberFormat.format(summary.capture_count) : "—"}</strong><span>个个人拍摄单元</span></div>
      </section>
      <section className="metric-grid">
        <article><span>拍摄天数</span><strong>{summary ? numberFormat.format(summary.shooting_days) : "—"}</strong><small>{summary?.first_capture?.slice(0, 10) ?? "—"} 至 {summary?.last_capture?.slice(0, 10) ?? "—"}</small></article>
        <article><span>相册</span><strong>{summary ? numberFormat.format(summary.album_count) : "—"}</strong><small>按当前图库归属统计</small></article>
        <article><span>质量分析覆盖</span><strong>{summary ? `${qualityCoverage}%` : "—"}</strong><small>{summary ? `${numberFormat.format(summary.quality_analyzed)} / ${numberFormat.format(summary.capture_count)} 张` : "—"}</small></article>
        <article><span>平均技术分</span><strong>{summary?.average_technical_score ?? "—"}</strong><small>只计算已有质量分析的照片</small></article>
      </section>
      <div className="statistics-view-toolbar"><div className="section-tabs" role="tablist" aria-label="统计视图">{([['overview', '概览'], ['parameters', '拍摄参数'], ['time', '成长趋势']] as const).map(([value, label]) => <button key={value} className={statisticsView === value ? "active" : ""} onClick={() => setStatisticsView(value)}>{label}</button>)}</div>{statisticsView !== "time" && <div className="section-tabs" role="group" aria-label="统计值显示"><button className={distributionMode === "count" ? "active" : ""} onClick={() => setDistributionMode("count")}>数量</button><button className={distributionMode === "percent" ? "active" : ""} onClick={() => setDistributionMode("percent")}>占比</button></div>}</div>
      {statisticsView === "overview" && <>
      <section className="panel selection-benchmark-panel">
        <div className="panel-heading"><div><span className="section-kicker">选片基准</span><h3>技术推荐与人工入选</h3></div><span className="batch-count">只统计已有人工入选的相似组</span></div>
        {(statistics?.selection_benchmark.reviewed_groups ?? 0) > 0 ? <><div className="selection-benchmark-grid"><article><span>已形成基准</span><strong>{numberFormat.format(statistics?.selection_benchmark.reviewed_groups ?? 0)}</strong><small>个人已完成选片的相似组</small></article><article><span>Top‑1 命中</span><strong>{statistics?.selection_benchmark.top1_rate ?? 0}%</strong><small>{statistics?.selection_benchmark.top1_hits ?? 0} 组人工入选包含技术最佳</small></article><article><span>Top‑2 覆盖</span><strong>{statistics?.selection_benchmark.top2_rate ?? 0}%</strong><small>{statistics?.selection_benchmark.top2_hits ?? 0} 组人工入选进入前两名</small></article></div>{(statistics?.selection_reasons.length ?? 0) > 0 && <div className="selection-reason-summary"><span>人工保留理由</span>{statistics?.selection_reasons.map((item) => <button key={item.reason} onClick={() => openLibraryWith({ selectionReason: item.reason })}>{item.reason}<small>{numberFormat.format(item.count)}</small></button>)}</div>}</> : <div className="empty-state">完成一些相似组选片后，这里会评估推荐命中率；未选组不会被算作失败。</div>}
      </section>
      <section className="panel shooting-review-stats-panel">
        <div className="panel-heading"><div><span className="section-kicker">拍摄复盘</span><h3>模型观察与后期建议</h3></div><span className="batch-count">仅汇总每张照片最近一次完成的分析</span></div>
        {(statistics?.shooting_review_summary.reviewed_captures ?? 0) > 0 ? <>
          <div className="shooting-review-stat-grid">
            <article><span>已复盘</span><strong>{numberFormat.format(statistics?.shooting_review_summary.reviewed_captures ?? 0)}</strong><small>张照片</small></article>
            <article><span>发现观察</span><strong>{numberFormat.format(statistics?.shooting_review_summary.with_observations ?? 0)}</strong><small>有明确可见问题</small></article>
            <article><span>下次建议</span><strong>{numberFormat.format(statistics?.shooting_review_summary.with_next_time ?? 0)}</strong><small>有拍摄改进建议</small></article>
            <article><span>平均置信度</span><strong>{statistics?.shooting_review_summary.average_confidence == null ? "—" : `${statistics.shooting_review_summary.average_confidence}%`}</strong><small>模型自报置信度</small></article>
          </div>
          {(statistics?.shooting_review_problems.length ?? 0) > 0 && <div className="shooting-review-problem-list"><span>常见模型观察</span>{statistics?.shooting_review_problems.map((item) => <button key={item.problem} onClick={() => openLibraryWith({ modelProblem: item.problem })}><span>{item.problem}</span><small>{item.repairability_label} · 置信度 {item.average_confidence ?? "—"}%</small><b>{numberFormat.format(item.count)}</b></button>)}</div>}
          {(statistics?.conditional_review_insights.length ?? 0) > 0 && <div className="conditional-insight-list"><div><strong>条件性关联</strong><small>至少 3 张样本、2 次同类观察；表示相关性，不代表因果</small></div>{statistics?.conditional_review_insights.map((item) => <button key={`${item.condition_key}-${item.problem}`} onClick={() => openLibraryWith({ modelProblem: item.problem, reviewCondition: item.condition_key })}><span>{item.dimension_label} · {item.condition}</span><strong>{item.problem}</strong><small>{item.problem_count} / {item.sample_count} 张 · {item.problem_rate}%（整体 {item.baseline_rate}%）</small><b>{item.lift.toFixed(2)}×</b></button>)}</div>}
        </> : <div className="empty-state">完成本地模型分析后，这里会汇总观察、拍摄建议和后期可处理性。</div>}
      </section>
      <section className="statistics-grid">
        <Distribution title="题材占比" rows={statistics?.categories ?? []} labelKey="category" valueMode={distributionMode} onSelect={(category) => openLibraryWith({ category })} />
        <Distribution title="主要相机" rows={statistics?.cameras ?? []} labelKey="camera_model" valueMode={distributionMode} onSelect={(camera) => openLibraryWith({ camera })} />
        <Distribution title="主要镜头" rows={statistics?.lenses ?? []} labelKey="lens_model" valueMode={distributionMode} onSelect={(lens) => openLibraryWith({ lens })} />
      </section>
      <section className="statistics-grid">
        <section className="panel lens-efficiency-panel">
          <div className="panel-heading"><div><span className="section-kicker">器材使用</span><h3>镜头使用概览</h3></div></div>
          <div className="lens-efficiency-list">
            {(statistics?.lenses ?? []).map((lens) => <button key={lens.lens_model} onClick={() => openLibraryWith({ lens: lens.lens_model })}>
              <span>{lens.lens_model}</span>
              <em>{numberFormat.format(lens.count)} 张 · 均分 {lens.average_score ?? "—"}</em>
              <b>{lens.average_score == null ? "尚未评分" : `技术均分 ${lens.average_score}`}</b>
            </button>)}
            {!(statistics?.lenses ?? []).length && <div className="empty-state">暂无镜头数据。</div>}
          </div>
        </section>
        <section className="panel issue-stats-panel">
          <div className="panel-heading"><div><span className="section-kicker">基础分析</span><h3>高频技术问题</h3></div><span className="batch-count">点击查看有问题的照片</span></div>
          <div className="issue-stats-list">
            {(statistics?.issues ?? []).slice(0, 8).map((issue) => <button key={issue.code} onClick={() => openLibraryWith({ quality: "problems" })}>
              <span>{issue.message}</span>
              <b>{numberFormat.format(issue.count)}</b>
            </button>)}
            {!(statistics?.issues ?? []).length && <div className="empty-state">尚未发现技术问题，或还没有运行质量分析。</div>}
          </div>
        </section>
      </section>
      </>}
      {statisticsView === "parameters" && <section className="statistics-grid">
        <Distribution title="焦段习惯" rows={statistics?.focal_ranges ?? []} labelKey="bucket" valueMode={distributionMode} />
        <Distribution title="ISO 分布" rows={statistics?.iso_ranges ?? []} labelKey="bucket" valueMode={distributionMode} />
        <Distribution title="光圈分布" rows={statistics?.aperture_ranges ?? []} labelKey="bucket" valueMode={distributionMode} />
        <Distribution title="快门分布" rows={statistics?.shutter_ranges ?? []} labelKey="bucket" valueMode={distributionMode} />
        <Distribution title="曝光补偿" rows={statistics?.exposure_compensation_ranges ?? []} labelKey="bucket" valueMode={distributionMode} />
      </section>}
      {statisticsView === "time" && <>
        <section className="panel growth-summary-panel">
          <div className="panel-heading"><div><span className="section-kicker">当前基线</span><h3>人工选择与拍摄结果</h3></div><span className="batch-count">只陈述比例，不自动判断进步或退步</span></div>
          <div className="growth-summary-grid">
            <article><span>人工高星率</span><strong>{statistics?.growth_summary.high_rating_rate == null ? "—" : `${statistics.growth_summary.high_rating_rate}%`}</strong><small>{statistics?.growth_summary.high_rated_count ?? 0} / {statistics?.growth_summary.rated_count ?? 0} 张人工评级</small></article>
            <article><span>技术低分率</span><strong>{statistics?.growth_summary.technical_failure_rate == null ? "—" : `${statistics.growth_summary.technical_failure_rate}%`}</strong><small>{statistics?.growth_summary.technical_failure_count ?? 0} / {statistics?.growth_summary.quality_count ?? 0} 张低于 70 分</small></article>
            <article><span>相似拍摄占比</span><strong>{statistics?.growth_summary.repeat_capture_rate == null ? "—" : `${statistics.growth_summary.repeat_capture_rate}%`}</strong><small>{statistics?.growth_summary.similar_capture_count ?? 0} / {statistics?.growth_summary.repeat_base_count ?? 0} 张进入相似组</small></article>
            <article><span>人工选片保留率</span><strong>{statistics?.growth_summary.selection_keep_rate == null ? "—" : `${statistics.growth_summary.selection_keep_rate}%`}</strong><small>{statistics?.growth_summary.selected_count ?? 0} / {statistics?.growth_summary.selection_decisions ?? 0} 张明确取舍</small></article>
          </div>
          <p className="growth-method-note">高星率只使用人工 4–5 星；技术低分只使用已有质量结果；相似占比不是缺陷；保留率描述取舍风格，不等同于选片耗时效率。</p>
        </section>
        <section className="panel growth-month-panel">
          <div className="panel-heading"><div><span className="section-kicker">按拍摄月</span><h3>月度基线</h3></div><span className="batch-count">点击月份查看当月照片；先看样本量再比较</span></div>
          <div className="growth-month-table">
            <div className="growth-month-head"><span>月份 / 样本</span><span>人工高星</span><span>技术低分</span><span>相似拍摄</span><span>选片保留</span></div>
            {(statistics?.growth_months ?? []).slice(-24).map((month) => <button key={month.month} onClick={() => openMonth(month.month)}>
              <span><strong>{month.month}</strong><small>{month.count} 张 · 均分 {month.average_score ?? "—"}</small></span>
              <span><strong>{month.high_rating_rate == null ? "—" : `${month.high_rating_rate}%`}</strong><small>{month.high_rated_count}/{month.rated_count}</small></span>
              <span><strong>{month.technical_failure_rate == null ? "—" : `${month.technical_failure_rate}%`}</strong><small>{month.technical_failure_count}/{month.quality_count}</small></span>
              <span><strong>{month.repeat_capture_rate == null ? "—" : `${month.repeat_capture_rate}%`}</strong><small>{month.similar_capture_count}/{month.count}</small></span>
              <span><strong>{month.selection_keep_rate == null ? "—" : `${month.selection_keep_rate}%`}</strong><small>{month.selected_count}/{month.selection_decisions}</small></span>
            </button>)}
            {!(statistics?.growth_months ?? []).length && <div className="empty-state">暂无可按月份统计的拍摄数据。</div>}
          </div>
        </section>
        <section className="panel growth-subject-panel">
          <div className="panel-heading"><div><span className="section-kicker">同题材对照</span><h3>人工结果与技术基线</h3></div><span className="batch-count">每个题材至少 3 张；多标签照片会进入多行</span></div>
          <div className="growth-month-table growth-subject-table">
            <div className="growth-month-head"><span>题材 / 样本</span><span>人工高星</span><span>技术低分</span><span>相似拍摄</span><span>技术均分</span></div>
            {(statistics?.growth_subjects ?? []).map((subject) => <button key={subject.subject} onClick={() => openLibraryWith({ tagSubject: subject.subject })}>
              <span><strong>{subject.subject}</strong><small>{subject.count} 张</small></span>
              <span><strong>{subject.high_rating_rate == null ? "—" : `${subject.high_rating_rate}%`}</strong><small>{subject.high_rated_count}/{subject.rated_count}</small></span>
              <span><strong>{subject.technical_failure_rate == null ? "—" : `${subject.technical_failure_rate}%`}</strong><small>{subject.technical_failure_count}/{subject.quality_count}</small></span>
              <span><strong>{subject.repeat_capture_rate == null ? "—" : `${subject.repeat_capture_rate}%`}</strong><small>{subject.similar_capture_count}/{subject.count}</small></span>
              <span><strong>{subject.average_score ?? "—"}</strong><small>已分析均分</small></span>
            </button>)}
            {!(statistics?.growth_subjects ?? []).length && <div className="empty-state">题材样本还不足，继续积累人工标签和评分后会自动出现。</div>}
          </div>
        </section>
        <section className="panel growth-feedback-panel">
          <div className="panel-heading"><div><span className="section-kicker">数据积累</span><h3>选片效率与修图反馈</h3></div><span className="batch-count">从本版本开始记录，不反推历史</span></div>
          <div className="growth-summary-grid">
            <article><span>完成选片会话</span><strong>{statistics?.selection_efficiency.completed_sessions ?? 0}</strong><small>{statistics?.selection_efficiency.average_active_seconds == null ? "少于 3 组时不计算平均值" : `平均活跃 ${statistics.selection_efficiency.average_active_seconds} 秒 · ${statistics.selection_efficiency.average_decisions} 次决策`}</small></article>
            <article><span>有最新修图方案</span><strong>{statistics?.edit_feedback.reviewed_recipes ?? 0}</strong><small>采用 {statistics?.edit_feedback.accepted_count ?? 0} · 暂不采用 {statistics?.edit_feedback.dismissed_count ?? 0} · 草稿 {statistics?.edit_feedback.draft_count ?? 0}</small></article>
          </div>
          <p className="growth-method-note">活跃耗时仅累计相邻选片动作，单次间隔最多计 5 分钟。“采用”是人工反馈，在没有同条件后续样本前不解释为修图建议已带来改善。</p>
        </section>
      </>}
    </>
  );
}
