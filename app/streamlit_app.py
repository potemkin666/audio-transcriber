from __future__ import annotations

import base64
import json
import html as _html
import io
import tempfile
import zipfile
import importlib.util
import os
import subprocess
import sys
import time
import socket
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from transcriber.core import TranscriptionOptions, prepare_whisper_model, transcribe_file
from transcriber.ffmpeg import ensure_ffmpeg_available, probe_duration_seconds, ffmpeg_version_line, ffprobe_version_line, find_ffmpeg_tools
from transcriber.hotfolder import decide_file_action, iter_audio_files, load_state, rel_key, save_state
from transcriber.telemetry import get_rtf


SUPPORTED_TYPES = ["mp3", "m4a", "mp4", "aac", "wav", "flac", "ogg", "m4b", "webm"]


def _zip_dir(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in root.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(root))
    return buf.getvalue()

def _format_eta(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "—"
    s = int(seconds + 0.5)
    h, rem = divmod(s, 3600)
    m, s2 = divmod(rem, 60)
    if h:
        return f"~{h}h {m:02d}m"
    if m:
        return f"~{m}m {s2:02d}s"
    return f"~{s2}s"


def _format_duration(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "—"
    s = int(seconds + 0.5)
    h, rem = divmod(s, 3600)
    m, s2 = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s2:02d}"
    return f"{m:02d}:{s2:02d}"

def _get_local_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _get_qp(name: str) -> str | None:
    try:
        v = st.query_params.get(name)
        if isinstance(v, list):
            return v[0] if v else None
        return v
    except Exception:
        try:
            v2 = st.experimental_get_query_params().get(name)  # type: ignore[attr-defined]
            return v2[0] if v2 else None
        except Exception:
            return None


def _clear_qp(name: str) -> None:
    try:
        if name in st.query_params:
            del st.query_params[name]
    except Exception:
        try:
            qp = st.experimental_get_query_params()  # type: ignore[attr-defined]
            qp.pop(name, None)
            st.experimental_set_query_params(**qp)  # type: ignore[attr-defined]
        except Exception:
            pass


def _safe_dom_id(value: str, *, prefix: str = "tr") -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(value or ""))
    cleaned = cleaned.strip("_")[:80]
    return f"{prefix}_{cleaned or 'item'}"


def _safe_uploaded_filename(name: str, *, index: int) -> str:
    raw_name = Path(str(name or "")).name
    suffix = Path(raw_name).suffix.lower()
    if suffix.lstrip(".") not in SUPPORTED_TYPES:
        suffix = ".wav"
    return f"upload_{index:02d}{suffix}"


