export type CountRow = { count: number } & Record<string, string | number | null>;

export type StructureSummary = {
  event_count: number;
  unconfirmed_event_count: number;
  unassigned_capture_count: number;
  categories: Array<{ category: string; event_count: number; capture_count: number }>;
  burst_count: number;
  captures_in_bursts: number;
  largest_burst: number;
};

export type Overview = {
  generated_at: string;
  files: { count: number; size_bytes: number };
  by_media_kind: CountRow[];
  pairing: Array<{ pairing_status: string; count: number }>;
  metadata: Array<{ metadata_status: string; count: number }>;
  cameras: Array<{ camera_make: string; camera_model: string; count: number }>;
  lenses: Array<{ lens_model: string; count: number }>;
  capture_total: number;
  dated_captures: number;
  structure: StructureSummary;
  visual: {
    duplicate_group_count: number;
    duplicate_file_count: number;
    duplicate_total_bytes: number;
    similarity_group_count: number;
    captures_in_similarity_groups: number;
    largest_similarity_group: number;
    fingerprint_count: number;
    fingerprint_error_count: number;
  };
  work_queue: {
    open_count: number;
    today_count: number;
    daily_limit: number;
    estimated_minutes: number;
    quality: { open_count: number; new_count: number; reappeared_count: number };
    ai: { open_count: number; new_count: number };
  };
  latest_scan: {
    id: number;
    started_at: string;
    finished_at: string | null;
    status: string;
    files_seen: number;
  } | null;
};
