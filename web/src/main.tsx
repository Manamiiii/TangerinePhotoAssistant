import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { getJson, similarityGroupsUrl } from "./api";
import { taskForDisplay, taskReceipt, type Task } from "./components/TaskCard";
import { ArchiveView, type ArchiveStatus } from "./features/system/ArchiveView";
import { LightroomView, type LightroomManifest, type LightroomManifestScope, type LightroomStatus } from "./features/system/LightroomView";
import type { EditableSettings, SettingsStatus, SystemCapabilities } from "./features/system/types";
import { SettingsView } from "./features/system/SettingsView";
import { EquipmentView } from "./features/equipment/EquipmentView";
import type { EquipmentCatalog, EquipmentDraft, EquipmentItem, EquipmentKind } from "./features/equipment/types";
import { StatisticsView, type Statistics } from "./features/statistics/StatisticsView";
import { AnalysisView } from "./features/analysis/AnalysisView";
import type { AiPreflight, AnalysisOverview, QualityItem, QualityResponse, QualityReviewFilter, ReviewPayload } from "./features/analysis/types";
import type { GroupCapture, SimilarityGroupDetail, SimilarityGroupsResponse, SimilarityReviewFilter } from "./features/similarity/types";
import { BurstsView } from "./features/similarity/BurstsView";
import type { CaptureDetail } from "./features/details/types";
import { CaptureDetailPanel } from "./features/details/CaptureDetailPanel";
import type { CaptureTagDimension } from "./features/details/types";
import type { Overview } from "./features/overview/types";
import type { EventItem, EventsResponse, LibraryCapturesResponse, LibraryFilters, LibraryQuery, LibrarySection, PhoneShareExport } from "./features/library/types";
import { LibraryView } from "./features/library/LibraryView";
import { HomeView } from "./features/home/HomeView";
import { formatDate } from "./formatters";
import "./styles.css";

type View = "home" | "library" | "bursts" | "analysis" | "statistics" | "equipment" | "lightroom" | "archive" | "settings";
type Theme = "light" | "dark";



type Toast = { id: number; kind: "success" | "error"; message: string; actionLabel?: string; action?: () => void };


