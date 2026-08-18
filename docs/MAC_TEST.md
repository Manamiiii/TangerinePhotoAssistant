# macOS test entry

The Mac setup is an isolated functional test environment. The Windows PC
remains the production host and no production database, model, Lightroom
catalog, XMP file, or original photo is copied to macOS.

## Requirements

- macOS 13 or newer
- Python 3.12 or newer
- Node.js 20 or newer (includes `npm`)
- Optional: ExifTool from Homebrew for EXIF enrichment

Optional EXIF support:

```bash
brew install exiftool
```

## First start

After cloning the repository, run from Terminal:

```bash
cd TangerinePhotoAssistant
bash start-mac-test.sh
```

The first start creates `.venv-mac`, installs dependencies, builds the React
frontend, expands the four privacy-cleaned source samples into a deterministic
30-file demo library, creates an isolated SQLite catalog under
`runtime/mac-test`, scans the demo library, and opens:

```text
http://127.0.0.1:8765
```

To verify burst folding, open `照片图库 → 相册`, then enter `海边散步` or
`公园抓拍`. Album details default to `折叠连拍`; `全部照片` intentionally stays
expanded. The demo seeds persistent burst picks, standalone star ratings, multi-pick, and manual
split examples so all selection states are visible without editing production data.
The isolated catalog also seeds fictional rich EXIF examples for shutter, exposure,
focus, stabilization, drive mode, precise time, and Fujifilm recipe sections. Two
captures have simulated `.RAF` companions so the JPG+RAW interface can be verified;
their payload remains the privacy-cleaned JPEG derivative and must not be used to
test RAW decoding or image quality. Six fictional results labeled
`DEMO-ONLY-no-inference` exercise model-result, evidence, advice, and review
layouts without loading a model. Five additional results labeled
`DEMO-V5-SANITIZED-RUN11` preserve the output structure of a successful Windows
v5 benchmark run. Their source identifiers and paths were removed, and they are
attached to fictional captures for UI and schema testing. The dedicated album
`v5实测样片` contains `V5_SAMPLE_0001` (traffic night) and `V5_SAMPLE_0002`
(cat), using explicitly approved, resized, metadata-free copies of the actual
non-person inputs, so their v5 text matches the displayed image. The other three
results remain attached to unrelated fictional images and must not be interpreted
as judgments about those displayed mock images.
Fictional owned/unowned camera, lens, and accessory states are written only below
`runtime/mac-test/workspace` on first preparation; later starts preserve equipment
changes made in the UI. Rich details remain visible without ExifTool; installing
ExifTool is only needed to test reading metadata from other files.

Later starts reuse the environment and catalog. Stop the server with
`Control-C` in Terminal.

## Hot-reload development mode

Stop the normal service first, then run:

```bash
bash start-mac-dev.sh
```

Open `http://127.0.0.1:5173`. React and CSS changes update through Vite HMR;
Python files under `src/` restart the FastAPI backend automatically. Keeping
this Terminal open also means a later `git pull` normally refreshes the UI and
backend without rerunning the script. Dependency or configuration changes still
require stopping the process and starting it again.

Both launchers now refuse to start when their ports are already occupied. This
prevents a newly pulled build from appearing to start while the browser is
actually connected to an older process.

## Reset only the Mac test data

Stop the service, then remove the generated test runtime:

```bash
rm -rf runtime/mac-test
```

Run `bash start-mac-test.sh` again to rebuild it. This command affects only the
ignored Mac test runtime inside the cloned project.

## Intentional limits

- The demo library contains four fictional albums and short similar bursts.
  All timestamps and album names are fictional; integrity fixtures stay in the background.
- The bundled source samples are JPEG-only reduced derivatives, not originals. The
  generated `.RAF` companions only simulate pairing and contain JPEG fixture bytes.
- The Windows Qwen3-VL model is not included or downloaded.
- AI inference therefore remains unavailable on the Mac test clone.
- Lightroom and XMP writes remain disabled.
- Migration controls must not be used with this sample configuration.
