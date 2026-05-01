from __future__ import annotations

import json
import os
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_EXTS = {".mp3", ".m4a", ".mp4", ".aac", ".wav", ".flac", ".ogg", ".m4b", ".webm"}


@dataclass(frozen=True)
class FileSignature:
    size: int
    mtime_ns: int
    sha256: str | None = None


@dataclass(frozen=True)
class FileDecision:
    should_process: bool
    signature: FileSignature
    persist_state: bool = False


def _state_path(out_dir: Path) -> Path:
    return out_dir / ".transcriber_hotfolder_state.json"


def load_state(out_dir: Path) -> dict[str, FileSignature]:
    p = _state_path(out_dir)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        out: dict[str, FileSignature] = {}
        for k, v in (raw or {}).items():
            if not isinstance(v, dict):
                continue
            out[k] = FileSignature(
                size=int(v.get("size", 0)),
                mtime_ns=int(v.get("mtime_ns", 0)),
                sha256=(v.get("sha256") or None),
            )
        return out
    except Exception:
        return {}


def save_state(out_dir: Path, state: dict[str, FileSignature]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = _state_path(out_dir)
    payload = {
        k: {"size": v.size, "mtime_ns": v.mtime_ns, "sha256": v.sha256} for k, v in sorted(state.items())
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def iter_audio_files(folder: Path, *, recursive: bool) -> list[Path]:
    folder = folder.expanduser().resolve()
    if recursive:
        candidates = folder.rglob("*")
    else:
        candidates = folder.glob("*")
    files: list[Path] = []
    for p in candidates:
        try:
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                files.append(p)
        except Exception:
            continue
    return sorted(files)


def stat_signature(p: Path) -> FileSignature:
    st = p.stat()
    return FileSignature(size=int(st.st_size), mtime_ns=int(st.st_mtime_ns), sha256=None)


def sha256_file(p: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def decide_file_action(
    p: Path,
    previous: FileSignature | None,
    *,
    use_hash: bool,
    always_hash_before_skip: bool = False,
) -> FileDecision:
    sig = stat_signature(p)
    same_meta = bool(previous and previous.size == sig.size and previous.mtime_ns == sig.mtime_ns)

    if previous is None:
        return FileDecision(should_process=True, signature=sig)

    if always_hash_before_skip:
        sha = sha256_file(p)
        current = FileSignature(size=sig.size, mtime_ns=sig.mtime_ns, sha256=sha)
        if previous.sha256 and previous.sha256 == sha:
            return FileDecision(should_process=False, signature=current, persist_state=True)
        return FileDecision(should_process=True, signature=current)

    if not use_hash:
        return FileDecision(should_process=not same_meta, signature=sig)

    if same_meta and previous.sha256:
        return FileDecision(
            should_process=False,
            signature=FileSignature(size=sig.size, mtime_ns=sig.mtime_ns, sha256=previous.sha256),
        )

    sha = sha256_file(p)
    current = FileSignature(size=sig.size, mtime_ns=sig.mtime_ns, sha256=sha)
    if previous.sha256 and previous.sha256 == sha:
        return FileDecision(should_process=False, signature=current, persist_state=True)
    return FileDecision(should_process=True, signature=current)


def is_settled(p: Path, *, wait_seconds: float = 1.0, checks: int = 3) -> bool:
    """
    Files dropped into a hot folder may still be copying.
    Consider a file "settled" if size stays constant for N checks.
    """
    last_size: int | None = None
    for _ in range(max(1, int(checks))):
        try:
            size = int(p.stat().st_size)
        except Exception:
            return False
        if last_size is not None and size != last_size:
            last_size = size
            time.sleep(wait_seconds)
            continue
        last_size = size
        time.sleep(wait_seconds)
    return True


def rel_key(folder: Path, p: Path) -> str:
    try:
        return os.fspath(p.resolve().relative_to(folder.resolve()))
    except Exception:
        return os.fspath(p.resolve())
