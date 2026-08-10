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
frontend, creates an isolated SQLite catalog under `runtime/mac-test`, scans
the four reduced-size sample JPEGs, and opens:

```text
http://127.0.0.1:8765
```

Later starts reuse the environment and catalog. Stop the server with
`Control-C` in Terminal.

## Reset only the Mac test data

Stop the service, then remove the generated test runtime:

```bash
rm -rf runtime/mac-test
```

Run `bash start-mac-test.sh` again to rebuild it. This command affects only the
ignored Mac test runtime inside the cloned project.

## Intentional limits

- The bundled samples are JPEG-only reduced derivatives, not originals.
- The Windows Qwen3-VL model is not included or downloaded.
- AI inference therefore remains unavailable on the Mac test clone.
- Lightroom and XMP writes remain disabled.
- Migration controls must not be used with this sample configuration.
