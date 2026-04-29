from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None


def _format_srt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def segments_to_txt(segments: list[Segment]) -> str:
    return "\n".join(s.text.strip() for s in segments if s.text and s.text.strip()).strip() + "\n"


def _format_hms(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    whole = int(seconds)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def segments_to_txt_timestamps(segments: list[Segment]) -> str:
    lines: list[str] = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        prefix = _format_hms(s.start)
        header = f"{prefix} {s.speaker}".rstrip() if s.speaker else prefix
        lines.append(header)
        lines.append(text)
    return "\n".join(lines).strip() + "\n"


def segments_to_paragraphs(segments: list[Segment]) -> str:
    """
    Paragraph style: group consecutive segments by speaker, no timestamps.
    """
    lines: list[str] = []
    current_speaker: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, current_speaker
        if not buf:
            return
        text = " ".join(buf).strip()
        if current_speaker:
            lines.append(f"{current_speaker}: {text}")
        else:
            lines.append(text)
        lines.append("")
        buf = []

    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        if s.speaker != current_speaker:
            flush()
            current_speaker = s.speaker
        buf.append(text)

    flush()
    return "\n".join(lines).strip() + "\n"


def segments_to_subtitle_first(segments: list[Segment]) -> str:
    """
    Subtitle-first: timestamp range per line + speaker, then text.
    """
    lines: list[str] = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        start = _format_hms(s.start)
        end = _format_hms(s.end)
        spk = f" {s.speaker}" if s.speaker else ""
        lines.append(f"{start} --> {end}{spk}".strip())
        lines.append(text)
    return "\n".join(lines).strip() + "\n"

def segments_to_srt(segments: list[Segment]) -> str:
    lines: list[str] = []
    i = 1
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(f"{_format_srt_time(s.start)} --> {_format_srt_time(s.end)}")
        lines.append(f"{s.speaker}: {text}" if s.speaker else text)
        lines.append("")
        i += 1
    return "\n".join(lines).strip() + "\n"


def segments_to_vtt(segments: list[Segment]) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        lines.append(f"{_format_vtt_time(s.start)} --> {_format_vtt_time(s.end)}")
        lines.append(f"{s.speaker}: {text}" if s.speaker else text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"
