export type LibrarySection = "photos" | "albums";
export type PhotoLayout = "list" | "small" | "medium" | "large";
export type PhotoInboxStatus = { path: string; exists: boolean; can_open: boolean };

export type LibraryCapture = {
  id: number;
  stem: string;
  captured_at: string | null;
  pairing_status: string;
  camera_model: string | null;
  lens_model: string | null;
  album_id: number | null;
  album_name: string | null;
  category: string | null;
  user_rating: number | null;
  user_pick: number | null;
  user_reject: number | null;
  user_note: string | null;
  similarity_group_id: number | null;
  similarity_group_size: number | null;
  item_type: "photo" | "group";
  selection_capture_ids: number[];
  group_pick_count: number | null;
  group_reject_count: number | null;
  group_unreviewed_count: number | null;
  grouping_override: "exclude" | "split_before" | null;
  size_bytes: number;
  thumbnail_url: string;
};
export type LibraryCapturesResponse = { count: number; limit: number; offset: number; collapsed: boolean; items: LibraryCapture[] };
export type LibraryFilters = {
  albums: Array<{ id: number; name: string; category: string; capture_count: number; status: string }>;
  album_types: Array<{ name: string; built_in: number }>;
  cameras: string[];
  lenses: string[];
  tags: Array<{
    dimension: "subject" | "status" | "problem" | "location";
    name: string;
    capture_count: number;
  }>;
};
export type LibraryQuery = {
  pageSize: number;
  albumId: string;
  category: string;
  camera: string;
  lens: string;
  rating: string;
  selection: string;
  quality: string;
  tagSubject: string;
  tagStatus: string;
  tagProblem: string;
  tagLocation: string;
  dateFrom: string;
  dateTo: string;
  search: string;
  sort: string;
  collapseGroups: boolean;
};
export type PhoneShareExport = {
  filename: string;
  photo_count: number;
  size_bytes: number;
  max_edge: number;
  quality: number;
  metadata_removed: boolean;
  download_url: string;
};

export type EventItem = {
  id: number;
  proposed_name: string;
  category: string;
  date_label: string | null;
  start_at: string | null;
  end_at: string | null;
  capture_count: number;
  status: string;
  confidence: number;
  source_count: number;
  burst_count: number;
  largest_burst: number;
  sources: string[];
  reason: { method: string; legacy_buckets: string[] };
};
export type EventsResponse = { count: number; limit: number; offset: number; items: EventItem[] };
