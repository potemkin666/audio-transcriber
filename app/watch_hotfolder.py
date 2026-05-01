from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from transcriber.core import TranscriptionOptions, transcribe_file, prepare_whisper_model
from transcriber.hotfolder import (
    decide_file_action,
    is_settled,
    iter_audio_files,
    load_state,
    rel_key,
    save_state,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hot-folder watcher for TRANSCRIBER (auto transcribe new files).")
    p.add_argument("--folder", required=True, help="Folder to watch for new audio files.")
    p.add_argument("--out", required=True, help="Output folder for transcripts/state.")
    p.add_argument("--recursive", action="store_true", help="Scan/watch subfolders.")
    p.add_argument("--once", action="store_true", help="Run a single scan then exit (no watch).")
    p.add_argument("--hash", action="store_true", help="Hash changed files before skipping duplicates (slower, safer).")
    p.add_argument(
        "--always-hash-before-skip",
        action="store_true",
        help="Hash every candidate before skipping duplicates (slowest, correctness-first).",
    )
    p.add_argument("--model", default="small", help="Whisper model: tiny, base, small, medium, large.")
    p.add_argument("--language", default="en", help="Language code or blank for auto.")
    p.add_argument("--speakers", type=int, default=None, help="Speaker count (beta). Omit/1 disables.")
    p.add_argument(
        "--style",
        default="per_segment",
        help="Transcript style: per_segment, paragraph, subtitle_first (default: per_segment).",
    )
    p.add_argument("--vad", action="store_true", help="Trim leading/trailing silence (fast).")
    p.add_argument("--normalize", action="store_true", help="Apply loudness normalization via ffmpeg.")
    p.add_argument("--denoise", action="store_true", help="Apply light denoise via ffmpeg.")
    p.add_argument("--redact", action="store_true", help="Mask emails/phones in saved transcript.")
    return p.parse_args()


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _process_new(
    *,
    folder: Path,
    out_dir: Path,
    options: TranscriptionOptions,
    use_hash: bool,
    always_hash_before_skip: bool,
    recursive: bool,
) -> int:
    folder = folder.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    state = load_state(out_dir)
    candidates = iter_audio_files(folder, recursive=bool(recursive))
    new_files: list[Path] = []
    state_dirty = False
    for f in candidates:
        key = rel_key(folder, f)
        decision = decide_file_action(
            f,
            state.get(key),
            use_hash=bool(use_hash),
            always_hash_before_skip=bool(always_hash_before_skip),
        )
        if not decision.should_process:
            if decision.persist_state:
                state[key] = decision.signature
                state_dirty = True
            continue
        new_files.append(f)

    if state_dirty:
        save_state(out_dir, state)

    if not new_files:
        return 0

    _log(f"Found {len(new_files)} new/changed file(s).")
    prepare_whisper_model(options.whisper_model, progress_cb=None)

    processed = 0
    for f in new_files:
        if not is_settled(f, wait_seconds=1.0, checks=3):
            _log(f"Skip (not settled yet): {f.name}")
            continue

        key = rel_key(folder, f)
        decision = decide_file_action(
            f,
            state.get(key),
            use_hash=bool(use_hash),
            always_hash_before_skip=bool(always_hash_before_skip),
        )
        if not decision.should_process:
            if decision.persist_state:
                state[key] = decision.signature
                save_state(out_dir, state)
            continue

        _log(f"Transcribing: {f.name}")
        try:
            transcribe_file(in_path=f, out_dir=out_dir, options=options, progress_cb=None, preview_cb=None)
        except Exception as e:
            _log(f"ERROR: {f.name}: {e}")
            continue

        state[key] = decision.signature
        save_state(out_dir, state)
        processed += 1
        _log(f"Done: {f.name}")

    return processed


def main() -> int:
    args = _parse_args()
    folder = Path(args.folder)
    out_dir = Path(args.out)

    num_speakers = int(args.speakers) if args.speakers and int(args.speakers) > 1 else None
    language = (args.language or "").strip() or None
    options = TranscriptionOptions(
        whisper_model=args.model,
        language=language,
        chunk_seconds=600,
        num_speakers=num_speakers,
        transcript_style=str(args.style or "per_segment"),
        redact=bool(args.redact),
        vad=bool(args.vad),
        normalize=bool(args.normalize),
        denoise=bool(args.denoise),
        retain_audio=True,
    )

    if not folder.exists() or not folder.is_dir():
        _log(f"Folder not found: {os.fspath(folder)}")
        return 2

    _log(f"Folder: {os.fspath(folder)}")
    _log(f"Out:    {os.fspath(out_dir)}")
    _log(f"Model:  {options.whisper_model} | Lang: {options.language or 'auto'} | Speakers: {options.num_speakers or 0}")

    processed = _process_new(
        folder=folder,
        out_dir=out_dir,
        options=options,
        use_hash=bool(args.hash),
        always_hash_before_skip=bool(args.always_hash_before_skip),
        recursive=bool(args.recursive),
    )
    if args.once:
        _log(f"Scan complete. Processed: {processed}")
        return 0

    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except Exception:
        _log("watchdog not installed. Install with: pip install -r requirements-hotfolder.txt")
        _log("Tip: You can still run a one-time scan with --once.")
        return 3

    class Handler(FileSystemEventHandler):
        def __init__(self) -> None:
            super().__init__()
            self._last_scan = 0.0

        def on_created(self, event):  # type: ignore[no-untyped-def]
            self._maybe_scan(event)

        def on_moved(self, event):  # type: ignore[no-untyped-def]
            self._maybe_scan(event)

        def on_modified(self, event):  # type: ignore[no-untyped-def]
            self._maybe_scan(event)

        def _maybe_scan(self, event) -> None:  # type: ignore[no-untyped-def]
            if getattr(event, "is_directory", False):
                return
            # Simple debounce: scanning is cheap, but transcription isn't.
            now = time.time()
            if now - self._last_scan < 2.0:
                return
            self._last_scan = now
            _process_new(
                folder=folder,
                out_dir=out_dir,
                options=options,
                use_hash=bool(args.hash),
                always_hash_before_skip=bool(args.always_hash_before_skip),
                recursive=bool(args.recursive),
            )

    observer = Observer()
    handler = Handler()
    observer.schedule(handler, os.fspath(folder), recursive=bool(args.recursive))
    observer.start()
    _log("Watching for new audio... (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        _log("Stopping...")
    finally:
        observer.stop()
        observer.join(timeout=5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
