#!/usr/bin/env bash
# One-command local launch: sets up Python + Node deps if needed, builds the UI, starts TrueOffer on http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/node/bin:$PATH"

if [ ! -x .venv/bin/python ]; then
  echo "Creating Python virtual environment…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend packages…"
  (cd frontend && npm install --no-audit --no-fund)
fi
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
  echo "Building the frontend…"
  (cd frontend && npm run build >/dev/null)
fi

PORT="${PORT:-8000}"
echo ""
echo "  TrueOffer is running at  http://localhost:${PORT}"
echo "  (local engine, no API key, nothing leaves this computer). Press Ctrl+C to stop."
echo ""
# Open the browser only once the server actually answers (up to 60 s).
if [ -z "${NO_OPEN:-}" ]; then
  (
    for _ in $(seq 1 120); do
      if curl -s -o /dev/null "http://127.0.0.1:${PORT}/api/health"; then
        command -v open >/dev/null && open "http://localhost:${PORT}"
        exit 0
      fi
      sleep 0.5
    done
    echo "TrueOffer didn't start within 60 seconds. Check the messages above." >&2
  ) &
fi
exec .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
