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
      <div className="statistics-view-toolbar"><div className="section-tabs" role="tablist" aria-label="统计视图">{([['overview', '概览'], ['parameters', '拍摄参数'], ['time', '时间趋势']] as const).map(([value, label]) => <button key={value} className={statisticsView === value ? "active" : ""} onClick={() => setStatisticsView(value)}>{label}</button>)}</div>{statisticsView !== "time" && <div className="section-tabs" role="group" aria-label="统计值显示"><button className={distributionMode === "count" ? "active" : ""} onClick={() => setDistributionMode("count")}>数量</button><button className={distributionMode === "percent" ? "active" : ""} onClick={() => setDistributionMode("percent")}>占比</button></div>}</div>
      {statisticsView === "overview" && <>
      <section className="panel selection-benchmark-panel">
        <div className="panel-heading"><div><span className="section-kicker">选片基准</span><h3>技术推荐与人工入选</h3></div><span className="batch-count">只统计已有人工入选的相似组</span></div>
        {(statistics?.selection_benchmark.reviewed_groups ?? 0) > 0 ? <><div className="selection-benchmark-grid"><article><span>已形成基准</span><strong>{numberFormat.format(statistics?.selection_benchmark.reviewed_groups ?? 0)}</strong><small>个人已完成选片的相似组</small></article><article><span>Top‑1 命中</span><strong>{statistics?.selection_benchmark.top1_rate ?? 0}%</strong><small>{statistics?.selection_benchmark.top1_hits ?? 0} 组人工入选包含技术最佳</small></article><article><span>Top‑2 覆盖</span><strong>{statistics?.selection_benchmark.top2_rate ?? 0}%</strong><small>{statistics?.selection_benchmark.top2_hits ?? 0} 组人工入选进入前两名</small></article></div>{(statistics?.selection_reasons.length ?? 0) > 0 && <div className="selection-reason-summary"><span>人工保留理由</span>{statistics?.selection_reasons.map((item) => <b key={item.reason}>{item.reason}<small>{numberFormat.format(item.count)}</small></b>)}</div>}</> : <div className="empty-state">完成一些相似组选片后，这里会评估推荐命中率；未选组不会被算作失败。</div>}
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
          <div className="panel-heading"><div><span className="section-kicker">拍摄复盘</span><h3>高频问题</h3></div><span className="batch-count">点击查看有问题的照片</span></div>
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
      {statisticsView === "time" &&
      <section className="panel month-panel">
        <div className="panel-heading"><div><span className="section-kicker">时间趋势</span><h3>最近拍摄月份</h3></div><span className="batch-count">点击月份跳到对应照片</span></div>
        <div className="month-strip">{(statistics?.months ?? []).slice(-24).map((month) => <button type="button" key={month.month} onClick={() => openMonth(month.month)}><span>{month.month}</span><i style={{ height: `${Math.max(8, Math.min(100, month.count / Math.max(1, ...(statistics?.months ?? []).map((item) => item.count)) * 100))}%` }} /><strong>{month.count}</strong><small>{month.average_score ?? "—"}</small></button>)}</div>
      </section>
      }
    </>
  );
}
