from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _project_root() -> Path:
    # .../mp3-transcriber/transcriber/ffmpeg.py -> project root
    return Path(__file__).resolve().parents[1]


def _bundled_ffmpeg_dir() -> Path:
    return _project_root() / "tools" / "ffmpeg"


def _find_ffmpeg_exe(name: str) -> str | None:
    # 1) System PATH
    p = shutil.which(name)
    if p:
        return p

    # 2) Bundled tools (Setup.cmd can download this)
    bundled = _bundled_ffmpeg_dir() / "bin" / (f"{name}.exe" if name in {"ffmpeg", "ffprobe"} else name)
    if bundled.exists():
        return str(bundled)

    return None


def ensure_ffmpeg_available() -> None:
    ffmpeg = _find_ffmpeg_exe("ffmpeg")
    ffprobe = _find_ffmpeg_exe("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError(
            "FFmpeg is required but wasn't found on PATH. "
            "Run Setup.cmd to auto-download it, or install it system-wide with: winget install Gyan.FFmpeg."
        )

    # Light sanity check (fast).
    subprocess.run([ffmpeg, "-version"], check=True, capture_output=True)
    subprocess.run([ffprobe, "-version"], check=True, capture_output=True)


def probe_duration_seconds(path: str) -> float | None:
    ffprobe = _find_ffmpeg_exe("ffprobe")
    if not ffprobe:
        return None
    try:
        p = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(p.stdout.strip())
    except Exception:
        return None


def split_to_wav_chunks(
    *,
    in_path: str,
    out_dir: str,
    chunk_seconds: int,
    audio_filters: str | None = None,
) -> list[tuple[str, int]]:
    """
    Returns list of (chunk_path, start_offset_seconds).
    Produces 16kHz mono WAV chunks for predictable decoding.
    """
    ffmpeg = _find_ffmpeg_exe("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH.")

    out_pattern = f"{out_dir}/chunk_%05d.wav"

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        in_path,
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
    ]
    if audio_filters:
        cmd += ["-af", audio_filters]
    cmd += [
        "-f",
        "segment",
        "-segment_time",
        str(int(chunk_seconds)),
        "-reset_timestamps",
        "1",
        out_pattern,
    ]

    subprocess.run(cmd, check=True)

    # Collect chunks in order and infer offsets by index*chunk_seconds.
    import os
    from pathlib import Path

    chunks = sorted(Path(out_dir).glob("chunk_*.wav"))
    results: list[tuple[str, int]] = []
    for i, p in enumerate(chunks):
        results.append((os.fspath(p), i * int(chunk_seconds)))
    return results
