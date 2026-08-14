export type SystemCapabilities = {
  platform: string;
  library_root: string;
  workspace_root: string;
  metadata: { level: "basic" | "full"; exiftool: boolean; message: string };
  ai: { ready: boolean; message: string };
  features: {
    open_folder: boolean;
    raw_pairing: boolean;
    lightroom_manifest: boolean;
    phone_share_export: boolean;
  };
  safety: {
    offline_only: boolean;
    library_read_only: boolean;
    allow_move: boolean;
    allow_delete: boolean;
    allow_original_metadata_write: boolean;
  };
};

export type EditableSettings = {
  library: { originals: string; workspace: string };
  cache: { root: string; max_size_gb: number; thumbnail_max_size_gb: number };
  analysis: { raw_extensions: string[]; burst_time_gap_seconds: number; metadata_batch_size: number };
  tools: { exiftool: string };
  models: {
    python: string;
    vision_language_model: string;
    quantization: "none" | "int8";
    gpu_memory_limit_gb: number;
    max_new_tokens: number;
    image_max_edge: number;
  };
};

export type SettingsStatus = {
  configured: EditableSettings;
  effective: SystemCapabilities;
  restart_required: boolean;
  backup_path: string | null;
  message?: string;
};
