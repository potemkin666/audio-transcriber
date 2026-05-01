from __future__ import annotations

import json
import hashlib
import os
import re
import time
import tempfile
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import whisper
import requests
import numpy as np

from .ffmpeg import ensure_ffmpeg_available, probe_media, split_to_wav_chunks, convert_to_audio_16k_mono
from .formats import (
    Segment,
    segments_to_paragraphs,
    segments_to_srt,
    segments_to_subtitle_first,
    segments_to_txt,
    segments_to_txt_timestamps,
    segments_to_vtt,
)
from .speakers import label_speakers_from_windows
from .report import write_brief_pack
from .telemetry import update_rtf


ProgressCallback = Callable[[float, str], None] | None
PreviewCallback = Callable[[str], None] | None


@dataclass(frozen=True)
class TranscriptionOptions:
    whisper_model: str = "small"
    language: str | None = "en"
    chunk_seconds: int = 600
    num_speakers: int | None = None
    transcript_style: str = "per_segment"  # per_segment | paragraph | subtitle_first
    redact: bool = False
    vad: bool = False
    normalize: bool = False
    denoise: bool = False
    retain_audio: bool = False


@dataclass(frozen=True)
class TranscriptionResult:
    input_file: Path
    output_dir: Path


def _app_whisper_download_root() -> Path:
    """
    Keep model downloads out of the user's global cache to avoid:
    - partial/corrupt cache collisions
    - OneDrive/profile sync weirdness
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "transcriber" / "whisper"
    # Fallback for non-Windows / missing env.
    return Path(os.path.expanduser("~")) / ".cache" / "transcriber" / "whisper"


def _whisper_model_url(name: str) -> str | None:
    try:
        return whisper._MODELS.get(name)  # type: ignore[attr-defined]
    except Exception:
        return None


def _whisper_model_file(download_root: Path, name: str) -> Path | None:
    url = _whisper_model_url(name)
    if not url:
        return None
    return download_root / os.path.basename(url)


def _model_download_error_message(name: str, err: Exception | None) -> str:
    if err is None:
        return (
            f"Whisper model download failed for '{name}'. "
            "Check your internet connection and try again, or choose a smaller model (tiny/base)."
        )

    if isinstance(err, requests.Timeout):
        return (
            f"Whisper model download timed out for '{name}'. "
            "Check your internet connection and try again, or choose a smaller model (tiny/base)."
        )

    if isinstance(err, requests.ConnectionError):
        return (
            f"Whisper model download could not reach the model host for '{name}'. "
            "Check DNS/firewall settings or try again on a different network."
        )

    if isinstance(err, requests.HTTPError):
        status = getattr(getattr(err, "response", None), "status_code", None)
        if status:
            return (
                f"Whisper model download failed with HTTP {status} for '{name}'. "
                "Try again later, or choose a smaller model (tiny/base)."
            )
        return (
            f"Whisper model download failed for '{name}'. "
            "The download server returned an HTTP error; try again later."
        )

    msg = str(err).strip()
    if "SHA256 mismatch" in msg:
        return (
            f"Whisper model download failed integrity checks for '{name}'. "
            "This usually means a partial/corrupt download or a network/proxy rewriting the file. "
            "Try again on a different network, or choose a smaller model (tiny/base)."
        )

    return f"Whisper model download failed for '{name}': {msg or err.__class__.__name__}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_whisper_model_downloaded(
    name: str,
    progress_cb: ProgressCallback = None,
    download_stats: dict | None = None,
) -> Path:
    """
    Downloads model with retries and integrity verification.
    This avoids partial downloads causing Whisper's built-in downloader to repeatedly fail.
    """
    url = _whisper_model_url(name)
    if not url:
        raise RuntimeError(f"Unknown Whisper model: {name}")

    expected_sha256 = url.split("/")[-2]
    download_root = _app_whisper_download_root()
    download_root.mkdir(parents=True, exist_ok=True)

    model_file = download_root / os.path.basename(url)
    part_file = model_file.with_suffix(model_file.suffix + ".part")

    if model_file.exists():
        try:
            if _sha256_file(model_file) == expected_sha256:
                if download_stats is not None:
                    download_stats.update({"cached": True, "attempts": 0})
                return model_file
        except Exception:
            pass
        try:
            model_file.unlink()
        except Exception:
            pass

    if download_stats is not None:
        download_stats.update({"cached": False, "attempts": 0, "bytes": 0, "content_length": None})

    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            if download_stats is not None:
                download_stats["attempts"] = int(attempt)
            if progress_cb:
                progress_cb(0.0, f"Downloading Whisper model '{name}' (attempt {attempt}/3)...")

            if part_file.exists():
                try:
                    part_file.unlink()
                except Exception:
                    pass

            with requests.get(url, stream=True, timeout=(10, 60)) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", "0") or "0")
                if download_stats is not None:
                    download_stats["content_length"] = int(total) if total else None
                downloaded = 0
                h = hashlib.sha256()

                with part_file.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        h.update(chunk)
                        downloaded += len(chunk)
                        if download_stats is not None:
                            download_stats["bytes"] = int(downloaded)

                        if progress_cb and total > 0:
                            progress_cb(min(0.999, downloaded / total), "Downloading model...")

            if h.hexdigest() != expected_sha256:
                raise RuntimeError("Downloaded model SHA256 mismatch.")

            part_file.replace(model_file)
            if progress_cb:
                progress_cb(1.0, "Model ready.")
            return model_file
        except Exception as e:
            last_err = e
            if download_stats is not None:
                download_stats["last_error"] = str(e)
            time.sleep(0.75 * attempt)

    raise RuntimeError(_model_download_error_message(name, last_err)) from last_err


def prepare_whisper_model(name: str, progress_cb: ProgressCallback = None) -> None:
    ensure_whisper_model_downloaded(name, progress_cb=progress_cb)
    _load_whisper_model_cached(name)


@lru_cache(maxsize=4)
def _load_whisper_model_cached(name: str):
    download_root = _app_whisper_download_root()
    download_root.mkdir(parents=True, exist_ok=True)

    def _try_load():
        return whisper.load_model(name, download_root=os.fspath(download_root))

    try:
        return _try_load()
    except RuntimeError as e:
        msg = str(e)
        if "SHA256" in msg or "checksum" in msg:
            # Try our own downloader once, then load again.
            ensure_whisper_model_downloaded(name, progress_cb=None)
            return _try_load()
        raise


def _safe_stem(p: Path) -> str:
    # Keep it filesystem-friendly.
    stem = p.stem.strip().replace(" ", "_")
    return "".join(ch for ch in stem if ch.isalnum() or ch in ("_", "-", ".")) or "audio"


def _format_hms(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    whole = int(seconds)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _redact_text(text: str) -> str:
    text = _EMAIL_RE.sub("[EMAIL]", text)

    # Very loose phone matcher: replace sequences with >=9 digits.
    def _phone_sub(m: re.Match) -> str:
        s = m.group(0)
        digits = [ch for ch in s if ch.isdigit()]
        return "[PHONE]" if len(digits) >= 9 else s

    phone_like = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
    return phone_like.sub(_phone_sub, text)


def _trim_leading_trailing_silence(
    audio: np.ndarray,
    *,
    sr: int = 16000,
    threshold_db: float = -45.0,
    pad_seconds: float = 0.25,
) -> tuple[np.ndarray, float]:
    """
    Trims leading/trailing silence only.
    Returns (trimmed_audio, trim_start_seconds).
    """
    if audio.size == 0:
        return audio, 0.0

    frame = int(0.03 * sr)
    hop = int(0.01 * sr)
    if frame <= 0 or hop <= 0 or audio.size < frame:
        return audio, 0.0

    eps = 1e-9
    rms_db: list[float] = []
    for i in range(0, audio.size - frame + 1, hop):
        x = audio[i : i + frame]
        rms = float(np.sqrt(np.mean(x * x) + eps))
        db = 20.0 * np.log10(rms + eps)
        rms_db.append(db)

    speech = np.array([d > threshold_db for d in rms_db], dtype=bool)
    if not speech.any():
        return np.zeros((0,), dtype=np.float32), 0.0

    first = int(np.argmax(speech))
    last = int(len(speech) - 1 - np.argmax(speech[::-1]))

    pad_frames = int(pad_seconds / 0.01)
    first = max(0, first - pad_frames)
    last = min(len(speech) - 1, last + pad_frames)

    start = first * hop
    end = min(audio.size, last * hop + frame)
    trimmed = audio[start:end]
    return trimmed, float(start) / float(sr)


def _load_wav_mono_16k_float32(path: str) -> np.ndarray:
    """
    Loads a WAV file without FFmpeg (Whisper's default loader shells out to ffmpeg).
    We generate WAV chunks as 16kHz mono PCM, so this is enough and avoids WinError 2.
    """
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        frames = wf.readframes(nframes)

    if framerate != 16000:
        raise RuntimeError(f"Unexpected WAV sample rate {framerate}Hz; expected 16000Hz.")
    if channels not in (1, 2):
        raise RuntimeError(f"Unsupported WAV channels: {channels}.")
    if sampwidth != 2:
        raise RuntimeError(f"Unsupported WAV sample width: {sampwidth} bytes (expected 16-bit PCM).")

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1)
    return audio


def transcribe_file(
    *,
    in_path: Path,
    out_dir: Path,
    options: TranscriptionOptions,
    progress_cb: ProgressCallback,
    preview_cb: PreviewCallback = None,
) -> TranscriptionResult:
    t0 = time.time()
    t0_perf = time.perf_counter()
    ensure_ffmpeg_available()

    in_path = in_path.resolve()
    out_dir = out_dir.resolve()

    file_out_dir = out_dir / _safe_stem(in_path)
    file_out_dir.mkdir(parents=True, exist_ok=True)

    input_duration: float | None = None
    run_stats: dict = {
        "input_name": in_path.name,
        "input_path": os.fspath(in_path),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": options.whisper_model,
        "language": options.language,
        "chunk_seconds": int(options.chunk_seconds),
        "options": {
            "speakers": int(options.num_speakers or 0),
            "style": options.transcript_style,
            "vad": bool(options.vad),
            "normalize": bool(options.normalize),
            "denoise": bool(options.denoise),
            "redact": bool(options.redact),
            "retain_audio": bool(options.retain_audio),
        },
        "timings": {},
        "chunks": [],
        "counts": {"segments": 0, "chunks_total": 0, "chunks_used": 0, "chunks_skipped_silence": 0},
        "warnings": [],
    }
    try:
        run_stats["input_bytes"] = int(in_path.stat().st_size)
    except Exception:
        pass

    # Persist rich input metadata for auditability + preflight UX.
    try:
        media = probe_media(os.fspath(in_path))
        if media:
            (file_out_dir / "media.json").write_text(json.dumps(media, indent=2), encoding="utf-8")

            warnings: list[str] = []
            suggestions: dict[str, bool] = {}
            streams = media.get("streams") if isinstance(media, dict) else None
            audio_streams = [s for s in (streams or []) if isinstance(s, dict) and s.get("codec_type") == "audio"]
            a0 = audio_streams[0] if audio_streams else {}
            channels = int(a0.get("channels") or 0)
            sample_rate = int(float(a0.get("sample_rate") or 0) or 0)
            codec = (a0.get("codec_name") or "").strip()
            br = int(float(a0.get("bit_rate") or 0) or 0)
            if channels >= 2:
                warnings.append("Stereo source detected; downmixing to mono for ASR.")
            if sample_rate >= 44100 and channels >= 2 and br >= 192000 and (in_path.suffix.lower() == ".mp3"):
                warnings.append("Possible music/mixed content (stereo, 44.1kHz+, high bitrate).")
                suggestions["denoise"] = True
            if br and br < 64000 and in_path.suffix.lower() in {".mp3", ".m4a", ".mp4", ".aac"}:
                warnings.append("Low bitrate audio; expect reduced accuracy.")
                suggestions["normalize"] = True

            (file_out_dir / "preflight.json").write_text(
                json.dumps(
                    {
                        "codec": codec or None,
                        "channels": channels or None,
                        "sample_rate": sample_rate or None,
                        "bit_rate": br or None,
                        "warnings": warnings,
                        "suggested_options": suggestions,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            if warnings and progress_cb:
                progress_cb(0.0, f"Preflight: {warnings[0]}")
            if warnings:
                run_stats["warnings"] = list(warnings)

            try:
                fmt = media.get("format") if isinstance(media, dict) else None
                if isinstance(fmt, dict) and fmt.get("duration") is not None:
                    input_duration = float(fmt.get("duration"))
                    run_stats["audio_seconds"] = float(input_duration)
            except Exception:
                pass
    except Exception:
        pass

    # Model cache presence + load timing.
    try:
        download_root = _app_whisper_download_root()
        mf = _whisper_model_file(download_root, options.whisper_model)
        run_stats["model_cache_present"] = bool(mf and mf.exists())
    except Exception:
        pass

    t_model0 = time.perf_counter()
    model = _load_whisper_model_cached(options.whisper_model)
    run_stats["timings"]["model_load_seconds"] = float(time.perf_counter() - t_model0)

    if progress_cb:
        progress_cb(0.0, f"Splitting into ~{options.chunk_seconds // 60} minute chunks...")

    with tempfile.TemporaryDirectory(prefix="transcriber-chunks-") as tmp:
        chunks_dir = Path(tmp)
        filters: list[str] = []
        if options.denoise:
            filters.append("afftdn=nf=-25")
        if options.normalize:
            filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        audio_filters = ",".join(filters) if filters else None

        if options.retain_audio:
            # Keep playback artifacts for verification + click-to-jump UX.
            t_ret0 = time.perf_counter()
            try:
                convert_to_audio_16k_mono(
                    in_path=os.fspath(in_path),
                    out_path=os.fspath(file_out_dir / "audio_preview.mp3"),
                    fmt="mp3",
                    audio_filters=audio_filters,
                )
            except Exception:
                pass
            try:
                convert_to_audio_16k_mono(
                    in_path=os.fspath(in_path),
                    out_path=os.fspath(file_out_dir / "audio.wav"),
                    fmt="wav",
                    audio_filters=audio_filters,
                )
            except Exception:
                pass
            run_stats["timings"]["retain_audio_seconds"] = float(time.perf_counter() - t_ret0)

        t_split0 = time.perf_counter()
        chunks = split_to_wav_chunks(
            in_path=os.fspath(in_path),
            out_dir=os.fspath(chunks_dir),
            chunk_seconds=int(options.chunk_seconds),
            audio_filters=audio_filters,
        )
        run_stats["timings"]["split_seconds"] = float(time.perf_counter() - t_split0)
        run_stats["counts"]["chunks_total"] = int(len(chunks))

        all_segments: list[Segment] = []
        # Parallel metadata list aligned with all_segments.
        seg_meta: list[dict] = []
        running_preview = ""
        max_preview_chars = 6000
        want_speakers = bool(options.num_speakers and int(options.num_speakers) > 1)
        speaker_windows: list[np.ndarray] = []
        speaker_segment_indexes: list[int] = []
        window_seconds = 3.0
        sr = 16000
        win = int(window_seconds * sr)
        total = max(1, len(chunks))
        first_chunk_stats_written = False
        transcribe_total = 0.0
        for i, (chunk_path, offset) in enumerate(chunks, start=1):
            if progress_cb:
                progress_cb((i - 1) / total, f"Transcribing chunk {i}/{total}...")

            chunk_stat: dict = {"i": int(i), "offset": int(offset)}
            t_chunk0 = time.perf_counter()
            audio = _load_wav_mono_16k_float32(chunk_path)
            trim_start = 0.0
            if options.vad:
                audio, trim_start = _trim_leading_trailing_silence(audio, sr=16000)
                if audio.size == 0:
                    run_stats["counts"]["chunks_skipped_silence"] += 1
                    continue

            if audio.size > 0:
                rms = float(np.sqrt(np.mean(audio * audio) + 1e-9))
                rms_db = 20.0 * np.log10(rms + 1e-9)

                if (not first_chunk_stats_written) and i == 1:
                    first_chunk_stats_written = True
                    try:
                        stats = {"rms_dbfs": float(rms_db), "vad_enabled": bool(options.vad)}
                        (file_out_dir / "audio_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
                        if rms_db < -40.0 and progress_cb:
                            progress_cb((i - 1) / total, "Warning: audio looks very quiet (expect errors).")
                    except Exception:
                        pass

                if rms_db < -55.0:
                    run_stats["counts"]["chunks_skipped_silence"] += 1
                    continue

            chunk_stat["audio_seconds"] = float(audio.shape[0]) / float(sr) if audio.size else 0.0
            r = model.transcribe(
                audio,
                task="transcribe",
                language=options.language,
                fp16=False,
                verbose=False,
            )

            segs_in_chunk = 0
            for s in r.get("segments", []):
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                rel_start = float(s.get("start", 0.0))
                rel_end = float(s.get("end", 0.0))

                whisper_meta = {
                    "avg_logprob": s.get("avg_logprob"),
                    "no_speech_prob": s.get("no_speech_prob"),
                    "compression_ratio": s.get("compression_ratio"),
                    "temperature": s.get("temperature"),
                    "tokens": len(s.get("tokens") or []),
                }
                if options.redact:
                    text = _redact_text(text)

                start = rel_start + float(offset) + float(trim_start)
                end = rel_end + float(offset) + float(trim_start)
                all_segments.append(Segment(start=start, end=end, text=text, speaker="Speaker 1"))
                seg_meta.append({"whisper": whisper_meta, "speaker_confidence": None})
                segs_in_chunk += 1

                if want_speakers:
                    center = (rel_start + rel_end) / 2.0
                    win_start = int((center - window_seconds / 2.0) * sr)
                    win_end = win_start + win
                    pad_left = max(0, -win_start)
                    pad_right = max(0, win_end - audio.shape[0])
                    a0 = max(0, win_start)
                    a1 = min(audio.shape[0], win_end)
                    clip = audio[a0:a1]
                    if pad_left or pad_right:
                        clip = np.pad(clip, (pad_left, pad_right), mode="constant")
                    if clip.shape[0] != win:
                        clip = np.pad(clip, (0, max(0, win - clip.shape[0])), mode="constant")[:win]
                    speaker_windows.append(clip.astype(np.float32, copy=False))
                    speaker_segment_indexes.append(len(all_segments) - 1)
                if preview_cb:
                    ts = _format_hms(start)
                    header = f"{ts} {all_segments[-1].speaker}".strip()
                    block = f"{header}\n{text}"
                    running_preview = (running_preview + ("\n" if running_preview else "") + block).strip()

            if preview_cb:
                if len(running_preview) > max_preview_chars:
                    running_preview = running_preview[-max_preview_chars:]
                preview_cb(running_preview)

            chunk_elapsed = float(time.perf_counter() - t_chunk0)
            chunk_stat["transcribe_seconds"] = chunk_elapsed
            chunk_stat["segments"] = int(segs_in_chunk)
            transcribe_total += chunk_elapsed
            run_stats["counts"]["chunks_used"] += 1
            if len(run_stats["chunks"]) < 600:
                run_stats["chunks"].append(chunk_stat)

        if want_speakers and speaker_windows:
            if progress_cb:
                progress_cb(0.98, "Labeling speakers...")
            diar = label_speakers_from_windows(windows=speaker_windows, num_speakers=int(options.num_speakers or 2))
            for j, (seg_i, label) in enumerate(zip(speaker_segment_indexes, diar.labels, strict=False)):
                seg = all_segments[seg_i]
                all_segments[seg_i] = Segment(start=seg.start, end=seg.end, text=seg.text, speaker=label)
                if diar.confidence and j < len(diar.confidence) and seg_i < len(seg_meta):
                    seg_meta[seg_i]["speaker_confidence"] = float(diar.confidence[j])

            try:
                diar_out = {"num_speakers": int(options.num_speakers or 0), "metrics": diar.metrics or {}}
                (file_out_dir / "diarization.json").write_text(json.dumps(diar_out, indent=2), encoding="utf-8")
            except Exception:
                pass

        if progress_cb:
            progress_cb(1.0, "Writing outputs...")

        txt_plain = segments_to_txt(all_segments)
        style = (options.transcript_style or "per_segment").strip().lower()
        if style == "paragraph":
            txt = segments_to_paragraphs(all_segments)
        elif style == "subtitle_first":
            txt = segments_to_subtitle_first(all_segments)
        else:
            txt = segments_to_txt_timestamps(all_segments)
        srt = segments_to_srt(all_segments)
        vtt = segments_to_vtt(all_segments)

        (file_out_dir / "transcript.txt").write_text(txt, encoding="utf-8")
        (file_out_dir / "transcript_plain.txt").write_text(txt_plain, encoding="utf-8")
        (file_out_dir / "transcript.srt").write_text(srt, encoding="utf-8")
        (file_out_dir / "transcript.vtt").write_text(vtt, encoding="utf-8")
        segments_payload = [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "speaker": s.speaker,
                **(seg_meta[i] if i < len(seg_meta) else {}),
            }
            for i, s in enumerate(all_segments)
        ]

        (file_out_dir / "segments.json").write_text(
            json.dumps(segments_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Brief Pack (best-effort): leadership-ready summary artifacts.
        try:
            extras: dict = {}
            preflight_path = file_out_dir / "preflight.json"
            if preflight_path.exists():
                extras["preflight"] = json.loads(preflight_path.read_text(encoding="utf-8"))
            write_brief_pack(out_dir=file_out_dir, input_name=in_path.name, segments=segments_payload, extras=extras)
        except Exception:
            pass

        # Run telemetry (best-effort): learn per-machine ETA over time.
        try:
            elapsed = max(0.0, float(time.time() - t0))
            if input_duration is None:
                input_duration = max((float(s.get("end") or 0.0) for s in segments_payload), default=0.0) or None
            speakers_on = bool(options.num_speakers and int(options.num_speakers) > 1)
            if input_duration and input_duration > 1.0:
                rtf = float(elapsed) / float(input_duration)
                update_rtf(model=options.whisper_model, speakers=speakers_on, rtf=rtf)
                run_stats["elapsed_seconds"] = float(elapsed)
                run_stats["audio_seconds"] = float(input_duration)
                run_stats["rtf"] = float(rtf)
                run_stats["timings"]["transcribe_seconds_total"] = float(transcribe_total)
                run_stats["counts"]["segments"] = int(len(segments_payload))
        except Exception:
            pass

        # Always write run_stats.json (best-effort).
        try:
            run_stats["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            run_stats["timings"]["total_seconds"] = float(time.perf_counter() - t0_perf)
            (file_out_dir / "run_stats.json").write_text(json.dumps(run_stats, indent=2), encoding="utf-8")
        except Exception:
            pass

    return TranscriptionResult(input_file=in_path, output_dir=file_out_dir)


def transcribe_path(
    *,
    in_path: Path,
    out_dir: Path,
    options: TranscriptionOptions,
    progress_cb: ProgressCallback,
) -> list[TranscriptionResult]:
    in_path = in_path.expanduser()
    if in_path.is_file():
        return [transcribe_file(in_path=in_path, out_dir=out_dir, options=options, progress_cb=progress_cb)]

    if not in_path.is_dir():
        raise FileNotFoundError(os.fspath(in_path))

    supported_exts = {
        ".mp3",
        ".m4a",
        ".mp4",
        ".aac",
        ".wav",
        ".flac",
        ".ogg",
        ".m4b",
        ".webm",
    }
    audio_files = sorted(p for p in in_path.rglob("*") if p.is_file() and p.suffix.lower() in supported_exts)
    results: list[TranscriptionResult] = []
    total = max(1, len(audio_files))
    for i, p in enumerate(audio_files, start=1):
        if progress_cb:
            progress_cb((i - 1) / total, f"Transcribing {p.name} ({i}/{total})...")
        results.append(transcribe_file(in_path=p, out_dir=out_dir, options=options, progress_cb=None))
    if progress_cb:
        progress_cb(1.0, "Done.")
    return results
