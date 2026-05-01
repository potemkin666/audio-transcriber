# TRANSCRIBER

TRANSCRIBER is a local Whisper-based app for turning audio and video files into transcripts on your own machine. The working app lives in `/app`, and this repo root now exposes the files GitHub expects for a normal open-source project.

## Repository layout

- `/app` — the Streamlit app, CLI, setup scripts, docs, and packaging files
- `/RUNME - Start TRANSCRIBER.cmd` — Windows convenience launcher from the repo root
- `/.github` — GitHub Actions and issue/PR templates
- `/LICENSE` — repository license

## Quick start from source

### Windows

1. Open `/home/runner/work/audio-transcriber/audio-transcriber/app`
2. Run `Setup.cmd`
3. Run `Launch.cmd`

### macOS / Linux

1. Open `/home/runner/work/audio-transcriber/audio-transcriber/app`
2. Install FFmpeg first
3. Run `bash ./setup_unix.sh`

## Quick start from GitHub

- If you downloaded a release ZIP, use the instructions in `/home/runner/work/audio-transcriber/audio-transcriber/app/README.md`
- If you cloned the repo, start in `/home/runner/work/audio-transcriber/audio-transcriber/app`
- No environment variables are required for a standard local run

## Development notes

- Existing source README: `/home/runner/work/audio-transcriber/audio-transcriber/app/README.md`
- Existing short guide: `/home/runner/work/audio-transcriber/audio-transcriber/app/START_HERE.md`
- Existing project map: `/home/runner/work/audio-transcriber/audio-transcriber/app/docs/PROJECT_STRUCTURE.md`
