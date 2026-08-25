# Public release foundation

TangerinePhotoAssistant is being generalized as a local-first photo curation tool.
The public edition should keep photos on the user's computer and treat optional
integrations as capabilities, not assumptions.

## Stable product boundaries

- The photo library is read-only by default. Ratings, picks, analysis results,
  thumbnails, and user notes live in the application workspace.
- Offline operation is mandatory for the core product. ExifTool, RAW support,
  a local AI model, and Lightroom manifests are optional layers.
- Missing optional tools must reduce functionality with a clear explanation;
  they must not prevent browsing and manual selection.
- Paths, camera vendors, Lightroom, GPU hardware, and operating systems must not
  be hard-coded into shared UI copy or core domain behavior.
- User-authored reviews and grouping decisions are durable data. Thumbnails,
  histograms, fingerprints, and automated analysis are rebuildable derivatives.

## Implemented foundation

- `tangerine-photo init` creates a conservative portable configuration from
  explicit photo, workspace, and cache paths. It refuses to overwrite an
  existing file and does not create, scan, copy, or modify photos.
- `/api/system/capabilities` reports platform, metadata level, optional local AI,
  export features, paths, and active safety switches for future setup screens.
- The web settings center edits the same portable configuration used by the CLI.
  It validates a temporary file, backs up the previous config, then replaces it
  atomically. Directory changes take effect after restart and never imply moving data.
- Opening the inbox uses Explorer, Finder, or `xdg-open` when available.
- Shared safety copy uses configured paths rather than one developer's drives.
- Personal equipment lives only in the configured workspace. The bundled profile
  is empty and the Fujifilm catalogue contains public reference data only.
- The home page contains no prescribed selection funnel. Empty libraries receive
  a small first-use explanation; established libraries prioritize recent photos
  and exceptional items that actually require attention.
- A three-step first-launch wizard separates the read-only photo root, durable
  workspace, and rebuildable cache. Optional metadata and local-model paths can
  be skipped, all settings remain editable later, and saving still uses the same
  validated/atomic configuration path as the full settings center.
- The local service exposes a native directory picker on Windows and macOS, with
  Zenity/KDialog support on Linux when installed. Picking a folder never creates,
  scans, copies, or moves files; manual absolute-path entry remains available.
- Synthetic metadata snapshots cover Canon, Nikon, Sony, Panasonic, OM System,
  Apple, Google, and Samsung standard EXIF shapes, plus no-EXIF and corrupt JPEG
  behavior. They exercise normalized vendor names, timezone/subsecond capture
  times, standard lens specifications, GPS conversion, and explicit error fallback
  without redistributing third-party photos.
- A portable human-data JSON export excludes photos, absolute paths, GPS,
  thumbnails, and model result bodies. Restore preflights stable capture keys,
  requires explicit confirmation, blocks around background tasks, and creates an
  integrity-checked SQLite backup before changing ratings, picks, notes, tags,
  current grouping overrides, edit histories, AI review verdicts, or equipment.
- Generated migration fixtures exercise every supported schema version before the
  current schema 32, verifying both preserved fixture data and the pre-upgrade backup.
- A redacted diagnostic ZIP is constructed from an explicit whitelist. It reports
  versions, capability and safety switches, database integrity and aggregate counts,
  while excluding images, names and paths, GPS, serials, user-authored text, model
  payloads, and raw error messages. Its archive contains one inspectable JSON file.
- Persistent worker and launcher logs record exception categories and aggregate
  states, not raw exception text, task error bodies, or runtime path messages.

## Release work still required

1. Choose the public license and contribution policy. The project metadata stays
   proprietary until the owner makes that explicit legal decision.
2. Add signed Windows and macOS packages around the existing local web service.
3. Add licensed real-world RAW/HEIC metadata samples for the synthetic vendor
   baseline where closed-beta users expose compatibility gaps.
4. Extend portable restore to confirmed album names/membership after collision
   semantics are defined; current export covers capture-level human decisions.
5. Run a small closed beta before enabling update telemetry or any networked
   feature. Telemetry must remain opt-in and inspectable.

Packaging must call the existing configuration and capability boundaries rather
than introduce a second settings format. This keeps the Python CLI, local web UI,
and future desktop shell compatible.
