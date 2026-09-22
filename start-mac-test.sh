#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

MODE="${1:-serve}"
if [[ "$MODE" != "serve" && "$MODE" != "--prepare-only" ]]; then
  echo "Usage: bash start-mac-test.sh [--prepare-only]"
  exit 1
fi

if [[ "$MODE" == "serve" ]] && command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8765 is already in use by an older TangerinePhotoAssistant service."
  echo "Return to its Terminal window and press Control-C, then run this script again."
  echo "To inspect the process: lsof -nP -iTCP:8765 -sTCP:LISTEN"
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.12 or newer is required. Install it, then run this script again."
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then
  echo "Python 3.12 or newer is required. Current: $($PYTHON_BIN --version 2>&1)"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js and npm are required to build the local web interface."
  echo "Install Node.js 20.19+ or 22.12+, then run this script again."
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1)'; then
  echo "Node.js 20.19+ or 22.12+ is required by the frontend build."
  exit 1
fi

mkdir -p runtime/mac-test
PYTHON_DEPENDENCY_HASH="$(shasum -a 256 pyproject.toml requirements-tested.txt)"
FRONTEND_DEPENDENCY_HASH="$(shasum -a 256 web/package.json web/package-lock.json)"
if [[ ! -x ".venv-mac/bin/python" ]]; then
  echo "Creating isolated Mac test environment..."
  "$PYTHON_BIN" -m venv .venv-mac
  .venv-mac/bin/python -m pip install --upgrade pip
fi
if [[ "$(cat runtime/mac-test/python-dependencies.sha256 2>/dev/null || true)" != "$PYTHON_DEPENDENCY_HASH" ]] || ! .venv-mac/bin/python -c 'import tangerine_photo_assistant' >/dev/null 2>&1; then
  .venv-mac/bin/python -m pip install -c requirements-tested.txt -e .
  printf '%s\n' "$PYTHON_DEPENDENCY_HASH" > runtime/mac-test/python-dependencies.sha256
fi

if [[ ! -d "web/node_modules" || "$(cat runtime/mac-test/frontend-dependencies.sha256 2>/dev/null || true)" != "$FRONTEND_DEPENDENCY_HASH" ]]; then
  echo "Installing frontend dependencies..."
  (cd web && npm ci)
  printf '%s\n' "$FRONTEND_DEPENDENCY_HASH" > runtime/mac-test/frontend-dependencies.sha256
fi

echo "Building the latest frontend..."
(cd web && npm run build)

mkdir -p runtime/mac-test/workspace runtime/mac-test/cache

echo "Preparing the expanded Mac demo library..."
.venv-mac/bin/python -m tangerine_photo_assistant.sample_data \
  --source sample-library/photos/mac-test-event --pagination-count 100 \
  --target runtime/mac-test/sample-library/photos

APP=".venv-mac/bin/tangerine-photo"
CONFIG="config.mac-test.toml"
"$APP" doctor --config "$CONFIG"

DATABASE="runtime/mac-test/workspace/AnalysisDatabase/catalog.sqlite3"
if [[ -f "$DATABASE" ]]; then
  echo "Refreshing the isolated sample catalog..."
else
  echo "Preparing the isolated sample catalog..."
fi
"$APP" scan --config "$CONFIG" --metadata auto
"$APP" structure --config "$CONFIG"
"$APP" visual --config "$CONFIG"
"$APP" quality --config "$CONFIG"
.venv-mac/bin/python -m tangerine_photo_assistant.sample_data \
  --source sample-library/photos/mac-test-event --pagination-count 100 \
  --target runtime/mac-test/sample-library/photos \
  --database "$DATABASE"

if [[ "$MODE" == "--prepare-only" ]]; then
  echo "Mac test data is ready."
  exit 0
fi

echo "Opening TangerinePhotoAssistant Mac test at http://127.0.0.1:8765"
exec "$APP" serve --config "$CONFIG" --host 127.0.0.1 --port 8765
