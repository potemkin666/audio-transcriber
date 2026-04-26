from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeedProfile:
    rtf: float  # real-time factor: processing_seconds / audio_seconds
    samples: int


def _profile_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "transcriber" / "telemetry.json"
    return Path(os.path.expanduser("~")) / ".cache" / "transcriber" / "telemetry.json"


def _key(*, model: str, speakers: bool) -> str:
    return f"{model.strip().lower()}|speakers={int(bool(speakers))}"


def load_profiles() -> dict[str, SpeedProfile]:
    p = _profile_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        out: dict[str, SpeedProfile] = {}
        for k, v in (raw or {}).items():
            if not isinstance(v, dict):
                continue
            rtf = float(v.get("rtf", 0.0) or 0.0)
            samples = int(v.get("samples", 0) or 0)
            if rtf > 0 and samples > 0:
                out[str(k)] = SpeedProfile(rtf=rtf, samples=samples)
        return out
    except Exception:
        return {}


def save_profiles(profiles: dict[str, SpeedProfile]) -> None:
    p = _profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: {"rtf": float(v.rtf), "samples": int(v.samples)} for k, v in sorted(profiles.items())}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def default_rtf(*, model: str, speakers: bool) -> float:
    """
    Conservative-ish CPU defaults; the app learns per machine over time.
    """
    m = model.strip().lower()
    base = {
        "tiny": 0.35,
        "base": 0.65,
        "small": 1.15,
        "medium": 2.2,
        "large": 3.5,
    }.get(m, 1.3)
    if speakers:
        base *= 1.35
    return float(base)


def get_rtf(*, model: str, speakers: bool) -> tuple[float, int]:
    profiles = load_profiles()
    k = _key(model=model, speakers=speakers)
    prof = profiles.get(k)
    if not prof:
        return default_rtf(model=model, speakers=speakers), 0
    return float(prof.rtf), int(prof.samples)


def update_rtf(*, model: str, speakers: bool, rtf: float) -> None:
    if not (rtf and rtf > 0):
        return
    profiles = load_profiles()
    k = _key(model=model, speakers=speakers)
    prev = profiles.get(k)
    if not prev:
        profiles[k] = SpeedProfile(rtf=float(rtf), samples=1)
        save_profiles(profiles)
        return

    # Weighted moving average; newer runs count, but history stabilizes.
    n = int(prev.samples)
    new_n = min(50, n + 1)
    alpha = 1.0 / float(new_n)
    new_rtf = (1.0 - alpha) * float(prev.rtf) + alpha * float(rtf)
    profiles[k] = SpeedProfile(rtf=float(new_rtf), samples=int(new_n))
    save_profiles(profiles)

