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
28-file demo library, creates an isolated SQLite catalog under
`runtime/mac-test`, scans the demo library, and opens:

```text
http://127.0.0.1:8765
```

To verify burst folding, open `照片图库 → 相册`, then enter `海边散步` or
`公园抓拍`. Album details default to `折叠连拍`; `全部照片` intentionally stays
expanded. The demo seeds retained, rejected, non-burst, multi-pick, and manual
split examples so all selection states are visible without editing production data.

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
- The bundled source samples are JPEG-only reduced derivatives, not originals.
- The Windows Qwen3-VL model is not included or downloaded.
- AI inference therefore remains unavailable on the Mac test clone.
- Lightroom and XMP writes remain disabled.
- Migration controls must not be used with this sample configuration.