def _read_json_file(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _build_output_meta(*, preflight: dict | None = None, run_stats: dict | None = None) -> dict:
    preflight_warnings = []
    if isinstance(preflight, dict):
        preflight_warnings = [str(w).strip() for w in (preflight.get("warnings") or []) if str(w).strip()]

    run_warnings = []
    counts: dict = {}
    if isinstance(run_stats, dict):
        run_warnings = [str(w).strip() for w in (run_stats.get("warnings") or []) if str(w).strip()]
        counts = run_stats.get("counts") if isinstance(run_stats.get("counts"), dict) else {}

    warnings = _dedupe_preserve_order(preflight_warnings + run_warnings)
    skipped_vad = int(counts.get("chunks_skipped_vad_empty") or 0)
    skipped_quiet = int(counts.get("chunks_skipped_quiet") or 0)
    skipped_total = int(counts.get("chunks_skipped_total") or counts.get("chunks_skipped_silence") or (skipped_vad + skipped_quiet))

    warning_summary = "—"
    if warnings:
        warning_summary = warnings[0] if len(warnings) == 1 else f"{warnings[0]} (+{len(warnings) - 1} more)"

    skipped_summary = "—"
    if skipped_total:
        details = []
        if skipped_vad:
            details.append(f"{skipped_vad} VAD-empty")
        if skipped_quiet:
            details.append(f"{skipped_quiet} ultra-quiet")
        detail_txt = f" ({', '.join(details)})" if details else ""
        skipped_summary = f"{skipped_total}{detail_txt}"

    return {
        "preflight": preflight if isinstance(preflight, dict) else {},
        "run_stats": run_stats if isinstance(run_stats, dict) else {},
        "warnings": warnings,
        "warning_summary": warning_summary,
        "skipped_total": skipped_total,
        "skipped_vad_empty": skipped_vad,
        "skipped_quiet": skipped_quiet,
        "skipped_summary": skipped_summary,
    }


def _load_output_meta(output_dir: Path) -> dict:
    preflight = _read_json_file(output_dir / "preflight.json")
    run_stats = _read_json_file(output_dir / "run_stats.json")
    return _build_output_meta(
        preflight=preflight if isinstance(preflight, dict) else None,
        run_stats=run_stats if isinstance(run_stats, dict) else None,
    )


def _unique_output_name(name: str, existing: dict[str, str]) -> str:
    base = str(name or "").strip() or "Transcript"
    if base not in existing:
        return base
    idx = 2
    while f"{base} ({idx})" in existing:
        idx += 1
    return f"{base} ({idx})"


def _collect_saved_outputs(rows: list[dict], *, zip_bytes: bytes | None = None) -> tuple[dict[str, str], dict[str, dict], dict[str, dict], bytes | None]:
    transcripts: dict[str, str] = {}
    briefs: dict[str, dict] = {}
    outputs: dict[str, dict] = {}
    for row in rows:
        transcript_text = str(row.get("transcript") or "")
        if not transcript_text.strip():
            continue
        stem = str(row.get("stem") or "").strip()
        run_stats = row.get("run_stats") if isinstance(row.get("run_stats"), dict) else {}
        input_name = str(run_stats.get("input_name") or row.get("display_name") or stem or "Transcript")
        display_name = _unique_output_name(input_name, transcripts)
        meta = _build_output_meta(
            preflight=row.get("preflight") if isinstance(row.get("preflight"), dict) else None,
            run_stats=run_stats if isinstance(run_stats, dict) else None,
        )
        transcripts[display_name] = transcript_text
        if isinstance(row.get("brief"), dict):
            briefs[display_name] = row["brief"]
        outputs[display_name] = {
            "stem": stem,
            "segments": row.get("segments") if isinstance(row.get("segments"), list) else None,
            "meta": meta,
        }
    return transcripts, briefs, outputs, zip_bytes


def _load_saved_outputs_from_zip_bytes(zip_bytes: bytes) -> tuple[dict[str, str], dict[str, dict], dict[str, dict], bytes | None]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        stems = sorted(
            {
                Path(name).parts[0]
                for name in zf.namelist()
                if name and not name.endswith("/") and len(Path(name).parts) > 1
            }
        )
        rows: list[dict] = []
        for stem in stems:
            def _read_text(member: str) -> str | None:
                try:
                    return zf.read(member).decode("utf-8", errors="replace")
                except Exception:
                    return None

            def _read_json(member: str) -> dict | list | None:
                try:
                    return json.loads(zf.read(member).decode("utf-8"))
                except Exception:
                    return None

            transcript = _read_text(f"{stem}/transcript.txt")
            if not transcript:
                continue
            rows.append(
                {
                    "stem": stem,
                    "display_name": stem,
                    "transcript": transcript,
                    "segments": _read_json(f"{stem}/segments.json"),
                    "brief": _read_json(f"{stem}/brief_snippets.json"),
                    "preflight": _read_json(f"{stem}/preflight.json"),
                    "run_stats": _read_json(f"{stem}/run_stats.json"),
                }
            )
    return _collect_saved_outputs(rows, zip_bytes=zip_bytes)


def _load_saved_outputs_from_dir(root: Path) -> tuple[dict[str, str], dict[str, dict], dict[str, dict], bytes | None]:
    rows: list[dict] = []
    for output_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        transcript_path = output_dir / "transcript.txt"
        if not transcript_path.exists():
            continue
        try:
            transcript = transcript_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rows.append(
            {
                "stem": output_dir.name,
                "display_name": output_dir.name,
                "transcript": transcript,
                "segments": _read_json_file(output_dir / "segments.json"),
                "brief": _read_json_file(output_dir / "brief_snippets.json"),
                "preflight": _read_json_file(output_dir / "preflight.json"),
                "run_stats": _read_json_file(output_dir / "run_stats.json"),
            }
        )
    return _collect_saved_outputs(rows, zip_bytes=_zip_dir(root))


def _validated_saved_output_dir(path_text: str) -> Path:
    raw = str(path_text or "").strip()
    if not raw:
        raise RuntimeError("Choose a transcript ZIP or an output folder first.")
    if any(ch in raw for ch in ("\x00", "\n", "\r")):
        raise RuntimeError("Folder path contains unsupported characters.")

    resolved = Path(raw).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise FileNotFoundError(f"Saved output folder not found: {resolved}")

    allowed_roots = [Path.home().resolve(), Path.cwd().resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise RuntimeError("Choose a saved output folder under your home directory or the current workspace.")
    return resolved


def _command_palette(commands: list[dict]) -> None:
    payload = json.dumps(commands)
    components.html(
        f"""
        <div id="tr_cmd_root"></div>
        <style>
          #tr_cmd_overlay{{position:fixed;inset:0;display:none;z-index:2147483000;background:rgba(0,0,0,.45);backdrop-filter:blur(6px);}}
          #tr_cmd_modal{{max-width:740px;margin:8vh auto 0;padding:14px 14px;border-radius:18px;border:1px solid rgba(167,240,255,0.22);
                        background:linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.04));
                        box-shadow:0 22px 54px rgba(0,0,0,0.42), 0 0 46px rgba(167,240,255,0.10);}}
          #tr_cmd_input{{width:100%;padding:12px 12px;border-radius:14px;border:1px solid rgba(167,240,255,0.18);
                        background:rgba(0,0,0,0.18);color:rgba(236,243,255,0.92);outline:none;font-size:14px;letter-spacing:.03em;}}
          #tr_cmd_list{{margin-top:10px;max-height:44vh;overflow:auto;}}
          .tr_cmd_item{{padding:10px 10px;border-radius:14px;border:1px solid rgba(167,240,255,0.10);background:rgba(255,255,255,0.04);margin:8px 0;cursor:pointer;}}
          .tr_cmd_item:hover{{border-color:rgba(167,240,255,0.22);box-shadow:0 0 26px rgba(167,240,255,0.10);}}
          .tr_cmd_title{{font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
                         letter-spacing:.10em;text-transform:uppercase;font-size:.75rem;color:rgba(236,243,255,0.86);}}
          .tr_cmd_desc{{margin-top:3px;color:rgba(185,212,255,0.78);font-size:13px;}}
          .tr_cmd_hint{{margin-top:10px;color:rgba(185,212,255,0.55);font-size:12px;letter-spacing:.08em;text-transform:uppercase;}}
        </style>
        <div id="tr_cmd_overlay">
          <div id="tr_cmd_modal">
            <input id="tr_cmd_input" placeholder="Type a command... (Enter to run)" />
            <div id="tr_cmd_list"></div>
            <div class="tr_cmd_hint">Ctrl+K to open • Esc to close • ↑/↓ to select</div>
          </div>
        </div>
        <script>
        (function(){{
          const COMMANDS = {payload};
          const overlay = document.getElementById('tr_cmd_overlay');
          const input = document.getElementById('tr_cmd_input');
          const list = document.getElementById('tr_cmd_list');
          let idx = 0;

          function score(q, t) {{
            q = (q||'').toLowerCase().trim();
            t = (t||'').toLowerCase();
            if(!q) return 1;
            if(t.includes(q)) return 100 - (t.indexOf(q));
            // very small fuzzy
            let qi=0;
            for(let i=0;i<t.length && qi<q.length;i++) if(t[i]===q[qi]) qi++;
            return qi===q.length ? 10 : 0;
          }}

          function render() {{
            const q = input.value || '';
            const items = COMMANDS.map(c => {{
              const s = Math.max(score(q, c.title), score(q, c.desc));
              return [s, c];
            }}).filter(x => x[0] > 0).sort((a,b)=>b[0]-a[0]).slice(0, 16).map(x => x[1]);
            if(idx >= items.length) idx = 0;
            list.innerHTML = '';
            items.forEach((c, i) => {{
              const div = document.createElement('div');
              div.className = 'tr_cmd_item';
              div.style.opacity = (i===idx) ? '1.0' : '0.92';
              div.style.borderColor = (i===idx) ? 'rgba(167,240,255,0.34)' : 'rgba(167,240,255,0.10)';
              const title = document.createElement('div');
              title.className = 'tr_cmd_title';
              title.textContent = c.title || '';
              const desc = document.createElement('div');
              desc.className = 'tr_cmd_desc';
              desc.textContent = c.desc || '';
              div.appendChild(title);
              div.appendChild(desc);
              div.onclick = () => run(c);
              list.appendChild(div);
            }});
            overlay.dataset.items = JSON.stringify(items);
          }}

          function open() {{
            overlay.style.display = 'block';
            input.value = '';
            idx = 0;
            render();
            setTimeout(()=>input.focus(), 10);
          }}

          function close() {{
            overlay.style.display = 'none';
          }}

          function run(c) {{
            try {{
              const recent = JSON.parse(localStorage.getItem('tr_cmd_recent') || '[]');
              recent.unshift(c.title);
              const uniq = [...new Set(recent)].slice(0, 10);
              localStorage.setItem('tr_cmd_recent', JSON.stringify(uniq));
            }} catch(e) {{}}

            const url = new URL(window.location.href);
            url.searchParams.set('cmd', c.cmd);
            if(c.arg) url.searchParams.set('arg', c.arg);
            window.location.href = url.toString();
          }}

          document.addEventListener('keydown', (e) => {{
            if((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {{
              e.preventDefault();
              open();
            }}
            if(overlay.style.display === 'block') {{
              if(e.key === 'Escape') {{ e.preventDefault(); close(); }}
              if(e.key === 'ArrowDown') {{ e.preventDefault(); idx++; render(); }}
              if(e.key === 'ArrowUp') {{ e.preventDefault(); idx = Math.max(0, idx-1); render(); }}
              if(e.key === 'Enter') {{
                e.preventDefault();
                const items = JSON.parse(overlay.dataset.items || '[]');
                if(items.length) run(items[idx] || items[0]);
              }}
            }}
          }});

          overlay.addEventListener('mousedown', (e) => {{
            if(e.target === overlay) close();
          }});
        }})();
        </script>
        """,
        height=0,
    )


def _data_uri(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    ext = path.suffix.lower()
    mime = "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _apply_transcriber_ui(*, water_uri: str | None, overlay_uri: str | None) -> None:
    water_css = f"background-image: url('{water_uri}');" if water_uri else ""
    overlay_css = f"background-image: url('{overlay_uri}');" if overlay_uri else ""

    css = """
    <style>
      :root{
        --bg0:#071C34;
        --bg1:#0F3D6B;
        --ink:#ECF3FF;
        --muted:#B9D4FF;
        --blue:#4BB4FF;
        --cyan:#A7F0FF;
        --line: rgba(75,180,255,0.24);
        --line2: rgba(167,240,255,0.18);
        --glass: rgba(255,255,255,0.06);
      }

      html, body, [data-testid="stAppViewContainer"]{
        background:
          radial-gradient(1200px 760px at 70% 10%, rgba(75,180,255,0.24), transparent 58%),
          radial-gradient(980px 600px at 25% 45%, rgba(167,240,255,0.14), transparent 62%),
          linear-gradient(180deg, var(--bg0), var(--bg1));
        color: var(--ink);
      }

      [data-testid="stAppViewContainer"]::before{
        content:"";
        position: fixed;
        inset: 0;
        __WATER_CSS__
        background-size: cover;
        background-position: center;
        opacity: 0.10;
        filter: saturate(1.0) contrast(1.0) brightness(1.02);
        pointer-events: none;
        z-index: 0;
      }

      [data-testid="stAppViewContainer"]::after{
        content:"";
        position: fixed;
        inset: 0;
        __OVERLAY_CSS__
        background-size: cover;
        background-position: center;
        opacity: 0.04;
        filter: saturate(0.9) contrast(1.0) brightness(1.0);
        pointer-events: none;
        z-index: 0;
      }

      [data-testid="stAppViewContainer"] > .main {
        position: relative;
        z-index: 1;
      }

      [data-testid="stHeader"]{ background: transparent; }
      [data-testid="stSidebar"]{
        background: rgba(6, 18, 33, 0.72);
        border-right: 1px solid rgba(167,240,255,0.16);
      }

      .block-container{ padding-top: 1.0rem; }

      h1, h2, h3{
        letter-spacing: 0.01em;
        text-transform: none;
      }

      button[kind="primary"]{
        background: linear-gradient(180deg, rgba(167,240,255,0.94), rgba(113,200,255,0.94)) !important;
        color: #03101F !important;
        border: 0 !important;
        letter-spacing: 0.01em;
        text-transform: none;
        box-shadow: 0 10px 22px rgba(6, 18, 33, 0.22) !important;
      }

      div[data-testid="stProgress"] > div{ background: rgba(75,180,255,0.22); }
      div[data-testid="stProgress"] div[role="progressbar"]{
        background: linear-gradient(90deg, var(--blue), var(--cyan));
        box-shadow: none;
      }

      [data-testid="stAlert"]{
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(167,240,255,0.18);
      }

      .hud{
        border: 1px solid rgba(167,240,255,0.18);
        border-radius: 16px;
        padding: 14px 16px;
        background: linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));
        position: relative;
        overflow: hidden;
        box-shadow: 0 12px 28px rgba(0,0,0,0.18);
      }

      .tag{
        color: rgba(236,243,255,0.96);
        letter-spacing: 0.01em;
        font-size: 1.15rem;
        font-weight: 600;
      }
      .sub{ color: var(--muted); margin-top: 0.25rem; }

      .micro{
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        color: rgba(236,243,255,0.80);
        letter-spacing: 0.10em;
        text-transform: uppercase;
        font-size: 0.78rem;
      }

      .footer{
        margin-top: 18px;
        text-align: center;
        color: rgba(185,212,255,0.55);
        font-size: 0.72rem;
        letter-spacing: 0.10em;
        text-transform: uppercase;
      }
      .footer .dot{
        display:inline-block;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid rgba(167,240,255,0.12);
        background: rgba(255,255,255,0.04);
      }

      .conf-legend{
        display:flex;
        flex-wrap:wrap;
        gap:8px;
        margin: 8px 0 4px;
      }

      .conf-chip{
        display:inline-flex;
        align-items:center;
        gap:6px;
        border-radius:999px;
        padding: 4px 10px;
        font-size: 12px;
        border:1px solid rgba(167,240,255,0.16);
        background: rgba(255,255,255,0.04);
        color: rgba(236,243,255,0.90);
      }

      .conf-chip.low{ border-color: rgba(255, 96, 136, 0.40); }
      .conf-chip.mid{ border-color: rgba(255, 210, 107, 0.34); }
      .conf-chip.good{ border-color: rgba(167,240,255,0.20); }

      .conf-chip .dot{
        width:8px;
        height:8px;
        border-radius:999px;
        display:inline-block;
      }

      .conf-chip.low .dot{ background: rgba(255, 96, 136, 0.95); }
      .conf-chip.mid .dot{ background: rgba(255, 210, 107, 0.95); }
      .conf-chip.good .dot{ background: rgba(167,240,255,0.95); }

      .brief-note{
        margin-top:10px;
        padding:10px 12px;
        border-radius:14px;
        border:1px solid rgba(167,240,255,0.14);
        background: rgba(255,255,255,0.03);
        color: rgba(185,212,255,0.88);
        font-size: 0.92rem;
      }
    </style>
    """

    css = css.replace("__WATER_CSS__", water_css).replace("__OVERLAY_CSS__", overlay_css)
    st.markdown(css, unsafe_allow_html=True)


st.set_page_config(page_title="TRANSCRIBER", layout="centered")
assets_dir = Path(__file__).parent / "assets" / "theme"
_apply_transcriber_ui(
    water_uri=_data_uri(assets_dir / "background.jpg"),
    overlay_uri=_data_uri(assets_dir / "overlay.jpg"),
)

st.markdown(
    """
    <div class="hud">
      <div class="tag">TRANSCRIBER</div>
      <div class="sub">Local/private transcription console for audio and video files, with timestamps and optional speaker labels.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="micro">STATUS: READY | PRIVACY: LOCAL | NETWORK: NOT REQUIRED</div>', unsafe_allow_html=True)

tabs = st.tabs(["Transcribe", "Hot folder", "Transcript"])

if "last_zip_bytes" not in st.session_state:
    st.session_state.last_zip_bytes = None
if "last_transcripts" not in st.session_state:
    st.session_state.last_transcripts = {}
if "last_briefs" not in st.session_state:
    st.session_state.last_briefs = {}
if "last_outputs" not in st.session_state:
    # maps uploaded filename -> {"stem": safe_stem, "segments": list[dict] | None}
    st.session_state.last_outputs = {}
if "hotfolder_proc" not in st.session_state:
    st.session_state.hotfolder_proc = None

# Command palette (Ctrl+K)
recent_files = []
try:
    recent_files = sorted((st.session_state.get("last_outputs") or {}).keys())[-8:]
except Exception:
    recent_files = []

cmds: list[dict] = [
    {"title": "Transcribe", "desc": "Run transcription for the current upload queue", "cmd": "transcribe"},
    {"title": "Export brief", "desc": "Jump to Brief Pack for the selected file", "cmd": "brief"},
    {"title": "Toggle redact", "desc": "Mask emails/phones in saved transcripts", "cmd": "toggle_redact"},
    {"title": "Jump: low-confidence", "desc": "Filter segments to low-confidence only", "cmd": "low_conf"},
]
for i in range(1, 7):
    cmds.append({"title": f"Jump: Speaker {i}", "desc": "Filter segments by speaker", "cmd": "speaker", "arg": f"Speaker {i}"})
for f in recent_files:
    cmds.append({"title": f"Select file: {f}", "desc": "Set Transcript view file selector", "cmd": "select_file", "arg": f})

_command_palette(cmds)

# Execute palette commands via query params (best-effort).
cmd = _get_qp("cmd")
arg = _get_qp("arg")
if cmd:
    try:
        if cmd == "toggle_redact":
            st.session_state["opt_redact"] = not bool(st.session_state.get("opt_redact", False))
        elif cmd == "low_conf":
            st.session_state["seg_low_only"] = True
            st.session_state["seg_min_conf"] = 0.0
            st.session_state["seg_low_threshold"] = 0.35
        elif cmd == "speaker" and arg:
            st.session_state["seg_speaker_filter"] = [str(arg)]
        elif cmd == "select_file" and arg:
            st.session_state["sel_file"] = str(arg)
        elif cmd == "transcribe":
            st.session_state["auto_transcribe"] = True
        elif cmd == "brief":
            st.session_state["focus_brief"] = True
    except Exception:
        pass
    _clear_qp("cmd")
    _clear_qp("arg")
    st.rerun()

with st.sidebar:
    st.header("Settings")
    whisper_model = st.selectbox("Model", ["tiny", "base", "small", "medium", "large"], index=2, key="opt_model")
    speakers_available = bool(importlib.util.find_spec("speechbrain") and importlib.util.find_spec("sklearn"))
    enable_speakers = st.checkbox(
        "Speaker labels (beta)",
        value=False,
        disabled=not speakers_available,
        help=None
        if speakers_available
        else "Install optional deps first (Windows: run Setup-Speakers.cmd).",
    )
    if not speakers_available:
        st.caption("Speaker labels need extra deps. Windows: run `Setup-Speakers.cmd` and re-launch.")

    num_speakers = st.slider(
        "Speakers",
        min_value=1,
        max_value=6,
        value=2,
        step=1,
        disabled=(not enable_speakers) or (not speakers_available),
        key="opt_speakers",
    )

    transcript_style = st.selectbox(
        "Output style",
        [
            ("Per-segment (timestamps)", "per_segment"),
            ("Paragraphs (grouped)", "paragraph"),
            ("Subtitle-first", "subtitle_first"),
        ],
        index=0,
        format_func=lambda x: x[0],
        key="opt_style",
    )[1]

    auto_clean = st.checkbox("Auto-clean audio", value=False, help="Applies safe defaults (VAD + normalize).", key="opt_autoclean")
    vad = st.checkbox("VAD (trim silence)", value=bool(auto_clean), disabled=auto_clean, key="opt_vad")
    normalize = st.checkbox("Normalize loudness", value=bool(auto_clean), disabled=auto_clean, key="opt_normalize")
    denoise = st.checkbox("Light denoise", value=False, key="opt_denoise")
    redact = st.checkbox("Redact emails/phones", value=False, key="opt_redact")
    retain_audio = st.checkbox("Retain audio (playback verify)", value=True, key="opt_retain_audio")

    lan_mode = st.checkbox("LAN mode (phone)", value=False, key="opt_lan_mode")
    if lan_mode:
        ip = _get_local_ip()
        if ip:
            url = f"http://{ip}:8501"
            st.caption(f"Start with `Launch-LAN.cmd`, then open: `{url}`")
            try:
                import qrcode

                qr = qrcode.QRCode(border=1, box_size=6)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#A7F0FF", back_color="#071C34")
                st.image(img, caption="Scan to open on your phone", use_container_width=True)
            except Exception:
                st.caption("Install QR support: `python -m pip install -r requirements.txt`.")
        else:
            st.caption("Could not detect local IP. Use `ipconfig` and open `http://<ip>:8501`.")

    with st.expander("Advanced"):
        language = st.text_input("Language", value="en")
        show_build = st.checkbox("Show build info", value=False)
    st.caption("Tip: start with Small. If it's slow, use Base.")

    if show_build:
        with st.expander("Build info", expanded=True):
            st.write(f"Python: `{sys.version.split()[0]}`")
            try:
                import whisper as _whisper

                st.write(f"Whisper: `{getattr(_whisper, '__version__', 'unknown')}`")
            except Exception:
                pass

            tools = find_ffmpeg_tools()
            if tools:
                st.write(f"FFmpeg: `{ffmpeg_version_line() or 'unknown'}`")
                st.write(f"FFprobe: `{ffprobe_version_line() or 'unknown'}`")
            else:
                st.write("FFmpeg: `not found`")

with tabs[0]:
    uploaded = st.file_uploader("Drop audio files here", type=SUPPORTED_TYPES, accept_multiple_files=True)
    if uploaded:
        st.markdown(
            """
            <div class="hud" style="padding:10px 12px; margin-top: 10px;">
              <div class="micro">QUEUE</div>
              <div class="sub">Files are processed in order. Outputs are bundled into one ZIP at the end.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if "dur_cache" not in st.session_state:
            st.session_state.dur_cache = {}

        queue_rows = []
        speakers_on = bool(enable_speakers and speakers_available and int(num_speakers) > 1)
        rtf, samples = get_rtf(model=whisper_model, speakers=speakers_on)
        throughput = (1.0 / float(rtf)) if (rtf and rtf > 0) else 0.0
        eta_note = f"ETA uses learned speed (samples={samples})" if samples else "ETA uses default speed (no telemetry yet)"
        total_audio_seconds = 0.0
        total_eta_seconds = 0.0
        for uf in uploaded:
            buf = uf.getbuffer()
            cache_key = f"{uf.name}|{len(buf)}"
            dur = st.session_state.dur_cache.get(cache_key)
            if dur is None:
                try:
                    with tempfile.NamedTemporaryFile(prefix="transcriber-dur-", suffix=Path(uf.name).suffix, delete=True) as tmpf:
                        tmpf.write(buf)
                        tmpf.flush()
                        dur = probe_duration_seconds(tmpf.name)
                except Exception:
                    dur = None
                st.session_state.dur_cache[cache_key] = dur

            if dur:
                total_audio_seconds += float(dur)
                total_eta_seconds += float(dur) * float(rtf)
            queue_rows.append(
                {
                    "file": uf.name,
                    "size_mb": round(len(uf.getbuffer()) / (1024 * 1024), 2),
                    "duration": _format_duration(dur),
                    "eta": _format_eta((dur or 0.0) * float(rtf) if dur else None),
                    "status": "Queued",
                    "warning_summary": "—",
                    "skipped_summary": "—",
                    "output": "In final ZIP",
                }
            )
        st.dataframe(queue_rows, use_container_width=True, hide_index=True)
        st.caption(
            f"Model `{whisper_model}` • Throughput ~`{throughput:.2f}x` realtime • {eta_note}. "
            f"Estimate: `{_format_eta(total_eta_seconds)}` for `{_format_duration(total_audio_seconds)}` of audio on this machine."
        )

        start = st.button("Transcribe", type="primary", use_container_width=True)
        if st.session_state.get("auto_transcribe"):
            start = True
            st.session_state["auto_transcribe"] = False

        if not start:
            st.caption("Press Transcribe when ready.")
        else:
            try:
                ensure_ffmpeg_available()
            except RuntimeError as e:
                st.error(str(e))
            else:
                options = TranscriptionOptions(
                    whisper_model=whisper_model,
                    language=language.strip() or "en",
                    chunk_seconds=600,
                    num_speakers=int(num_speakers) if (enable_speakers and speakers_available) else None,
                    retain_audio=bool(retain_audio),
                    transcript_style=transcript_style,
                    vad=bool(vad) or bool(auto_clean),
                    normalize=bool(normalize) or bool(auto_clean),
                    denoise=bool(denoise),
                    redact=bool(redact),
                )

                with tempfile.TemporaryDirectory(prefix="transcriber-") as tmp:
                    tmp_dir = Path(tmp)
                    out_dir = tmp_dir / "out"
                    out_dir.mkdir(parents=True, exist_ok=True)

                    total = len(uploaded)
                    overall_bar = st.progress(0)
                    file_bar = st.progress(0)
                    status = st.empty()
                    preview = st.empty()
                    table = st.empty()

                    status.markdown("**Preparing model...**")
                    prep_bar = st.progress(0)

                    def _prep_cb(p: float, msg: str) -> None:
                        prep_bar.progress(int(max(0.0, min(1.0, float(p))) * 100))
                        if msg:
                            status.markdown(f"**Preparing model...** {msg}")

                    try:
                        prepare_whisper_model(options.whisper_model, progress_cb=_prep_cb)
                    except Exception as e:
                        st.error(str(e))
                    else:
                        prep_bar.progress(100)

                        transcripts: dict[str, str] = {}
                        briefs: dict[str, dict[str, str]] = {}
                        outputs: dict[str, dict] = {}
                        status_rows = [{**r} for r in queue_rows]

                        for idx, uf in enumerate(uploaded, start=1):
                            status_rows[idx - 1]["status"] = "Running"
                            table.dataframe(status_rows, use_container_width=True, hide_index=True)

                            status.markdown(f"**File:** `{uf.name}`  \n`{idx}/{total}`")
                            file_bar.progress(0)
                            preview.text_area("Live preview", value="", height=220)

                            audio_path = tmp_dir / _safe_uploaded_filename(uf.name, index=idx)
                            audio_path.write_bytes(uf.getbuffer())

                            def _preview_cb(t: str) -> None:
                                preview.text_area("Live preview", value=t, height=220)

                            def _progress_cb(p: float, msg: str) -> None:
                                p = max(0.0, min(1.0, float(p)))
                                file_bar.progress(int(p * 100))
                                overall_p = (idx - 1 + p) / max(1, total)
                                overall_bar.progress(int(overall_p * 100))
                                if msg:
                                    status.markdown(f"**File:** `{uf.name}`  \n`{idx}/{total}` - {msg}")

                            try:
                                result = transcribe_file(
                                    in_path=audio_path,
                                    out_dir=out_dir,
                                    options=options,
                                    progress_cb=_progress_cb,
                                    preview_cb=_preview_cb,
                                )
                            except RuntimeError as e:
                                status_rows[idx - 1]["status"] = "Error"
                                table.dataframe(status_rows, use_container_width=True, hide_index=True)
                                st.error(str(e))
                                break

                            transcript_path = result.output_dir / "transcript.txt"
                            if transcript_path.exists():
                                transcripts[uf.name] = transcript_path.read_text(encoding="utf-8", errors="replace")

                            snippets_path = result.output_dir / "brief_snippets.json"
                            if snippets_path.exists():
                                try:
                                    briefs[uf.name] = json.loads(snippets_path.read_text(encoding="utf-8"))
                                except Exception:
                                    pass

                            seg_path = result.output_dir / "segments.json"
                            segs = None
                            if seg_path.exists():
                                try:
                                    segs = json.loads(seg_path.read_text(encoding="utf-8"))
                                except Exception:
                                    segs = None
                            output_meta = _load_output_meta(result.output_dir)
                            status_rows[idx - 1]["warning_summary"] = output_meta["warning_summary"]
                            status_rows[idx - 1]["skipped_summary"] = output_meta["skipped_summary"]
                            outputs[uf.name] = {
                                "stem": result.output_dir.name,
                                "segments": segs,
                                "meta": output_meta,
                            }

                            status_rows[idx - 1]["status"] = "Done"
                            table.dataframe(status_rows, use_container_width=True, hide_index=True)

                            file_bar.progress(100)
                            overall_bar.progress(int(idx / total * 100))
                        else:
                            status.markdown("**Done.**")
                            zip_bytes = _zip_dir(out_dir)

                            st.session_state.last_zip_bytes = zip_bytes
                            st.session_state.last_transcripts = transcripts
                            st.session_state.last_briefs = briefs
                            st.session_state.last_outputs = outputs

                            st.success("Transcription complete.")
                            st.download_button(
                                label="Download transcripts (.zip)",
                                data=zip_bytes,
                                file_name="transcripts.zip",
                                mime="application/zip",
                            )
                            st.caption(
                                "Outputs include transcript.txt (timestamps + speakers), transcript_plain.txt, segments.json, transcript.srt, transcript.vtt per file."
                            )
    else:
        st.info("Upload one or more audio files to start.")
        st.caption("You can still use the Hot folder and Transcript tabs without uploading first.")

with tabs[1]:
    st.markdown(
        """
        <div class="hud" style="padding:10px 12px; margin-top: 6px;">
          <div class="micro">HOT FOLDER</div>
          <div class="sub">Drop files into a folder. Scan-and-run now, or enable auto-watch (optional).</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    folder = st.text_input("Folder to watch", value="", placeholder=r"C:\path\to\folder")
    out_dir = st.text_input("Output folder", value="", placeholder=r"(default: <folder>\\_transcripts)")
    recursive = st.checkbox("Include subfolders", value=True)
    use_hash = st.checkbox("Hash changed files before skip (safer, slower)", value=False)
    always_hash_before_skip = st.checkbox("Always hash before skip (correctness-first, slowest)", value=False)
    st.caption(
        "Default de-duplication skips files by size + modified time. Hash modes add extra disk I/O but catch copied/replaced-file edge cases more reliably."
    )

    hotfolder_deps = bool(importlib.util.find_spec("watchdog"))
    if not hotfolder_deps:
        st.caption("Auto-watch requires `watchdog`. Install with: `python -m pip install -r requirements-hotfolder.txt`.")

    cols = st.columns(3)
    scan_now = cols[0].button("Scan & transcribe new", type="primary", use_container_width=True)
    start_watch = cols[1].button("Start watching", disabled=not hotfolder_deps, use_container_width=True)
    stop_watch = cols[2].button(
        "Stop watching",
        disabled=(st.session_state.hotfolder_proc is None) or (st.session_state.hotfolder_proc.poll() is not None),
        use_container_width=True,
    )

    folder_path = Path(folder).expanduser() if folder.strip() else None
    if folder_path and not out_dir.strip():
        out_dir_path = folder_path / "_transcripts"
    else:
        out_dir_path = Path(out_dir).expanduser() if out_dir.strip() else None

    if scan_now:
        if not folder_path or not folder_path.exists() or not folder_path.is_dir():
            st.error("Pick an existing folder.")
        elif not out_dir_path:
            st.error("Pick an output folder.")
        else:
            out_dir_path.mkdir(parents=True, exist_ok=True)
            state = load_state(out_dir_path)
            files = iter_audio_files(folder_path, recursive=bool(recursive))
            new_files: list[Path] = []
            state_dirty = False
            for f in files:
                key = rel_key(folder_path, f)
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
                save_state(out_dir_path, state)

            st.write(f"Found {len(files)} audio file(s). New/changed: {len(new_files)}.")
            if not new_files:
                st.info("No new or changed audio files were found for this hot-folder run.")
            else:
                try:
                    ensure_ffmpeg_available()
                except RuntimeError as e:
                    st.error(str(e))
                else:
                    options = TranscriptionOptions(
                        whisper_model=whisper_model,
                        language=(language.strip() or "en"),
                        chunk_seconds=600,
                        num_speakers=int(num_speakers) if (enable_speakers and speakers_available) else None,
                        retain_audio=bool(retain_audio),
                        transcript_style=transcript_style,
                        vad=bool(vad) or bool(auto_clean),
                        normalize=bool(normalize) or bool(auto_clean),
                        denoise=bool(denoise),
                        redact=bool(redact),
                    )
                    prepare_whisper_model(options.whisper_model, progress_cb=None)

                    bar = st.progress(0)
                    status = st.empty()
                    for i, f in enumerate(new_files, start=1):
                        status.markdown(f"**Transcribing:** `{f.name}` (`{i}/{len(new_files)}`)")
                        try:
                            key = rel_key(folder_path, f)
                            decision = decide_file_action(
                                f,
                                state.get(key),
                                use_hash=bool(use_hash),
                                always_hash_before_skip=bool(always_hash_before_skip),
                            )
                            if not decision.should_process:
                                if decision.persist_state:
                                    state[key] = decision.signature
                                    save_state(out_dir_path, state)
                                continue
                            transcribe_file(in_path=f, out_dir=out_dir_path, options=options, progress_cb=None, preview_cb=None)
                            state[key] = decision.signature
                            save_state(out_dir_path, state)
                        except Exception as e:
                            st.error(f"{f.name}: {e}")
                        bar.progress(int(i / len(new_files) * 100))
                    st.success("Hot-folder scan complete.")

    if start_watch:
        if not folder_path or not folder_path.exists() or not folder_path.is_dir():
            st.error("Pick an existing folder.")
        elif not out_dir_path:
            st.error("Pick an output folder.")
        else:
            proc = st.session_state.hotfolder_proc
            if proc is not None and proc.poll() is None:
                st.info("Watcher already running.")
            else:
                logs_dir = Path(__file__).parent / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                log_path = logs_dir / "hotfolder_watch.log"

                cmd = [
                    sys.executable,
                    os.fspath(Path(__file__).parent / "watch_hotfolder.py"),
                    "--folder",
                    os.fspath(folder_path),
                    "--out",
                    os.fspath(out_dir_path),
                    "--model",
                    whisper_model,
                    "--language",
                    (language.strip() or "en"),
                ]
                if recursive:
                    cmd.append("--recursive")
                if use_hash:
                    cmd.append("--hash")
                if always_hash_before_skip:
                    cmd.append("--always-hash-before-skip")
                if enable_speakers and speakers_available:
                    cmd += ["--speakers", str(int(num_speakers))]
                cmd += ["--style", transcript_style]
                if bool(vad) or bool(auto_clean):
                    cmd.append("--vad")
                if bool(normalize) or bool(auto_clean):
                    cmd.append("--normalize")
                if bool(denoise):
                    cmd.append("--denoise")
                if bool(redact):
                    cmd.append("--redact")

                lf = log_path.open("a", encoding="utf-8")
                lf.write("\n--- START watcher ---\n")
                lf.flush()
                st.session_state.hotfolder_proc = subprocess.Popen(
                    cmd,
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    cwd=Path(__file__).parent,
                )
                st.success("Watcher started. Leave this tab open to monitor logs.")

    if stop_watch:
        proc = st.session_state.hotfolder_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        st.session_state.hotfolder_proc = None
        st.info("Watcher stopped.")

    log_path = Path(__file__).parent / "logs" / "hotfolder_watch.log"
    if log_path.exists():
        try:
            txt = log_path.read_text(encoding="utf-8", errors="replace")
            tail = "\n".join(txt.splitlines()[-100:])
            st.text_area("Watcher log (tail)", value=tail, height=280)
        except Exception:
            pass

with tabs[2]:
    st.markdown(
        """
        <div class="hud" style="padding:10px 12px; margin-top: 6px;">
          <div class="micro">TRANSCRIPT VIEW</div>
          <div class="sub">Search and skim. You can also reopen a saved transcript ZIP or output folder.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    load_zip = st.file_uploader("Load saved transcript ZIP", type=["zip"], key="load_saved_zip")
    load_folder = st.text_input(
        "Or load saved transcript folder",
        value="",
        placeholder="/path/to/_transcripts",
        key="load_saved_folder",
    )
    load_existing = st.button("Load saved outputs", use_container_width=True)

    if load_existing:
        try:
            if load_zip is not None:
                transcripts, briefs, outputs, zip_bytes = _load_saved_outputs_from_zip_bytes(load_zip.getvalue())
            elif load_folder.strip():
                load_root = _validated_saved_output_dir(load_folder)
                transcripts, briefs, outputs, zip_bytes = _load_saved_outputs_from_dir(load_root)
            else:
                raise RuntimeError("Choose a transcript ZIP or an output folder first.")

            if not transcripts:
                raise RuntimeError("No transcript outputs were found in the selected ZIP/folder.")

            st.session_state.last_transcripts = transcripts
            st.session_state.last_briefs = briefs
            st.session_state.last_outputs = outputs
            st.session_state.last_zip_bytes = zip_bytes
            st.success(f"Loaded {len(transcripts)} transcript output(s).")
        except Exception as exc:
            st.error(f"Could not load saved outputs: {exc}")

    transcripts: dict[str, str] = st.session_state.get("last_transcripts") or {}
    outputs: dict[str, dict] = st.session_state.get("last_outputs") or {}
    selected = ""
    text = ""
    briefs: dict[str, dict[str, str]] = st.session_state.get("last_briefs") or {}
    segs: list[dict] = []
    stem = None
    output_meta: dict = {}
    query = ""
    audio_bytes: bytes | None = None
    audio_mime: str | None = None
    if not transcripts:
        st.info("No transcript loaded yet. Run a transcription first, or load a saved ZIP/folder above.")
    else:
        files = sorted(transcripts.keys())
        selected = st.selectbox("File", files, index=0, key="sel_file")

        text = transcripts.get(selected, "")
        briefs = st.session_state.get("last_briefs") or {}
        segs = (outputs.get(selected) or {}).get("segments") or []
        stem = (outputs.get(selected) or {}).get("stem")
        output_meta = (outputs.get(selected) or {}).get("meta") or {}
        query = st.text_input("Search", value="", placeholder="Search segments...", key="seg_query")

        warnings = output_meta.get("warnings") or []
        skipped_total = int(output_meta.get("skipped_total") or 0)
        skipped_vad = int(output_meta.get("skipped_vad_empty") or 0)
        skipped_quiet = int(output_meta.get("skipped_quiet") or 0)
        with st.expander("Diagnostics", expanded=False):
            st.write(
                {
                    "warning_summary": output_meta.get("warning_summary"),
                    "skipped_summary": output_meta.get("skipped_summary"),
                    "preflight": output_meta.get("preflight") or {},
                    "run_stats": output_meta.get("run_stats") or {},
                }
            )
        if warnings or skipped_total:
            st.markdown(
                """
                <div class="hud" style="padding:10px 12px; margin-top: 10px;">
                  <div class="micro">FILE WARNINGS</div>
                  <div class="sub">Preflight and non-fatal processing notices for the selected file.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            for warning in warnings:
                st.warning(warning)
            if skipped_total:
                detail_parts = []
                if skipped_vad:
                    detail_parts.append(f"{skipped_vad} VAD-trimmed empty")
                if skipped_quiet:
                    detail_parts.append(f"{skipped_quiet} ultra-quiet")
                detail_txt = f" ({', '.join(detail_parts)})" if detail_parts else ""
                st.info(f"Skipped chunks: {skipped_total}{detail_txt}.")

        # Playback sync (best-effort).
        zip_bytes = st.session_state.get("last_zip_bytes")
        if zip_bytes and stem:
            try:
                with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
                    for cand, mime in ((f"{stem}/audio_preview.mp3", "audio/mpeg"), (f"{stem}/audio.wav", "audio/wav")):
                        try:
                            audio_bytes = zf.read(cand)
                            audio_mime = mime
                            break
                        except Exception:
                            continue
            except Exception:
                audio_bytes = None

    if transcripts and audio_bytes:
        # Data URI approach enables click-to-jump timestamps.
        max_embed = 12 * 1024 * 1024
        if len(audio_bytes) <= max_embed:
            mime = audio_mime or "audio/mpeg"
            b64 = base64.b64encode(audio_bytes).decode("ascii")
            st.markdown(
                f"""
                <div class="hud" style="padding:10px 12px; margin-top: 10px;">
                  <div class="micro">PLAYBACK</div>
                  <div class="sub">Click a segment to jump playback to its timestamp.</div>
                </div>
                <audio id="tr_player" controls style="width:100%; margin-top:10px;">
                  <source src="data:{mime};base64,{b64}" />
                </audio>
                <script>
                  window.__transcriber_jump = (t) => {{
                    const p = document.getElementById('tr_player');
                    if(!p) return;
                    try {{
                      p.currentTime = Math.max(0, Number(t)||0);
                      p.play();
                    }} catch(e) {{}}
                  }};
                </script>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="hud" style="padding:10px 12px; margin-top: 10px;">
                  <div class="micro">PLAYBACK</div>
                  <div class="sub">Audio is large; showing a normal player (no click-to-jump).</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.audio(audio_bytes)
    elif transcripts:
        st.caption("Playback preview is unavailable for this result set. Load the ZIP output to restore bundled audio artifacts.")

    # Segment-first transcript view (uses segments.json metadata).
    if transcripts and segs:
        st.markdown(
            """
            <div class="hud" style="padding:10px 12px; margin-top: 10px;">
              <div class="micro">SEGMENTS</div>
              <div class="sub">Search + filter segments. Click a segment to jump playback.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="conf-legend">
              <span class="conf-chip low"><span class="dot"></span>Low confidence</span>
              <span class="conf-chip mid"><span class="dot"></span>Review</span>
              <span class="conf-chip good"><span class="dot"></span>Stronger match</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Confidence is estimated from Whisper metadata (avg_logprob, no_speech_prob, compression_ratio).")

        def _conf_score(s: dict) -> float:
            w = s.get("whisper") or {}
            try:
                alp = float(w.get("avg_logprob"))
            except Exception:
                alp = None
            try:
                nsp = float(w.get("no_speech_prob"))
            except Exception:
                nsp = None
            try:
                cr = float(w.get("compression_ratio"))
            except Exception:
                cr = None

            score = 0.55
            if alp is not None:
                score = max(0.0, min(1.0, (alp + 3.0) / 3.0))
            if nsp is not None:
                score *= max(0.0, min(1.0, 1.0 - nsp))
            if cr is not None and cr > 2.4:
                score *= 0.75
            return float(score)

        # Filters
        speakers = sorted({str((s.get("speaker") or "").strip() or "Speaker") for s in segs})
        cols = st.columns([2, 2, 2])
        speaker_filter = cols[0].multiselect("Speaker", options=speakers, default=speakers, key="seg_speaker_filter")
        min_conf = cols[1].slider("Min confidence", min_value=0.0, max_value=1.0, value=0.0, step=0.05, key="seg_min_conf")
        show_low_only = cols[2].checkbox("Low-confidence only", value=False, key="seg_low_only")

        cols2 = st.columns(3)
        want_digits = cols2[0].checkbox("Contains digits", value=False, key="seg_digits")
        want_questions = cols2[1].checkbox("Questions", value=False, key="seg_questions")
        want_caps = cols2[2].checkbox("Capitalized names", value=False, key="seg_caps")

        # If low-only is enabled, treat as "below threshold" gate.
        low_threshold = 0.35
        if show_low_only:
            low_threshold = st.slider(
                "Low-confidence threshold",
                min_value=0.05,
                max_value=0.75,
                value=0.35,
                step=0.05,
                key="seg_low_threshold",
            )

        shown = 0
        blocks: list[str] = []
        for s in segs:
            txt = (s.get("text") or "").strip()
            if not txt:
                continue
            sc = _conf_score(s)
            if show_low_only and sc >= float(low_threshold):
                continue
            if sc < float(min_conf):
                continue
            start = float(s.get("start") or 0.0)
            spk = (s.get("speaker") or "").strip() or "Speaker"
            if speaker_filter and spk not in set(speaker_filter):
                continue
            if query.strip():
                q = query.strip().lower()
                if q not in txt.lower() and q not in spk.lower():
                    continue
            if want_digits and not any(ch.isdigit() for ch in txt):
                continue
            if want_questions and "?" not in txt:
                continue
            if want_caps and not re.search(r"\b[A-Z][a-z]{2,}\b", txt):
                continue
            cls = "good"
            if sc < float(low_threshold):
                cls = "low"
                conf_label = "Low confidence"
            elif sc < float(low_threshold) + 0.15:
                cls = "mid"
                conf_label = "Review"
            else:
                conf_label = "Stronger match"

            spk_conf = s.get("speaker_confidence")
            spk_conf_txt = ""
            try:
                if spk_conf is not None:
                    spk_conf_txt = f" • spk {float(spk_conf):.2f}"
            except Exception:
                spk_conf_txt = ""

            blocks.append(
                f"""
                <div class="seg {cls}" onclick="window.__transcriber_jump && window.__transcriber_jump({start:.3f});">
                  <div class="seg-h">{_html.escape(_format_duration(start))} <span class="spk">{_html.escape(spk)}</span> <span class="conf-chip {cls}"><span class="dot"></span>{_html.escape(conf_label)}</span> <span class="sc">{sc:.2f}{_html.escape(spk_conf_txt)}</span></div>
                  <div class="seg-t">{_html.escape(txt)}</div>
                </div>
                """
            )
            shown += 1
            if shown >= 220:
                break

        st.markdown(
            """
            <style>
              .seg{ border-radius: 16px; padding: 10px 12px; border:1px solid rgba(167,240,255,0.14); background: rgba(255,255,255,0.05); margin-top:10px; }
              .seg{ cursor: pointer; transition: transform .08s ease, box-shadow .12s ease; }
              .seg:hover{ transform: translateY(-1px); box-shadow: 0 18px 40px rgba(0,0,0,0.22); }
              .seg-h{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
                      color: rgba(236,243,255,0.82); letter-spacing: .05em; font-size: .75rem; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
              .seg-h .spk{ color: rgba(167,240,255,0.95); }
              .seg-h .sc{ margin-left:auto; color: rgba(185,212,255,0.85); }
              .seg-t{ margin-top:6px; color: rgba(236,243,255,0.92); }
              .seg.low{ border-color: rgba(255, 96, 136, 0.35); }
              .seg.mid{ border-color: rgba(255, 210, 107, 0.30); }
              .seg.good{ border-color: rgba(167,240,255,0.16); }
            </style>
            """,
            unsafe_allow_html=True,
        )
        if blocks:
            st.markdown("".join(blocks), unsafe_allow_html=True)
            st.caption(f"Showing up to {shown} segments.")
        else:
            st.info("No segments match your filters.")

        with st.expander("Raw transcript", expanded=False):
            if query.strip():
                q = query.strip().lower()
                filtered = "\n".join([ln for ln in text.splitlines() if q in ln.lower()])
                st.text_area("Transcript (filtered)", value=filtered, height=360)
            else:
                st.text_area("Transcript", value=text, height=360)
    elif transcripts:
        # Fallback if segments.json isn't available.
        if query.strip():
            q = query.strip().lower()
            filtered = "\n".join([ln for ln in text.splitlines() if q in ln.lower()])
            st.text_area("Transcript (filtered)", value=filtered, height=420)
        else:
            st.text_area("Transcript", value=text, height=420)

    brief = briefs.get(selected)
    if transcripts and brief:
        if st.session_state.get("focus_brief"):
            st.session_state["focus_brief"] = False
            try:
                st.toast("Brief Pack ready.", icon=None)
            except Exception:
                pass
        st.markdown(
            """
            <div class="hud" style="padding:10px 12px; margin-top: 10px;">
              <div class="micro">BRIEF PACK</div>
              <div class="sub">Copy/paste outputs plus heuristic highlights from the generated brief.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="brief-note">
              Heuristic highlights in <code>brief.md</code> and <code>brief.html</code> are chosen automatically.
              The picker favors longer, higher-confidence, information-dense moments (for example numbers, questions, and named entities)
              while spreading selections across the timeline.
            </div>
            """,
            unsafe_allow_html=True,
        )

        email_txt = str(brief.get("email") or "").strip()
        wa_txt = str(brief.get("whatsapp") or "").strip()

        def _copy_widget(key: str, label: str, value: str) -> None:
            display = _html.escape(value)
            dom_id = _safe_dom_id(key)
            js_value = json.dumps(value)
            st.markdown(
                f"""
                <div style="margin-top:10px;">
                  <div class="micro" style="margin-bottom:6px;">{label}</div>
                  <button id="{dom_id}_btn" style="width:100%; padding:10px 12px; border-radius:14px; border:1px solid rgba(167,240,255,0.18); background: rgba(255,255,255,0.06); color: rgba(236,243,255,0.92); letter-spacing:0.06em; text-transform:uppercase;">
                    Copy
                  </button>
                  <pre id="{dom_id}_txt" style="white-space:pre-wrap; word-break:break-word; margin-top:10px; background: rgba(0,0,0,0.18); border:1px solid rgba(167,240,255,0.14); border-radius:14px; padding:12px 12px; color: rgba(236,243,255,0.92);">{display}</pre>
                </div>
                <script>
                  (function(){{
                    const btn = document.getElementById("{dom_id}_btn");
                    const txt = {js_value};
                    if(btn) btn.onclick = async () => {{
                      try {{ await navigator.clipboard.writeText(txt); btn.textContent = "Copied"; setTimeout(()=>btn.textContent="Copy", 900); }}
                      catch(e) {{ btn.textContent = "Copy failed"; setTimeout(()=>btn.textContent="Copy", 1200); }}
                    }};
                  }})();
                </script>
                """,
                unsafe_allow_html=True,
            )

        _copy_widget(f"email_{selected}".replace(".", "_"), "Email-ready", email_txt)
        _copy_widget(f"wa_{selected}".replace(".", "_"), "WhatsApp-ready", wa_txt)

        # Link to brief.html if present in the ZIP output
        st.caption("Also saved per file as `brief.md` and `brief.html` inside the output ZIP.")

st.markdown(
    '<div class="footer"><span class="dot" title="I listened all the way through.">&bull;</span></div>',
    unsafe_allow_html=True,
)
