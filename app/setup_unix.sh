#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg is required but wasn't found on PATH." >&2
  echo "Install it (examples):" >&2
  echo "  macOS: brew install ffmpeg" >&2
  echo "  Ubuntu/Debian: sudo apt-get update && sudo apt-get install -y ffmpeg" >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

".venv/bin/python" -m pip install -U pip
".venv/bin/python" -m pip install -r requirements.txt
echo "Optional (speaker labels beta): .venv/bin/python -m pip install -r requirements-speakers.txt"

echo "Starting TRANSCRIBER..."
exec ".venv/bin/python" -m streamlit run "$ROOT_DIR/streamlit_app.py"
