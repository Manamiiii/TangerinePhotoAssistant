export type SimilarityGroupItem = {
  id: number;
  capture_count: number;
  max_adjacent_hamming: number;
  start_at: string;
  end_at: string;
  event_id: number;
  event_name: string;
  category: string;
  average_score: number | null;
  recommended_capture_id: number | null;
  recommended_stem: string | null;
  cover_capture_id: number;
  pick_count: number;
  reject_count: number;
  confidence_level: "high" | "medium" | "low";
  pending_age_days: number | null;
  recommended_score: number | null;
  runner_up_score: number | null;
  review_status: "pending" | "picked" | "skipped";
  thumbnail_url: string;
};
export type SimilarityAlbumSummary = { id: number; name: string; category: string; total_count: number; pending_count: number };
export type SimilarityGroupsResponse = { count: number; limit: number; offset: number; items: SimilarityGroupItem[]; total_count: number; pending_count: number; estimated_review_minutes: number; estimate_basis: string; albums: SimilarityAlbumSummary[]; confidence_counts: Record<"high" | "medium" | "low", number> };
export type SimilarityReviewFilter = "all" | "pending" | "completed" | "adjusted";
export type SimilarityConfidenceFilter = "all" | "high" | "medium" | "low";
export type SimilarityAgeFilter = "all" | "recent" | "month" | "older";

export type SimilarityBatchPreview = {
  group_count: number;
  capture_count: number;
  audit_count: number;
  items: Array<SimilarityGroupItem & { score_margin: number }>;
};

export type SimilarityReviewBatch = {
  id: number; album_name: string | null; group_count: number; capture_count: number;
  status: "applied" | "undone"; created_at: string; undone_at: string | null;
  audit_count: number; pending_audit_count: number; can_undo: boolean;
};

export type SimilarityAuditItem = {
  batch_id: number; representative_capture_id: number; group_id: number | null;
  stem: string; album_name: string | null;
  audit_status: "pending" | "confirmed" | "problem";
  created_at: string; thumbnail_url: string;
};

export type GroupCapture = {
  capture_id: number;
  stem: string;
  captured_at: string | null;
  sequence_index: number;
  distance_from_previous: number | null;
  technical_score: number | null;
  exposure_score: number | null;
  sharpness_score: number | null;
  exif_score: number | null;
  auto_rating: number | null;
  auto_pick: number;
  similarity_rank: number | null;
  score_gap: number | null;
  recommendation_reason: string;
  recommendation_tier: "best" | "alternative" | "candidate" | "weak" | "unrated";
  balanced_rank: number | null;
  visual_difference: number | null;
  diversity_candidate: boolean;
  diversity_reason: string | null;
  user_rating: number | null;
  user_pick: number | null;
  user_reject: number;
  user_note: string | null;
  selection_reasons: string[];
  grouping_override: "exclude" | "split_before" | null;
  manual_batch_key: string | null;
  exposure_time: number | null;
  f_number: number | null;
  iso: number | null;
  focal_length_mm: number | null;
  camera_model: string | null;
  lens_model: string | null;
  issues: Array<{ code: string; severity: string; message: string }>;
  thumbnail_url: string;
};
export type SimilarityGroupDetail = {
  id: number;
  capture_count: number;
  max_adjacent_hamming: number;
  start_at: string;
  end_at: string;
  event_name: string;
  category: string;
  items: GroupCapture[];
  selection_session_id?: number;
};

export type SimilarityRevision = {
  id: number;
  operation: string;
  label: string;
  created_at: string;
  group_count: number;
  excluded_count: number;
  automatic: boolean;
  representative_capture_id: number;
  album_names: string[];
  can_undo: boolean;
};
