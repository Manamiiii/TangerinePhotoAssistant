export type AiRun = {
  id: number;
  mode: string;
  model_id: string;
  prompt_version: string;
  status: string;
  requested_count: number;
  completed_count: number;
  failed_count: number;
  processed_count: number;
  success_rate: number | null;
  average_seconds_per_photo: number | null;
  throughput_per_hour: number | null;
  estimated_remaining_seconds: number | null;
  total_attempts: number;
  max_attempts: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  report_available?: boolean;
  backup_count?: number;
  latest_backup_at?: string | null;
};

export type AiFailure = {
  id: number;
  capture_id: number;
  stem: string;
  status: string;
  selection_reason: string;
  attempt_count: number;
  error: string | null;
};

export type AiResultAudit = {
  prompt_version: string;
  last_analysis_id: number;
  result_count: number;
  parse_errors: number;
  schema_errors: number;
  unsafe_action_mentions: number;
  with_visible_problems: number;
  with_shooting_advice: number;
  with_lightroom_suggestions: number;
  photoshop_needed: number;
  empty_photoshop_reason: number;
  overconfident: number;
  risk_count: number;
  pending_audit_metadata: number;
  reviewed: number;
  timed_count: number;
  verdicts: { accurate: number; partial: number; inaccurate: number };
  average_confidence: number | null;
  average_seconds_per_photo: number | null;
};

export type AiRecentResult = {
  id: number;
  capture_id: number;
  model_id: string;
  prompt_version: string;
  finished_at: string;
  user_verdict: "accurate" | "partial" | "inaccurate" | null;
  stem: string;
  event_name: string | null;
  category: string | null;
  technical_score: number | null;
  subject_type: string | null;
  quality_summary: string | null;
  visible_problem_count: number;
  overall_confidence: number | null;
  photoshop_needed: boolean;
  thumbnail_url: string;
  review_flags?: string[];
  workflow_status?: WorkItemStatus;
  workflow_due_at?: string | null;
  workflow_reviewed_at?: string | null;
  workflow_first_seen_at?: string | null;
  workflow_age_days?: number | null;
};

export type AiResultsResponse = {
  count: number;
  limit: number;
  offset: number;
  items: AiRecentResult[];
};

export type AiPreflight = {
  ready: boolean;
  blockers: string[];
  warnings: string[];
  model_path: string | null;
  model_file_count: number;
  model_bytes: number;
  quantization: string;
  gpu_memory_limit_gb: number;
  image_max_edge?: number;
  database_bytes: number;
  backup_root: string;
  backup_free_bytes: number;
  competing_processes: string[];
};

export type GpuStatus = {
  available: boolean;
  name?: string;
  utilization_percent?: number;
  memory_used_mb?: number;
  memory_total_mb?: number;
  temperature_c?: number;
  message?: string;
};

export type AnalysisOverview = {
  quality: {
    analyzed: number;
    errors: number;
    average_score: number | null;
    flagged: number;
    recommended_picks: number;
    ratings: Array<{ rating: number; count: number }>;
  };
  ai: {
    completed_analysis_count: number;
    analyzed_capture_count: number;
    latest_run: AiRun | null;
    recent_runs: AiRun[];
    latest_failures: AiFailure[];
    result_audit: { versions: AiResultAudit[]; latest: AiResultAudit | null };
    recent_results: AiRecentResult[];
    candidates: { benchmark_available: number; recommended_available: number } | null;
  };
  runtime: { ready: boolean; message: string };
  subject_tags: {
    eligible_captures: number;
    tagged_captures: number;
    subject_count: number;
    tag_links: number;
  };
  detail_data: { metadata_profile_version: number; metadata_pending: number; histograms_pending: number };
};

export type QualityItem = {
  capture_id: number;
  stem: string;
  captured_at: string | null;
  event_id: number;
  event_name: string;
  category: string;
  technical_score: number;
  exposure_score: number;
  sharpness_score: number;
  exif_score: number;
  auto_rating: number | null;
  auto_pick: number;
  similarity_rank: number | null;
  user_rating: number | null;
  user_pick: number | null;
  user_reject: number;
  user_note: string | null;
  selection_reasons?: string[];
  thumbnail_url: string;
  has_error: boolean;
  issues: Array<{ code: string; severity: string; message: string }>;
  workflow_status: WorkItemStatus;
  workflow_due_at: string | null;
  workflow_reviewed_at: string | null;
  workflow_first_seen_at: string | null;
  workflow_age_days: number | null;
  ai_result: {
    subject_type?: string;
    quality_summary?: string;
    photoshop_needed?: boolean;
    shooting_advice?: Array<{ suggestion?: string; reason?: string }>;
    lightroom_suggestions?: Array<{ adjustment?: string; direction?: string; reason?: string }>;
  } | null;
};
export type QualityAlbumSummary = { id: number; name: string; category: string; analyzed_count: number; problem_count: number; model_count: number };
export type QualityResponse = { count: number; limit: number; offset: number; items: QualityItem[]; albums: QualityAlbumSummary[] };
export type QualityReviewFilter = "all" | "problems" | "errors" | "low_score" | "with_model" | "without_model" | "unrated";
export type WorkItemStatus = "new" | "reappeared" | "pending" | "confirmed" | "ignored" | "snoozed" | "resolved";
export type WorkItemFilter = "all" | "open" | WorkItemStatus;

export type ReviewPayload = {
  user_rating: number | null;
  user_pick: boolean;
  user_reject: boolean;
  user_note: string | null;
  selection_reasons?: string[];
};
