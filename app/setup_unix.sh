#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

print_failure_next_steps() {
  cat >&2 <<'EOF'

Setup did not finish.
Next steps:
  1. Read the error shown above.
  2. Install any missing prerequisite, then rerun: bash ./setup_unix.sh
  3. If FFmpeg was missing:
       macOS: brew install ffmpeg
       Ubuntu/Debian: sudo apt-get update && sudo apt-get install -y ffmpeg
  4. If Python venv support was missing on Linux:
       Ubuntu/Debian: sudo apt-get install -y python3-venv
EOF
}

on_error() {
  local exit_code=$?
  print_failure_next_steps
  exit "$exit_code"
}

trap on_error ERR

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg is required but wasn't found on PATH." >&2
  echo "Install it (examples):" >&2
  echo "  macOS: brew install ffmpeg" >&2
  echo "  Ubuntu/Debian: sudo apt-get update && sudo apt-get install -y ffmpeg" >&2
  print_failure_next_steps
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

".venv/bin/python" -m pip install -U pip
".venv/bin/python" -m pip install -r requirements.txt
echo "Optional (speaker labels beta): .venv/bin/python -m pip install -r requirements-speakers.txt"

echo "Setup complete."
echo "Next steps:"
echo "  1. Wait for Streamlit to print a Local URL (usually http://127.0.0.1:8501)."
echo "  2. Open that URL in your browser."
echo "  3. First successful run confirmation: curl -s http://127.0.0.1:8501/_stcore/health"
echo "     should print: ok"
echo "  4. Press Ctrl+C in this terminal when you want to stop the app."
echo "Starting TRANSCRIBER..."
exec ".venv/bin/python" -m streamlit run "$ROOT_DIR/streamlit_app.py"
