#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

for port in 8765 5173; do
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $port is already in use."
    echo "Return to the Terminal running the previous service and press Control-C."
    echo "To inspect it: lsof -nP -iTCP:$port -sTCP:LISTEN"
    exit 1
  fi
done

bash start-mac-test.sh --prepare-only

export TANGERINE_CONFIG="$PROJECT_ROOT/config.mac-test.toml"
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting auto-reloading FastAPI backend on http://127.0.0.1:8765"
.venv-mac/bin/python -m uvicorn tangerine_photo_assistant.devserver:app \
  --host 127.0.0.1 \
  --port 8765 \
  --reload \
  --reload-dir src &
BACKEND_PID=$!

cleanup() {
  if kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

for _ in {1..40}; do
  if curl --silent --fail http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    echo "FastAPI backend stopped before becoming ready."
    exit 1
  fi
  sleep 0.25
done

if ! curl --silent --fail http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
  echo "FastAPI backend did not become ready."
  exit 1
fi

echo "Opening hot-reload UI at http://127.0.0.1:5173"
echo "Keep this Terminal open. Press Control-C to stop both services."
cd web
npm run dev -- --host 127.0.0.1 --port 5173
