export type EquipmentKind = "camera" | "lens" | "accessory";

export type EquipmentDraft = {
  kind: EquipmentKind;
  key?: string;
  brand: string;
  model: string;
  display_name: string;
  category: string;
  section: string;
  notes: string;
  filter_thread_mm: string;
  thread_mm: string;
  owned: boolean;
  source?: string;
};

export type EquipmentItem = {
  brand?: string;
  model?: string;
  display_name?: string;
  kind?: string;
  section?: string;
  filter_thread_mm?: number;
  thread_mm?: number;
  system_mm?: number;
  lens_thread_mm?: number;
  stops?: number;
  capture_count?: number;
  album_count?: number;
  category?: string;
  source?: string;
  notes?: string;
  inventory_key: string;
  owned: boolean;
  status: string;
};

export type EquipmentCatalog = {
  schema_version: number;
  profile_file: string;
  catalog: { name?: string; source_url?: string; checked_at?: string };
  summary: {
    camera_count: number;
    lens_count: number;
    catalog_lens_count: number;
    unowned_lens_count: number;
    accessory_count: number;
    detected_camera_count: number;
    detected_lens_count: number;
  };
  cameras: EquipmentItem[];
  lenses: EquipmentItem[];
  accessories: EquipmentItem[];
  hidden: { camera: EquipmentItem[]; lens: EquipmentItem[]; accessory: EquipmentItem[] };
  detected: {
    cameras: Array<{ model: string; capture_count: number }>;
    lenses: Array<{ model: string; capture_count: number }>;
  };
  filter_system: { compatibility?: string; infer_usage_from_thread_size?: boolean };
};
