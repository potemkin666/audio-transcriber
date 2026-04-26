# TRANSCRIBER

Local app to transcribe long audio files (UK/English accents are fine) into:

- `transcript.txt` (timestamps + speaker labels)
- `transcript_plain.txt` (plain text)
- `segments.json` (timestamped segments)
- `transcript.srt` / `transcript.vtt` (subtitles)

Runs Whisper locally (no uploads required).

## Quick start (Windows)

1) Double-click `Setup.cmd` once (installs deps, bundles FFmpeg if needed, creates a Desktop shortcut).
2) Double-click the Desktop icon: `TRANSCRIBER`.

## Manual run (any OS)

You need Python 3.11+ (3.12 is a great default) and FFmpeg available.

```bash
python -m venv .venv
```

Activate the venv:

- Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
- macOS/Linux: `source .venv/bin/activate`

Install deps and launch:

```bash
python -m pip install -U pip
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

## FFmpeg

- Windows: `Setup.cmd` auto-downloads a local copy into `tools\ffmpeg` if you don’t have FFmpeg installed.
- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt-get install ffmpeg`

## Notes

- Speaker labels are **beta** and work best when you set the correct speaker count (e.g., 2 for an interview).
- Speaker labels require extra deps: `python -m pip install -r requirements-speakers.txt` (or run `Setup-Speakers.cmd` on Windows).
- Model downloads happen on first run and can take a few minutes.

## CLI (batch)

Transcribe a single file:

```powershell
python transcribe_cli.py --input "C:\path\to\audio.m4a" --out ".\out"
```

Transcribe everything in a folder:

```powershell
python transcribe_cli.py --input "C:\path\to\audio-folder" --out ".\out"
```

## Supported file types

Common formats like `.mp3`, `.m4a` (MPEG-4 audio), `.mp4`, `.aac`, `.wav`, `.flac`, `.ogg`, `.m4b`, `.webm`.
