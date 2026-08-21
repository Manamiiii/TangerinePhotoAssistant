import { TaskCard, type Task } from "../../components/TaskCard";
import { formatBytes, numberFormat } from "../../formatters";
import type { ArchiveStatus } from "../system/ArchiveView";
import type { SystemCapabilities } from "../system/types";
import type { Statistics } from "../statistics/StatisticsView";
import type { SimilarityGroupsResponse } from "../similarity/types";
import type { LibraryCapturesResponse, LibraryFilters } from "../library/types";
import type { Overview } from "../overview/types";

export function HomeView({ overview, statistics, archive, activeBaseline, library, filters, similarity, task, capabilities, firstRun, openPhotos, openSetup, openAlbums, openAlbum, openBursts, openStatistics, continueLabel, continueWork, openUnassigned, openMaintenance, openCapture }: {
  overview: Overview | null;
  statistics: Statistics | null;
  archive: ArchiveStatus | null;
  activeBaseline: ArchiveStatus | null;
  library: LibraryCapturesResponse | null;
  filters: LibraryFilters | null;
  similarity: SimilarityGroupsResponse | null;
  task: Task | null;
  capabilities: SystemCapabilities | null;
  firstRun: boolean;
  openPhotos: () => void;
  openSetup: () => void;
  openAlbums: () => void;
  openAlbum: (albumId: number) => void;
  openBursts: () => void;
  openStatistics: () => void;
  continueLabel: string;
  continueWork: () => void;
  openUnassigned: () => void;
  openMaintenance: () => void;
  openCapture: (captureId: number, context?: number[]) => void;
}) {
  const pendingEvents = overview?.structure.unconfirmed_event_count ?? 0;
  const unassigned = overview?.structure.unassigned_capture_count ?? 0;
  const archiveIssue = archive?.comparison && !archive.comparison.healthy;
  const activeIssue = activeBaseline?.comparison && !activeBaseline.comparison.healthy;
  const pendingSimilarity = similarity?.pending_count ?? 0;
  const monthRows = statistics?.months ?? [];
  const latestMonth = monthRows[monthRows.length - 1] ?? null;
  const hasPending = pendingEvents > 0 || unassigned > 0 || pendingSimilarity > 0 || Boolean(archiveIssue) || Boolean(activeIssue);
  const recentAlbums = (filters?.albums ?? []).slice(0, 4);
  const topCamera = statistics?.cameras[0];
  const topLens = statistics?.lenses[0];
  return <>
    <section className="home-metrics">
      <article><span>全部照片</span><strong>{overview ? numberFormat.format(overview.capture_total) : "—"}</strong><small>{overview ? formatBytes(overview.files.size_bytes) : ""}</small></article>
      <article><span>拍摄相册</span><strong>{overview?.structure.event_count ?? "—"}</strong><small>{pendingEvents} 个名称待确认</small></article>
      <article><span>最近拍摄月</span><strong>{latestMonth ? numberFormat.format(latestMonth.count) : "—"}</strong><small>{latestMonth?.month ?? "暂无拍摄日期"}</small></article>
    </section>
    {overview?.capture_total === 0 && <section className="panel welcome-panel">
      <div><span className="section-kicker">本地图库</span><h3>{firstRun ? "连接你的照片目录" : "图库中还没有照片"}</h3><p>{firstRun ? "先确认照片、工作数据与缓存目录；设置过程不会扫描或修改照片。" : "当前目录已经完成过扫描，可以在照片图库中手动更新索引。"}</p></div>
      <div className="welcome-capabilities"><span><b>图库</b>{capabilities?.library_root ?? "正在读取配置"}</span><span><b>元数据</b>{capabilities?.metadata.message ?? "正在检测"}</span><button className="toolbar-button primary" onClick={firstRun ? openSetup : openPhotos}>{firstRun ? "开始设置" : "打开照片图库"}</button></div>
    </section>}
    {overview && overview.capture_total > 0 && <section className="home-workspace-grid">
      <section className="home-continue-card"><span className="section-kicker">继续上次工作</span><h3>{continueLabel}</h3><button className="primary-action" onClick={continueWork}><span>继续浏览</span><b>→</b></button><div><button onClick={openPhotos}>照片图库</button><button onClick={openBursts}>相似组选片</button><button onClick={openStatistics}>摄影统计</button></div></section>
      <section className="panel home-albums-panel"><div className="panel-heading"><div><h3>最近相册</h3></div><button className="text-action" onClick={openAlbums}>管理全部</button></div><div className="home-album-list">{recentAlbums.map((album) => <button key={album.id} onClick={() => openAlbum(album.id)}><span><strong>{album.name}</strong><small>{album.category}</small></span><b>{album.capture_count} 张</b></button>)}</div></section>
    </section>}
    <section className="home-management-grid">
      <section className="panel recent-photos-panel"><div className="panel-heading"><div><h3>最近照片</h3></div><button className="text-action" onClick={openPhotos}>查看全部</button></div><div className="recent-photo-grid">
        {(library?.items ?? []).slice(0, 8).map((item, _index, recent) => <button key={item.id} onClick={() => openCapture(item.id, recent.map((entry) => entry.id))}><img src={item.thumbnail_url} alt={item.stem} /><span>{item.stem}</span></button>)}
      </div></section>
      <section className="panel pending-panel"><div className="panel-heading"><div><h3>待处理</h3></div></div><div className="pending-list">
        {pendingEvents > 0 && <button onClick={openAlbums}><span><strong>{pendingEvents}</strong> 个相册名称待确认</span><b>整理相册</b></button>}
        {pendingSimilarity > 0 && <button onClick={openBursts}><span><strong>{numberFormat.format(pendingSimilarity)}</strong> 组相似照片待挑选<small>预计约 {similarity?.estimated_review_minutes ?? 0} 分钟</small></span><b>继续选片</b></button>}
        {unassigned > 0 && <button onClick={openUnassigned}><span><strong>{unassigned}</strong> 张照片尚未归入相册</span><b>查看照片</b></button>}
        {archiveIssue && <button onClick={openMaintenance}><span>历史原片完整性检查存在异常</span><b>查看状态</b></button>}
        {activeIssue && <button onClick={openMaintenance}><span>活动图库完整性检查存在异常</span><b>查看状态</b></button>}
        {!hasPending && <div className="empty-state">当前没有需要及时处理的项目。</div>}
      </div></section>
    </section>
    {overview && overview.capture_total > 0 && <section className="panel home-insights"><div className="panel-heading"><div><h3>本月摄影摘要</h3></div><button className="text-action" onClick={openStatistics}>查看完整统计</button></div><div><article><span>最近月份</span><strong>{latestMonth?.month ?? "—"}</strong><small>{latestMonth ? `${numberFormat.format(latestMonth.count)} 张 · ${latestMonth.user_picks} 张入选` : "暂无数据"}</small></article><article><span>最常用相机</span><strong>{topCamera?.camera_model ?? "—"}</strong><small>{topCamera ? `${numberFormat.format(topCamera.count)} 次拍摄` : "暂无器材信息"}</small></article><article><span>最常用镜头</span><strong>{topLens?.lens_model ?? "—"}</strong><small>{topLens ? `${numberFormat.format(topLens.count)} 次拍摄` : "暂无镜头信息"}</small></article></div></section>}
    {task && task.status !== "idle" && <section className="home-current-task"><TaskCard task={task} /></section>}
  </>;
}
