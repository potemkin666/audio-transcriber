# TRANSCRIBER

TRANSCRIBER is a local Whisper-based app for turning audio and video files into transcripts on your own machine. The runnable project lives in the `app/` directory.

No environment variables are required for standard local use.

## Supported platforms

- Windows 10/11
- macOS
- Linux

## Start here

- If you downloaded this repo from GitHub, open `app/`
- If you want the shortest possible pointer, read `START_HERE.md`
- The Windows launchers are kept intentionally; do not remove them

## Copy-paste install and run

### Windows

Open PowerShell in the `app/` directory, then run:

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
cd app
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
cd app
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

- `app/` — the Streamlit app, CLI, setup scripts, docs, and packaging files
- `RUNME - Start TRANSCRIBER.cmd` — Windows convenience launcher from the repo root
- `.github/` — GitHub Actions and issue/PR templates
- `LICENSE` — repository license

## UI preview

![TRANSCRIBER UI preview](app/assets/mp3_transcriber.png)

## Quick start from source

### Windows

1. Open `app/`
2. Run `Setup.cmd`
3. Run `Launch.cmd`

### macOS / Linux

1. Open `app/`
2. Install Python 3, virtualenv support, and FFmpeg first
3. Run `bash ./setup_unix.sh`

## Quick start from GitHub

- If you downloaded a release ZIP, use the instructions in `app/README.md`
- If you cloned the repo, start in `app/`
- The root is intentionally thin; the runnable app is in `app/`

## Development notes

- Existing source README: `app/README.md`
- Existing short guide: `app/START_HERE.md`
- Existing project map: `app/docs/PROJECT_STRUCTURE.md`
