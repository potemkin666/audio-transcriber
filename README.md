# TRANSCRIBER

TRANSCRIBER is a local Whisper-based app for turning audio and video files into transcripts on your own machine. The runnable project lives in `/home/runner/work/audio-transcriber/audio-transcriber/app`.

No environment variables are required for standard local use.

## Supported platforms

- Windows 10/11
- macOS
- Linux

## Start here

- If you downloaded this repo from GitHub, open `/home/runner/work/audio-transcriber/audio-transcriber/app`
- If you want the shortest possible pointer, read `/home/runner/work/audio-transcriber/audio-transcriber/START_HERE.md`
- The Windows launchers are kept intentionally; do not remove them

## Copy-paste install and run

### Windows

Open PowerShell in `/home/runner/work/audio-transcriber/audio-transcriber/app`, then run:

```powershell
.\Setup.cmd
.\Launch.cmd
```

For same-Wi-Fi phone/tablet access:

```powershell
.\Launch-LAN.cmd
```

### macOS

Install prerequisites:

```bash
brew install python ffmpeg
```

Then run:

```bash
cd /home/runner/work/audio-transcriber/audio-transcriber/app
bash ./setup_unix.sh
```

### Ubuntu / Debian

Install prerequisites:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv ffmpeg
```

Then run:

```bash
cd /home/runner/work/audio-transcriber/audio-transcriber/app
bash ./setup_unix.sh
```

First successful run confirmation on macOS/Linux:

```bash
curl -s http://127.0.0.1:8501/_stcore/health
```

Expected output:

```text
ok
```

## Repository layout

- `/home/runner/work/audio-transcriber/audio-transcriber/app` — the Streamlit app, CLI, setup scripts, docs, and packaging files
- `/home/runner/work/audio-transcriber/audio-transcriber/RUNME - Start TRANSCRIBER.cmd` — Windows convenience launcher from the repo root
- `/home/runner/work/audio-transcriber/audio-transcriber/.github` — GitHub Actions and issue/PR templates
- `/home/runner/work/audio-transcriber/audio-transcriber/LICENSE` — repository license

## UI preview

![TRANSCRIBER UI preview](app/assets/mp3_transcriber.png)

## Quick start from source

### Windows

1. Open `/home/runner/work/audio-transcriber/audio-transcriber/app`
2. Run `Setup.cmd`
3. Run `Launch.cmd`

### macOS / Linux

1. Open `/home/runner/work/audio-transcriber/audio-transcriber/app`
2. Install Python 3, virtualenv support, and FFmpeg first
3. Run `bash ./setup_unix.sh`

## Quick start from GitHub

- If you downloaded a release ZIP, use the instructions in `/home/runner/work/audio-transcriber/audio-transcriber/app/README.md`
- If you cloned the repo, start in `/home/runner/work/audio-transcriber/audio-transcriber/app`
- The root is intentionally thin; the runnable app is in `app/`

## Development notes

- Existing source README: `/home/runner/work/audio-transcriber/audio-transcriber/app/README.md`
- Existing short guide: `/home/runner/work/audio-transcriber/audio-transcriber/app/START_HERE.md`
- Existing project map: `/home/runner/work/audio-transcriber/audio-transcriber/app/docs/PROJECT_STRUCTURE.md`
