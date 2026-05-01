from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from transcriber.core import TranscriptionOptions, prepare_whisper_model, transcribe_path
from transcriber.ffmpeg import ensure_ffmpeg_available


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe long audio files locally with Whisper.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to an audio file (e.g. .mp3/.m4a/.mp4) or a folder containing audio files.",
    )
    parser.add_argument("--out", required=True, help="Output folder.")
    parser.add_argument(
        "--model",
        default="small",
        help="Whisper model size: tiny, base, small, medium, large (default: small).",
    )
    parser.add_argument(
        "--chunk-minutes",
        type=int,
        default=10,
        help="Chunk length in minutes (default: 10).",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Language code (default: en).",
    )
    parser.add_argument(
        "--speakers",
        type=int,
        default=None,
        help="Number of speakers to label (beta). Example: 2. Omit to disable.",
    )
    parser.add_argument(
        "--style",
        default="per_segment",
        help="Transcript style: per_segment, paragraph, subtitle_first (default: per_segment).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    options = TranscriptionOptions(
        whisper_model=args.model,
        language=args.language,
        chunk_seconds=max(60, int(args.chunk_minutes) * 60),
        num_speakers=int(args.speakers) if args.speakers and int(args.speakers) > 1 else None,
        transcript_style=str(args.style or "per_segment"),
        retain_audio=True,
    )

    in_path = Path(args.input).expanduser()
    out_dir = Path(args.out).expanduser()
    if not in_path.exists():
        raise SystemExit(f"Error: input path not found: {in_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        ensure_ffmpeg_available()
    except RuntimeError as e:
        raise SystemExit(f"Error: FFmpeg preflight failed: {e}") from None
    except FileNotFoundError as e:
        raise SystemExit(f"Error: FFmpeg preflight failed: {e}") from None

    try:
        print(f"Preparing Whisper model '{options.whisper_model}'...", file=sys.stderr)
        prepare_whisper_model(options.whisper_model, progress_cb=None)
    except RuntimeError as e:
        raise SystemExit(f"Error: Could not prepare Whisper model '{options.whisper_model}': {e}") from None
    except FileNotFoundError as e:
        raise SystemExit(f"Error: Could not prepare Whisper model '{options.whisper_model}': {e}") from None
    except Exception as e:
        raise SystemExit(
            f"Error: Unexpected failure while preparing Whisper model '{options.whisper_model}': {e}"
        ) from None

    try:
        results = transcribe_path(in_path=in_path, out_dir=out_dir, options=options, progress_cb=None)
    except RuntimeError as e:
        raise SystemExit(f"Error: {e}") from None
    except FileNotFoundError as e:
        raise SystemExit(f"Error: {e}") from None

    print(f"Done. Wrote {len(results)} transcript(s) to: {out_dir}")
    for r in results:
        print(f"- {os.fspath(r.output_dir)}")


if __name__ == "__main__":
    main()