function App() {
  const [view, setView] = useState<View>("home");
  const [lastWorkspaceView, setLastWorkspaceView] = useState<View>(() => {
    const saved = window.localStorage.getItem("tangerine-last-workspace") as View | null;
    return saved && saved !== "home" ? saved : "library";
  });
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = window.localStorage.getItem("tangerine-theme");
    return saved === "dark" ? "dark" : "light";
  });
  const [overview, setOverview] = useState<Overview | null>(null);
  const [libraryCaptures, setLibraryCaptures] = useState<LibraryCapturesResponse | null>(null);
  const [libraryLandingSection, setLibraryLandingSection] = useState<LibrarySection>("photos");
  const [libraryOffset, setLibraryOffset] = useState(0);
  const [libraryQuery, setLibraryQuery] = useState<LibraryQuery>({
    pageSize: 40, albumId: "", category: "", camera: "", lens: "",
    rating: "", selection: "", quality: "", tagSubject: "", tagStatus: "", tagProblem: "", tagLocation: "", selectionReason: "", modelProblem: "",
    dateFrom: "", dateTo: "", search: "", sort: "newest", collapseGroups: false,
  });
  const [libraryFilters, setLibraryFilters] = useState<LibraryFilters | null>(null);
  const [albumOffset, setAlbumOffset] = useState(0);
  const [albumPageSize, setAlbumPageSize] = useState(40);
  const [events, setEvents] = useState<EventsResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisOverview | null>(null);
  const [aiPreflight, setAiPreflight] = useState<AiPreflight | null>(null);
  const [quality, setQuality] = useState<QualityResponse | null>(null);
  const [qualityOffset, setQualityOffset] = useState(0);
  const [qualityPageSize, setQualityPageSize] = useState(40);
  const [qualityFilter, setQualityFilter] = useState<QualityReviewFilter>("all");
  const [qualitySearch, setQualitySearch] = useState("");
  const [qualityAlbumId, setQualityAlbumId] = useState("");
  const [similarityGroups, setSimilarityGroups] = useState<SimilarityGroupsResponse | null>(null);
  const [groupOffset, setGroupOffset] = useState(0);
  const [groupPageSize, setGroupPageSize] = useState(40);
  const [groupReviewFilter, setGroupReviewFilter] = useState<SimilarityReviewFilter>("pending");
  const [groupAlbumId, setGroupAlbumId] = useState("");
  const [selectedGroup, setSelectedGroup] = useState<SimilarityGroupDetail | null>(null);
  const [captureDetail, setCaptureDetail] = useState<CaptureDetail | null>(null);
  const [detailContext, setDetailContext] = useState<number[]>([]);
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [equipment, setEquipment] = useState<EquipmentCatalog | null>(null);
  const [archive, setArchive] = useState<ArchiveStatus | null>(null);
  const [activeLibraryBaseline, setActiveLibraryBaseline] = useState<ArchiveStatus | null>(null);
  const [lightroomStatus, setLightroomStatus] = useState<LightroomStatus | null>(null);
  const [lightroomManifest, setLightroomManifest] = useState<LightroomManifest | null>(null);
  const [capabilities, setCapabilities] = useState<SystemCapabilities | null>(null);
  const [settingsStatus, setSettingsStatus] = useState<SettingsStatus | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const refreshSequence = useRef(0);
  const toastSequence = useRef(0);
  const reviewQueues = useRef(new Map<number, Promise<void>>());
  const reviewVersions = useRef(new Map<number, number>());
  const reviewAggregateTimer = useRef<number | null>(null);

  const pushToast = useCallback((kind: Toast["kind"], message: string, actionLabel?: string, action?: () => void) => {
    const id = ++toastSequence.current;
    setToasts((current) => [...current.slice(-3), { id, kind, message, actionLabel, action }]);
    window.setTimeout(
      () => setToasts((current) => current.filter((toast) => toast.id !== id)),
      kind === "error" ? 6000 : action ? 8000 : 2400,
    );
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("tangerine-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (view === "home") return;
    setLastWorkspaceView(view);
    window.localStorage.setItem("tangerine-last-workspace", view);
  }, [view]);
  useEffect(() => {
    if (view === "bursts") return;
    setSelectedGroup(null);
    setGroupAlbumId("");
  }, [view]);

  const refreshLibrary = useCallback(async () => {
    const requestSequence = ++refreshSequence.current;
    const libraryParameters = new URLSearchParams({
      limit: String(libraryQuery.pageSize), offset: String(libraryOffset), sort: libraryQuery.sort,
    });
    if (libraryQuery.albumId === "__unassigned__") libraryParameters.set("unassigned", "true");
    else if (libraryQuery.albumId) libraryParameters.set("album_id", libraryQuery.albumId);
    if (libraryQuery.category) libraryParameters.set("category", libraryQuery.category);
    if (libraryQuery.camera) libraryParameters.set("camera_model", libraryQuery.camera);
    if (libraryQuery.lens) libraryParameters.set("lens_model", libraryQuery.lens);
    if (libraryQuery.rating) libraryParameters.set("rating", libraryQuery.rating);
    if (libraryQuery.selection) libraryParameters.set("selection", libraryQuery.selection);
    if (libraryQuery.quality) libraryParameters.set("quality", libraryQuery.quality);
    if (libraryQuery.tagSubject) libraryParameters.set("tag_subject", libraryQuery.tagSubject);
    if (libraryQuery.tagStatus) libraryParameters.set("tag_status", libraryQuery.tagStatus);
    if (libraryQuery.tagProblem) libraryParameters.set("tag_problem", libraryQuery.tagProblem);
    if (libraryQuery.tagLocation) libraryParameters.set("tag_location", libraryQuery.tagLocation);
    if (libraryQuery.selectionReason) libraryParameters.set("selection_reason", libraryQuery.selectionReason);
    if (libraryQuery.modelProblem) libraryParameters.set("model_problem", libraryQuery.modelProblem);
    if (libraryQuery.dateFrom) libraryParameters.set("date_from", libraryQuery.dateFrom);
    if (libraryQuery.dateTo) libraryParameters.set("date_to", libraryQuery.dateTo);
    if (libraryQuery.search.trim()) libraryParameters.set("search", libraryQuery.search.trim());
    if (libraryQuery.albumId && libraryQuery.collapseGroups) libraryParameters.set("collapse_groups", "true");
    const results = await Promise.allSettled([
      getJson<Overview>("/api/overview"),
      getJson<LibraryCapturesResponse>(`/api/library/captures?${libraryParameters.toString()}`),
      getJson<LibraryFilters>("/api/library/filters"),
      getJson<EventsResponse>(`/api/albums?limit=${albumPageSize}&offset=${albumOffset}`),
      getJson<AnalysisOverview>("/api/analysis/overview"),
      getJson<AiPreflight>("/api/ai/preflight"),
      getJson<QualityResponse>(`/api/quality?${new URLSearchParams({ limit: String(qualityPageSize), offset: String(qualityOffset), review_filter: qualityFilter, ...(qualitySearch.trim() ? { search: qualitySearch.trim() } : {}), ...(qualityAlbumId ? { album_id: qualityAlbumId } : {}) }).toString()}`),
      getJson<SimilarityGroupsResponse>(similarityGroupsUrl(groupPageSize, groupOffset, groupReviewFilter, groupAlbumId)),
      getJson<Statistics>("/api/statistics"),
      getJson<EquipmentCatalog>("/api/equipment"),
      getJson<ArchiveStatus>("/api/archive/status"),
      getJson<ArchiveStatus>("/api/active-library/baseline/status"),
      getJson<LightroomStatus>("/api/lightroom/status"),
      getJson<SystemCapabilities>("/api/system/capabilities"),
      getJson<SettingsStatus>("/api/settings"),
    ] as const);
    if (requestSequence !== refreshSequence.current) return;
    const [overviewData, libraryData, filterData, eventData, analysisData, preflightData, qualityData, groupData, statisticsData, equipmentData, archiveData, activeBaselineData, lightroomData, capabilitiesData, settingsData] = results;
    if (overviewData.status === "fulfilled") setOverview(overviewData.value);
    if (libraryData.status === "fulfilled") setLibraryCaptures(libraryData.value);
    if (filterData.status === "fulfilled") setLibraryFilters(filterData.value);
    if (eventData.status === "fulfilled") setEvents(eventData.value);
    if (analysisData.status === "fulfilled") setAnalysis(analysisData.value);
    if (preflightData.status === "fulfilled") setAiPreflight(preflightData.value);
    if (qualityData.status === "fulfilled") setQuality(qualityData.value);
    if (groupData.status === "fulfilled") setSimilarityGroups(groupData.value);
    if (statisticsData.status === "fulfilled") setStatistics(statisticsData.value);
    if (equipmentData.status === "fulfilled") setEquipment(equipmentData.value);
    if (archiveData.status === "fulfilled") setArchive(archiveData.value);
    if (activeBaselineData.status === "fulfilled") setActiveLibraryBaseline(activeBaselineData.value);
    if (lightroomData.status === "fulfilled") setLightroomStatus(lightroomData.value);
    if (capabilitiesData.status === "fulfilled") setCapabilities(capabilitiesData.value);
    if (settingsData.status === "fulfilled") setSettingsStatus(settingsData.value);
    const failed = results.find((result) => result.status === "rejected");
    if (failed?.status === "rejected") setError(failed.reason instanceof Error ? failed.reason.message : String(failed.reason));
  }, [albumOffset, albumPageSize, groupAlbumId, groupOffset, groupPageSize, groupReviewFilter, libraryOffset, libraryQuery, qualityAlbumId, qualityFilter, qualityOffset, qualityPageSize, qualitySearch]);

  useEffect(() => {
    Promise.all([refreshLibrary(), getJson<Task>("/api/tasks/current").then((result) => setTask(taskForDisplay(result)))]).catch(
      (reason: Error) => setError(reason.message),
    );
    // Initial full snapshot only. Page filters have scoped effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const parameters = new URLSearchParams({
        limit: String(libraryQuery.pageSize), offset: String(libraryOffset), sort: libraryQuery.sort,
      });
      if (libraryQuery.albumId === "__unassigned__") parameters.set("unassigned", "true");
      else if (libraryQuery.albumId) parameters.set("album_id", libraryQuery.albumId);
      if (libraryQuery.category) parameters.set("category", libraryQuery.category);
      if (libraryQuery.camera) parameters.set("camera_model", libraryQuery.camera);
      if (libraryQuery.lens) parameters.set("lens_model", libraryQuery.lens);
      if (libraryQuery.rating) parameters.set("rating", libraryQuery.rating);
      if (libraryQuery.selection) parameters.set("selection", libraryQuery.selection);
      if (libraryQuery.quality) parameters.set("quality", libraryQuery.quality);
      if (libraryQuery.tagSubject) parameters.set("tag_subject", libraryQuery.tagSubject);
      if (libraryQuery.tagStatus) parameters.set("tag_status", libraryQuery.tagStatus);
      if (libraryQuery.tagProblem) parameters.set("tag_problem", libraryQuery.tagProblem);
      if (libraryQuery.tagLocation) parameters.set("tag_location", libraryQuery.tagLocation);
      if (libraryQuery.selectionReason) parameters.set("selection_reason", libraryQuery.selectionReason);
      if (libraryQuery.modelProblem) parameters.set("model_problem", libraryQuery.modelProblem);
      if (libraryQuery.dateFrom) parameters.set("date_from", libraryQuery.dateFrom);
      if (libraryQuery.dateTo) parameters.set("date_to", libraryQuery.dateTo);
      if (libraryQuery.search.trim()) parameters.set("search", libraryQuery.search.trim());
      if (libraryQuery.albumId && libraryQuery.collapseGroups) parameters.set("collapse_groups", "true");
      getJson<LibraryCapturesResponse>(`/api/library/captures?${parameters}`, { signal: controller.signal })
        .then(setLibraryCaptures)
        .catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    }, libraryQuery.search ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [libraryOffset, libraryQuery]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<EventsResponse>(`/api/albums?limit=${albumPageSize}&offset=${albumOffset}`, { signal: controller.signal })
      .then(setEvents).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [albumOffset, albumPageSize]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      const parameters = new URLSearchParams({ limit: String(qualityPageSize), offset: String(qualityOffset), review_filter: qualityFilter });
      if (qualitySearch.trim()) parameters.set("search", qualitySearch.trim());
      if (qualityAlbumId) parameters.set("album_id", qualityAlbumId);
      getJson<QualityResponse>(`/api/quality?${parameters}`, { signal: controller.signal })
        .then(setQuality).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    }, qualitySearch ? 250 : 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [qualityAlbumId, qualityFilter, qualityOffset, qualityPageSize, qualitySearch]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<SimilarityGroupsResponse>(similarityGroupsUrl(groupPageSize, groupOffset, groupReviewFilter, groupAlbumId), { signal: controller.signal })
      .then(setSimilarityGroups).catch((reason: Error) => { if (reason.name !== "AbortError") setError(reason.message); });
    return () => controller.abort();
  }, [groupAlbumId, groupOffset, groupPageSize, groupReviewFilter]);

  useEffect(() => {
    if (task?.status !== "running") return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getJson<Task>("/api/tasks/current");
        setTask(next);
        if (next.status !== "running") await refreshLibrary();
      } catch (reason) {
        setError((reason as Error).message);
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [task?.status, refreshLibrary]);

  useEffect(() => {
    if (task?.status !== "complete" && task?.status !== "cancelled") return;
    const completedId = task.id;
    const timer = window.setTimeout(() => {
      window.localStorage.setItem("tangerine-task-receipt", taskReceipt(task));
      setTask((current) => current?.id === completedId && (current.status === "complete" || current.status === "cancelled")
        ? { ...current, status: "idle", stage: "idle", message: "等待任务" }
        : current);
    }, 8000);
    return () => window.clearTimeout(timer);
  }, [task?.id, task?.status]);

  const startScan = async (albumId?: number) => {
    if (!albumId) return;
    setError(null);
    try {
      setTask(await getJson<Task>("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ album_id: albumId }),
      }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const cancelTask = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/tasks/current/cancel", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startVisual = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/visual/analyze", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startQuality = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/quality/analyze", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startDetailBackfill = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/detail-data/backfill", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const resumeDetailBackfill = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/detail-data/backfill/resume", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const startAi = async (mode: "benchmark" | "recommended", limit: number) => {
    if (mode === "recommended" && !window.confirm(`将分析最多 ${limit} 张推荐照片。任务可暂停、继续和取消，确认现在加载本地模型吗？`)) return;
    setError(null);
    try {
      setTask(await getJson<Task>("/api/ai/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, limit }),
      }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const pauseAi = async () => {
    setError(null);
    try {
      setTask(await getJson<Task>("/api/ai/runs/current/pause", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const pauseTask = async () => {
    if (!task?.stage.startsWith("detail-")) {
      await pauseAi();
      return;
    }
    setError(null);
    try {
      setTask(await getJson<Task>("/api/detail-data/backfill/pause", { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const resumeAi = async (runId: number) => {
    setError(null);
    try {
      setTask(await getJson<Task>(`/api/ai/runs/${runId}/resume`, { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const retryAiFailures = async (runId: number) => {
    setError(null);
    try {
      setTask(await getJson<Task>(`/api/ai/runs/${runId}/retry-failures`, { method: "POST" }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const applyReview = useCallback((captureId: number, review: ReviewPayload) => {
    const patchQuality = (item: QualityItem) => item.capture_id === captureId ? {
      ...item,
      user_rating: review.user_rating,
      user_pick: Number(review.user_pick),
      user_reject: Number(review.user_reject),
      user_note: review.user_note,
      selection_reasons: review.selection_reasons ?? item.selection_reasons,
    } : item;
    const patchGroup = (item: GroupCapture) => item.capture_id === captureId ? {
      ...item,
      user_rating: review.user_rating,
      user_pick: Number(review.user_pick),
      user_reject: Number(review.user_reject),
      user_note: review.user_note,
      selection_reasons: review.selection_reasons ?? item.selection_reasons,
    } : item;
    setQuality((current) => current ? { ...current, items: current.items.map(patchQuality) } : current);
    setSelectedGroup((current) => current ? { ...current, items: current.items.map(patchGroup) } : current);
    setLibraryCaptures((current) => current ? {
      ...current,
      items: current.items.map((item) => item.id === captureId ? {
        ...item,
        user_rating: review.user_rating,
        user_pick: Number(review.user_pick),
        user_reject: Number(review.user_reject),
        user_note: review.user_note,
      } : item),
    } : current);
    setCaptureDetail((current) => current && current.id === captureId ? {
      ...current,
      user_rating: review.user_rating,
      user_pick: Number(review.user_pick),
      user_reject: Number(review.user_reject),
      user_note: review.user_note,
      selection_reasons: review.selection_reasons ?? current.selection_reasons,
    } : current);
  }, []);

  const scheduleReviewAggregateRefresh = () => {
    if (reviewAggregateTimer.current != null) window.clearTimeout(reviewAggregateTimer.current);
    reviewAggregateTimer.current = window.setTimeout(() => {
      Promise.all([
        getJson<Overview>("/api/overview"),
        getJson<Statistics>("/api/statistics"),
        getJson<LightroomStatus>("/api/lightroom/status"),
        getJson<SimilarityGroupsResponse>(similarityGroupsUrl(groupPageSize, groupOffset, groupReviewFilter, groupAlbumId)),
      ]).then(([nextOverview, nextStatistics, nextLightroom, nextGroups]) => {
        setOverview(nextOverview);
        setStatistics(nextStatistics);
        setLightroomStatus(nextLightroom);
        setSimilarityGroups(nextGroups);
      }).catch((reason: Error) => setError(reason.message));
    }, 250);
  };

  const saveReview = async (captureId: number, review: ReviewPayload) => {
    applyReview(captureId, review);
    setSimilarityGroups((current) => {
      if (!current || !selectedGroup?.items.some((item) => item.capture_id === captureId)) return current;
      const pickCount = selectedGroup.items.reduce((total, item) => total + Number(
        item.capture_id === captureId ? review.user_pick : Boolean(item.user_pick),
      ), 0);
      const rejectCount = selectedGroup.items.reduce((total, item) => total + Number(
        item.capture_id === captureId ? review.user_reject : Boolean(item.user_reject),
      ), 0);
      const status = pickCount
        ? "picked" as const
        : rejectCount >= selectedGroup.items.length ? "skipped" as const : "pending" as const;
      const before = current.items.find((item) => item.id === selectedGroup.id);
      const pendingDelta = before
        ? Number(status === "pending") - Number(before.review_status === "pending")
        : 0;
      return {
        ...current,
        pending_count: current.pending_count + pendingDelta,
        items: current.items.map((item) => item.id === selectedGroup.id
          ? { ...item, pick_count: pickCount, reject_count: rejectCount, review_status: status }
          : item),
      };
    });
    const version = (reviewVersions.current.get(captureId) ?? 0) + 1;
    reviewVersions.current.set(captureId, version);
    const previousRequest = reviewQueues.current.get(captureId) ?? Promise.resolve();
    const request = previousRequest.catch(() => undefined).then(async () => {
      try {
        await getJson(`/api/reviews/${captureId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(review),
        });
        if (reviewVersions.current.get(captureId) === version) {
          pushToast("success", "已保存评价");
          scheduleReviewAggregateRefresh();
        }
      } catch (reason) {
        if (reviewVersions.current.get(captureId) === version) {
          pushToast("error", `保存失败：${(reason as Error).message}`);
          await refreshLibrary();
        }
      }
    });
    reviewQueues.current.set(captureId, request);
    void request.finally(() => {
      if (reviewQueues.current.get(captureId) === request) reviewQueues.current.delete(captureId);
    });
  };

  const saveAiReview = async (analysisId: number, verdict: "accurate" | "partial" | "inaccurate" | null, note: string | null) => {
    setError(null);
    try {
      const saved = await getJson<{ user_verdict: "accurate" | "partial" | "inaccurate" | null; user_note: string | null; reviewed_at: string | null }>(`/api/ai/analyses/${analysisId}/review`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_verdict: verdict, user_note: note }),
      });
      setCaptureDetail((current) => current ? {
        ...current,
        ai_analyses: current.ai_analyses.map((item) => item.id === analysisId ? { ...item, ...saved } : item),
      } : current);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const openGroup = async (groupId: number) => {
    setError(null);
    try {
      setSelectedGroup(await getJson<SimilarityGroupDetail>(`/api/similarity-groups/${groupId}`));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const saveCaptureTags = async (
    captureId: number,
    tags: Array<{ dimension: CaptureTagDimension; name: string }>,
  ) => {
    setError(null);
    try {
      const saved = await getJson<Pick<CaptureDetail, "tags">>(`/api/captures/${captureId}/tags`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tags }),
      });
      setCaptureDetail((current) => current && current.id === captureId ? { ...current, tags: saved.tags } : current);
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const batchTagCaptures = async (
    captureIds: number[],
    dimension: CaptureTagDimension,
    name: string,
    action: "add" | "remove",
  ) => {
    setError(null);
    try {
      const saved = await getJson<{ affected_count: number }>("/api/captures/tags/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capture_ids: captureIds, dimension, name, action }),
      });
      await refreshLibrary();
      pushToast("success", `${action === "add" ? "已标记" : "已移除"} ${saved.affected_count} 张照片`);
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const restoreGroupingRevision = async (revisionId: number, useBefore = false) => {
    setError(null);
    try {
      await getJson(`/api/similarity-group-revisions/${revisionId}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ use_before: useBefore }),
      });
      setSelectedGroup(null);
      await refreshLibrary();
      pushToast("success", useBefore ? "已撤销本次分组调整" : "已恢复所选分组版本");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const editGrouping = async (captureId: number, action: "exclude" | "split_before" | "auto") => {
    setError(null);
    try {
      const result = await getJson<{ revision_id?: number }>(`/api/captures/${captureId}/similarity-override`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      setSelectedGroup(null);
      await refreshLibrary();
      if (result.revision_id) pushToast("success", action === "auto" ? "已恢复自动识别" : "分组已更新", "撤销", () => void restoreGroupingRevision(result.revision_id!, true));
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const saveGrouping = async (groupId: number, groups: number[][], excludedIds: number[]) => {
    setError(null);
    try {
      const result = await getJson<{ revision_id: number; group_ids: number[] }>("/api/similarity-groups/manual", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_group_id: groupId, groups, excluded_ids: excludedIds }),
      });
      setGroupOffset(0);
      await refreshLibrary();
      if (result.group_ids[0]) {
        setSelectedGroup(await getJson<SimilarityGroupDetail>(`/api/similarity-groups/${result.group_ids[0]}`));
      } else {
        setSelectedGroup(null);
      }
      const groupLabel = result.group_ids.length ? `已保存为 ${result.group_ids.length} 个相似组，正在显示第一组` : "照片已作为普通单张移出相似组";
      pushToast("success", groupLabel, "撤销", () => void restoreGroupingRevision(result.revision_id, true));
      return result;
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const openLibraryWith = (changes: Partial<LibraryQuery>) => {
    setLibraryLandingSection("photos");
    setLibraryOffset(0);
    setLibraryCaptures(null);
    setLibraryQuery((current) => ({ ...current, albumId: "", category: "", camera: "", lens: "", rating: "", selection: "", quality: "", tagSubject: "", tagStatus: "", tagProblem: "", tagLocation: "", selectionReason: "", modelProblem: "", dateFrom: "", dateTo: "", search: "", ...changes }));
    setView("library");
  };

  const openCapture = async (captureId: number, context?: number[]) => {
    setError(null);
    try {
      setCaptureDetail(await getJson<CaptureDetail>(`/api/captures/${captureId}`));
      if (context) setDetailContext(context);
      else setDetailContext((current) => current.includes(captureId) ? current : []);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const navigateDetail = async (direction: 1 | -1) => {
    if (!captureDetail || !detailContext.length) return;
    const index = detailContext.indexOf(captureDetail.id);
    if (index < 0) return;
    const nextId = detailContext[index + direction];
    if (nextId == null) return;
    try {
      setCaptureDetail(await getJson<CaptureDetail>(`/api/captures/${nextId}`));
    } catch (reason) {
      pushToast("error", (reason as Error).message);
    }
  };

  const createBaseline = async () => {
    if (!window.confirm("建立新的原片逻辑基线？这只记录当前索引，不读取、复制或修改照片。")) return;
    setError(null);
    try {
      await getJson("/api/archive/baselines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setArchive(await getJson<ArchiveStatus>("/api/archive/status"));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const createActiveBaseline = async () => {
    if (!window.confirm("为当前活动图库建立新的逻辑基线？这不会读取文件内容或修改照片。")) return;
    setError(null);
    try {
      await getJson("/api/active-library/baselines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      setActiveLibraryBaseline(await getJson<ArchiveStatus>("/api/active-library/baseline/status"));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const checkIntegrity = async (scope: "archive" | "active") => {
    setError(null);
    try {
      const result = await getJson<ArchiveStatus>(`/api/integrity/check/${scope}`, { method: "POST" });
      if (scope === "archive") setArchive(result);
      else setActiveLibraryBaseline(result);
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const updateEvent = async (event: EventItem, changes: Partial<Pick<EventItem, "proposed_name" | "category" | "status" | "equipment_keys" | "equipment_count">>) => {
    setError(null);
    const next = { ...event, ...changes };
    try {
      await getJson(`/api/albums/${event.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposed_name: next.proposed_name, category: next.category, status: next.status, ...(changes.equipment_keys ? { accessory_keys: changes.equipment_keys } : {}) }),
      });
      setEvents((current) => current ? { ...current, items: current.items.map((item) => item.id === event.id ? next : item) } : current);
      setLightroomStatus((current) => current ? { ...current, confirmed_events: current.confirmed_events + (event.status !== "confirmed" && next.status === "confirmed" ? 1 : event.status === "confirmed" && next.status !== "confirmed" ? -1 : 0) } : current);
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const createAlbum = async (name: string, category: string): Promise<number | null> => {
    setError(null);
    try {
      const created = await getJson<{ id: number }>("/api/albums", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, category }),
      });
      setAlbumOffset(0);
      await refreshLibrary();
      return created.id;
    } catch (reason) {
      setError((reason as Error).message);
      return null;
    }
  };

  const createAlbumType = async (name: string) => {
    setError(null);
    try {
      await getJson("/api/album-types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const deleteAlbumType = async (name: string) => {
    setError(null);
    try {
      await getJson(`/api/album-types/${encodeURIComponent(name)}`, { method: "DELETE" });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const renameAlbumType = async (name: string, nextName: string) => {
    setError(null);
    try {
      await getJson(`/api/album-types/${encodeURIComponent(name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName }),
      });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const assignToAlbum = async (albumId: number, captureIds: number[]) => {
    setError(null);
    try {
      await getJson(`/api/albums/${albumId}/captures`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capture_ids: captureIds }),
      });
      await refreshLibrary();
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const generateManifest = async (scope: LightroomManifestScope, albumId?: number) => {
    setError(null);
    try {
      setLightroomManifest(await getJson<LightroomManifest>("/api/lightroom/manifest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scope, album_id: albumId ?? null }) }));
    } catch (reason) {
      setError((reason as Error).message);
    }
  };

  const saveSettings = async (next: EditableSettings) => {
    setError(null);
    try {
      const result = await getJson<SettingsStatus>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next),
      });
      setSettingsStatus(result);
      pushToast("success", "配置已保存，重启应用后生效");
      return result;
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const changeEquipmentOwnership = async (kind: "camera" | "lens" | "accessory", key: string, owned: boolean) => {
    setError(null);
    try {
      const result = await getJson<EquipmentCatalog>("/api/equipment/ownership", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, key, owned }),
      });
      setEquipment(result);
      pushToast("success", owned ? "已加入我的设备" : "已标记为未拥有");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const saveEquipmentItem = async (draft: EquipmentDraft) => {
    setError(null);
    try {
      const payload = {
        ...draft,
        filter_thread_mm: draft.filter_thread_mm ? Number(draft.filter_thread_mm) : null,
        thread_mm: draft.thread_mm ? Number(draft.thread_mm) : null,
      };
      const result = await getJson<EquipmentCatalog>("/api/equipment/items", {
        method: draft.key ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setEquipment(result);
      pushToast("success", draft.key ? "设备信息已更新" : "设备已添加");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const deleteEquipmentItem = async (kind: EquipmentKind, item: EquipmentItem) => {
    setError(null);
    try {
      const result = await getJson<EquipmentCatalog>("/api/equipment/items", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, key: item.inventory_key }),
      });
      setEquipment(result);
      pushToast("success", "设备已从管理清单移除");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const changeEquipmentVisibility = async (kind: EquipmentKind, item: EquipmentItem, visible: boolean) => {
    setError(null);
    try {
      const result = await getJson<EquipmentCatalog>("/api/equipment/visibility", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, key: item.inventory_key, visible }),
      });
      setEquipment(result);
      pushToast("success", visible ? "设备已恢复显示" : "设备已隐藏，可在页面底部恢复");
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const exportPhoneShare = async (captureIds: number[], maxEdge: number) => {
    setError(null);
    try {
      return await getJson<PhoneShareExport>("/api/exports/phone-share", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capture_ids: captureIds, max_edge: maxEdge, quality: 90 }),
      });
    } catch (reason) {
      setError((reason as Error).message);
      throw reason;
    }
  };

  const pageMeta = {
    home: ["OVERVIEW", "首页概览", ""],
    library: ["LIBRARY", "照片图库", "浏览、整理并管理全部拍摄单元"],
    bursts: ["REVIEW", "连拍选片", "比较连拍与相似画面，留下真正需要的版本"],
    analysis: ["ANALYSIS / REVIEW", "质量分析", "批量运行技术检测与本地模型，在单张详情中复核结果"],
    statistics: ["STATISTICS", "摄影统计", "从器材、参数和选片结果理解拍摄习惯"],
    equipment: ["EQUIPMENT", "设备管理", "器材档案与实际使用统计"],
    lightroom: ["OUTPUT", "后期输出", "检查评分与相册后生成 Lightroom 只读准备清单"],
    archive: ["SYSTEM / MAINTENANCE", "系统维护", "按需检查活动图库与历史存档完整性"],
    settings: ["SETTINGS", "应用设置", "随时调整目录与本地能力；保存不会移动任何照片或数据库"],
  }[view];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">T</span><div><strong>Tangerine</strong><span>Photo Assistant</span></div></div>
        <nav aria-label="主要功能">
          <span className="nav-group-label">照片管理</span>
          <button className={`nav-item ${view === "home" ? "active" : ""}`} onClick={() => setView("home")}><span>首</span>首页概览</button>
          <button className={`nav-item ${view === "library" ? "active" : ""}`} onClick={() => { setLibraryLandingSection("photos"); setView("library"); }}><span>图</span>照片图库</button>
          <button className={`nav-item ${view === "bursts" ? "active" : ""}`} onClick={() => setView("bursts")}><span>选</span>连拍选片</button>
          <span className="nav-group-label system-label">分析学习</span>
          <button className={`nav-item ${view === "analysis" ? "active" : ""}`} onClick={() => setView("analysis")}><span>析</span>质量分析</button>
          <button className={`nav-item ${view === "statistics" ? "active" : ""}`} onClick={() => setView("statistics")}><span>统</span>摄影统计</button>
          <span className="nav-group-label system-label">工具</span>
          <button className={`nav-item ${view === "equipment" ? "active" : ""}`} onClick={() => setView("equipment")}><span>器</span>设备管理</button>
          <button className={`nav-item ${view === "lightroom" ? "active" : ""}`} onClick={() => setView("lightroom")}><span>出</span>后期输出</button>
          <span className="nav-group-label system-label">系统</span>
          <button className={`nav-item ${view === "archive" ? "active" : ""}`} onClick={() => setView("archive")}><span>维</span>系统维护</button>
          <button className={`nav-item ${view === "settings" ? "active" : ""}`} onClick={() => setView("settings")}><span>设</span>应用设置</button>
        </nav>
        <div className="privacy-note"><span className="status-dot" /><div><strong>本地离线</strong><small>照片与人脸数据不离开电脑</small></div></div>
      </aside>

      <main>
        <header className="topbar">
          <div><span className="eyebrow">{pageMeta[0]}</span><h1>{pageMeta[1]}</h1></div>
          <div className="topbar-tools">
            <button className="theme-toggle" onClick={() => setTheme((current) => current === "light" ? "dark" : "light")} aria-label={`切换到${theme === "light" ? "深色" : "浅色"}主题`}>
              <span aria-hidden="true">{theme === "light" ? "☀" : "◐"}</span>
              {theme === "light" ? "浅色" : "深色"}
            </button>
            <div className="scan-meta"><span>上次扫描</span><strong>{formatDate(overview?.latest_scan?.finished_at)}</strong></div>
          </div>
        </header>
        {error && <div className="error-banner" role="alert">{error}</div>}
        {view === "home" && <HomeView overview={overview} statistics={statistics} archive={archive} activeBaseline={activeLibraryBaseline} library={libraryCaptures} filters={libraryFilters} similarity={similarityGroups} task={task} capabilities={capabilities} openPhotos={() => { setLibraryLandingSection("photos"); setView("library"); }} openAlbums={() => { setLibraryLandingSection("albums"); setView("library"); }} openAlbum={(albumId) => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: String(albumId), collapseGroups: true })); setView("library"); }} openBursts={() => setView("bursts")} openStatistics={() => setView("statistics")} continueLabel={({ library: "照片图库", bursts: "相似组选片", analysis: "质量分析", statistics: "摄影统计", equipment: "设备管理", lightroom: "后期输出", archive: "系统维护", settings: "应用设置", home: "首页概览" } as Record<View, string>)[lastWorkspaceView]} continueWork={() => setView(lastWorkspaceView)} openUnassigned={() => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: "__unassigned__", collapseGroups: false })); setView("library"); }} openMaintenance={() => setView("archive")} openCapture={openCapture} />}
        {view === "library" && <LibraryView
          overview={overview} library={libraryCaptures} albums={events} filters={libraryFilters} equipment={equipment} query={libraryQuery}
          requestedSection={libraryLandingSection}
          updateQuery={(changes) => { setLibraryOffset(0); setLibraryCaptures(null); setLibraryQuery((current) => ({ ...current, ...changes })); }}
          task={task} startScan={startScan} cancelTask={cancelTask} updateAlbum={updateEvent}
          createAlbum={createAlbum} createAlbumType={createAlbumType} renameAlbumType={renameAlbumType} deleteAlbumType={deleteAlbumType} assignToAlbum={assignToAlbum} batchTag={batchTagCaptures}
          openCapture={openCapture} selectedGroup={selectedGroup} openGroup={openGroup} closeGroup={() => setSelectedGroup(null)} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} restoreGroupingRevision={restoreGroupingRevision} exportPhotos={exportPhoneShare} changePage={setLibraryOffset}
          changePageSize={(limit) => { setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, pageSize: limit })); }}
          changeAlbumPage={setAlbumOffset} changeAlbumPageSize={(limit) => { setAlbumOffset(0); setAlbumPageSize(limit); }}
          openAlbumBursts={(albumId) => { setGroupOffset(0); setGroupReviewFilter("pending"); setGroupAlbumId(String(albumId)); setSelectedGroup(null); setView("bursts"); }}
          openAlbumQuality={(albumId) => { setQualityOffset(0); setQualityAlbumId(String(albumId)); setView("analysis"); }}
        />}
        {view === "bursts" && <BurstsView groups={similarityGroups} selectedGroup={selectedGroup} task={task} startVisual={startVisual} openGroup={openGroup} closeGroup={() => setSelectedGroup(null)} openCapture={openCapture} saveReview={saveReview} editGrouping={editGrouping} saveGrouping={saveGrouping} restoreGroupingRevision={restoreGroupingRevision} cancelTask={cancelTask} changeGroupPage={setGroupOffset} changeGroupPageSize={(limit) => { setGroupOffset(0); setGroupPageSize(limit); }} reviewFilter={groupReviewFilter} setReviewFilter={(filter) => { setGroupOffset(0); setGroupReviewFilter(filter); }} albumId={groupAlbumId} setAlbumId={(albumId) => { setGroupOffset(0); setSelectedGroup(null); setGroupReviewFilter("pending"); setGroupAlbumId(albumId); }} openAlbumPhotos={(albumId) => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: String(albumId), collapseGroups: true })); setView("library"); }} openAlbumQuality={(albumId) => { setQualityOffset(0); setQualityAlbumId(String(albumId)); setView("analysis"); }} />}
        {view === "analysis" && <AnalysisView analysis={analysis} preflight={aiPreflight} quality={quality} qualityFilter={qualityFilter} qualitySearch={qualitySearch} setQualityFilter={(filter) => { setQualityOffset(0); setQualityFilter(filter); }} setQualitySearch={(search) => { setQualityOffset(0); setQualitySearch(search); }} qualityAlbumId={qualityAlbumId} setQualityAlbumId={(albumId) => { setQualityOffset(0); setQualityAlbumId(albumId); }} openAlbumPhotos={(albumId) => { setLibraryLandingSection("photos"); setLibraryOffset(0); setLibraryQuery((current) => ({ ...current, albumId: String(albumId), collapseGroups: true })); setView("library"); }} openAlbumBursts={(albumId) => { setGroupOffset(0); setGroupReviewFilter("pending"); setGroupAlbumId(String(albumId)); setSelectedGroup(null); setView("bursts"); }} task={task} startQuality={startQuality} startDetailBackfill={startDetailBackfill} resumeDetailBackfill={resumeDetailBackfill} startAi={startAi} saveReview={saveReview} cancelTask={cancelTask} pauseTask={pauseTask} resumeAi={resumeAi} retryAiFailures={retryAiFailures} openCapture={openCapture} changeQualityPage={setQualityOffset} changeQualityPageSize={(limit) => { setQualityOffset(0); setQualityPageSize(limit); }} />}
        {view === "statistics" && <StatisticsView statistics={statistics} openLibraryWith={openLibraryWith} />}
        {view === "equipment" && <EquipmentView equipment={equipment} changeOwnership={changeEquipmentOwnership} saveItem={saveEquipmentItem} deleteItem={deleteEquipmentItem} changeVisibility={changeEquipmentVisibility} />}
        {view === "archive" && <ArchiveView archive={archive} activeLibrary={activeLibraryBaseline} createBaseline={createBaseline} createActiveBaseline={createActiveBaseline} checkIntegrity={checkIntegrity} />}
        {view === "lightroom" && <LightroomView status={lightroomStatus} manifest={lightroomManifest} capabilities={capabilities} albums={libraryFilters?.albums ?? []} generateManifest={generateManifest} />}
        {view === "settings" && <SettingsView status={settingsStatus} task={task} save={saveSettings} />}
        {captureDetail && (() => { const detailIndex = detailContext.indexOf(captureDetail.id); return <CaptureDetailPanel detail={captureDetail} close={() => setCaptureDetail(null)} saveAiReview={saveAiReview} saveReview={saveReview} saveTags={saveCaptureTags} navigate={(direction) => void navigateDetail(direction)} hasPrev={detailIndex > 0} hasNext={detailIndex >= 0 && detailIndex < detailContext.length - 1} />; })()}
        <div className="toast-stack" aria-live="polite">
          {toasts.map((toast) => <div key={toast.id} className={`toast ${toast.kind}`}><span>{toast.message}</span>{toast.action && <button onClick={() => { toast.action?.(); setToasts((current) => current.filter((item) => item.id !== toast.id)); }}>{toast.actionLabel}</button>}</div>)}
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
