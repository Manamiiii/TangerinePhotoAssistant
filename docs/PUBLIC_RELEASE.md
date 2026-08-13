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
- Opening the inbox uses Explorer, Finder, or `xdg-open` when available.
- Shared safety copy uses configured paths rather than one developer's drives.
- The home page contains no prescribed selection funnel. Empty libraries receive
  a small first-use explanation; established libraries prioritize recent photos
  and exceptional items that actually require attention.

## Release work still required

1. Choose the public license and contribution policy. The project metadata stays
   proprietary until the owner makes that explicit legal decision.
2. Add signed Windows and macOS packages around the existing local web service.
3. Build a graphical setup screen on top of the stable config/capability APIs.
4. Add vendor-neutral metadata fixtures for Canon, Nikon, Sony, Panasonic, OM
   System, Apple, and common no-EXIF/corrupt-file cases.
5. Add migration fixtures for every supported schema and an explicit restore UI
   for user reviews, picks, notes, and manual grouping decisions.
6. Add a redacted diagnostic export and verify that logs exclude GPS, serial
   numbers, absolute user paths, and image content.
7. Run a small closed beta before enabling update telemetry or any networked
   feature. Telemetry must remain opt-in and inspectable.

Packaging must call the existing configuration and capability boundaries rather
than introduce a second settings format. This keeps the Python CLI, local web UI,
and future desktop shell compatible.
