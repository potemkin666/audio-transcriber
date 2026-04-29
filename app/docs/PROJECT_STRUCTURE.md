# Project Structure

This project is arranged so normal users can start the app from the root folder, while developer and generated files stay clearly labeled.

## User-Facing Files

- `START_HERE.md` - shortest instructions for a non-technical user.
- `Setup.cmd` - first-time Windows setup.
- `Launch.cmd` - starts the local app.
- `Launch-LAN.cmd` - starts the app for access from another device on the same Wi-Fi.
- `Setup-Speakers.cmd` - installs optional speaker-label dependencies.
- `README.md` - fuller usage and troubleshooting notes.

## App Source

- `streamlit_app.py` - main Streamlit interface.
- `transcriber/` - transcription, FFmpeg, formatting, report, speaker-label, and hot-folder logic.
- `transcribe_cli.py` - command-line batch transcription entry point.
- `watch_hotfolder.py` - background hot-folder watcher used by the app.

## Assets And Setup Support

- `assets/` - app icon and visual theme files.
- `scripts/` - maintenance scripts, currently icon generation.
- `setup_windows.ps1` - real Windows setup logic called by `Setup.cmd`.
- `setup_unix.sh` - manual setup helper for macOS/Linux.

## Generated Or Hidden Folders

- `.venv/` - Python virtual environment created by setup.
- `tools/` - bundled FFmpeg binaries downloaded by setup.
- `logs/` - runtime logs created when the app launches.
- `out/` - default output folder for command-line runs.
- `__pycache__/` - Python cache folders. These can be deleted safely.

Generated folders should not be committed to Git.

## Project Metadata

- `pyproject.toml` - package metadata and dependency definitions.
- `requirements.txt` - main app dependencies.
- `requirements-speakers.txt` - optional speaker-label dependencies.
- `requirements-hotfolder.txt` - optional hot-folder watcher dependency.
- `.github/` - GitHub templates and CI.
- `docs/` - project notes, contribution docs, changelog, and security policy.
