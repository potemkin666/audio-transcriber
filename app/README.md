# TRANSCRIBER

TRANSCRIBER is a local app for turning audio and video files into transcripts. It runs Whisper on your computer, so your files are not uploaded to a cloud transcription service. The app presents itself as a local/private transcription console with a sober dark-blue interface.

No environment variables are required for standard local use.

## Supported platforms

- Windows 10/11
- macOS
- Linux

## UI preview

![TRANSCRIBER UI preview](assets/mp3_transcriber.png)

## For Normal Use

If you are looking at the simple release folder, double-click `RUNME - Start TRANSCRIBER.cmd`.

If you have a release ZIP, unzip it somewhere permanent such as Documents or Desktop, then:

1. Double-click `1 Install TRANSCRIBER.cmd` once.
2. Double-click `2 Start TRANSCRIBER.cmd` or the Desktop shortcut named `TRANSCRIBER`.

If you are running from the source project folder instead:

1. Double-click `Setup.cmd` once.
2. After setup finishes, double-click the Desktop shortcut named `TRANSCRIBER`.
3. Drop in audio files and download the transcript ZIP when it finishes.

For phone or tablet access on the same Wi-Fi, launch with `Launch-LAN.cmd` and use the QR code shown inside the app.

If you only want the shortest possible instructions, open `START_HERE.md`.

## What It Produces

Each transcript bundle can include:

- `transcript.txt` with timestamps and optional speaker labels
- `transcript_plain.txt` with clean plain text
- `segments.json` with timestamped transcript data
- `transcript.srt` and `transcript.vtt` subtitle files
- `brief.md` and `brief.html` with a one-page brief pack

Supported inputs include `.mp3`, `.m4a`, `.mp4`, `.aac`, `.wav`, `.flac`, `.ogg`, `.m4b`, and `.webm`.

## Optional Features

Speaker labels are beta. On Windows, run `Setup-Speakers.cmd` after `Setup.cmd`, then relaunch the app.
They are implemented as optional speaker diarization with speech embeddings plus KMeans-based labeling. This is not an identity graph, entity stitching, or person-recognition system.

Hot-folder watching is available from the app. If the app says the watcher dependency is missing, install it with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-hotfolder.txt
```

## Privacy and local telemetry

TRANSCRIBER stores a small local telemetry file only to improve ETA estimates on your own machine.

- Windows: `%LOCALAPPDATA%\transcriber\telemetry.json`
- macOS / Linux: `~/.cache/transcriber/telemetry.json`

The file stores only per-configuration speed profiles:

- model name
- whether speaker labeling was enabled
- learned real-time factor (`rtf`)
- sample count used for the moving average

It does **not** store transcript text, audio, speaker names, identities, or remote analytics. The file stays on the local machine unless you copy it yourself.

## Install from source

### Windows

Prerequisites:

- Python 3

Run from the `app/` directory:

```powershell
.\Setup.cmd
.\Launch.cmd
```

Optional LAN launch:

```powershell
.\Launch-LAN.cmd
```

### macOS

Prerequisites:

```bash
brew install python ffmpeg
```

Run from the `app/` directory:

```bash
bash ./setup_unix.sh
```

### Ubuntu / Debian Linux

Prerequisites:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv ffmpeg
```

Run from the `app/` directory:

```bash
bash ./setup_unix.sh
```

If `setup_unix.sh` stops with an error, fix the missing prerequisite shown in the terminal and rerun the same command.

## Supported pip install path

If you are installing from source instead of using the launcher scripts, the supported package install path is:

```bash
python -m pip install .
```

Optional extras:

```bash
python -m pip install .[hotfolder]
python -m pip install .[speakers]
```

First successful run confirmation on macOS/Linux:

```bash
curl -s http://127.0.0.1:8501/_stcore/health
```

Expected output:

```text
ok
```

## Manual Run

Use this if you are developing the project or running it outside the Windows launchers.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Install FFmpeg before the first run.

## Command Line

Transcribe one file:

```powershell
python transcribe_cli.py --input "C:\path\to\audio.m4a" --out ".\out"
```

Transcribe a folder:

```powershell
python transcribe_cli.py --input "C:\path\to\audio-folder" --out ".\out"
```

## Folder Map

See `docs\PROJECT_STRUCTURE.md` for a plain-English explanation of what each folder/file is for.

## Building A Windows Release ZIP

From the project folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_windows.ps1 -Version 0.1.0
```

The output appears in `dist\TRANSCRIBER-Windows-0.1.0.zip`.
