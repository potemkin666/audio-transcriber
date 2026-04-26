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
from pathlib import Path

import streamlit as st

from transcriber.core import TranscriptionOptions, prepare_whisper_model, transcribe_file
from transcriber.ffmpeg import ensure_ffmpeg_available, probe_duration_seconds, ffmpeg_version_line, ffprobe_version_line, find_ffmpeg_tools
from transcriber.hotfolder import FileSignature, iter_audio_files, load_state, rel_key, save_state, sha256_file, stat_signature
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


def _data_uri(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    ext = path.suffix.lower()
    mime = "image/jpeg" if ext in {".jpg", ".jpeg"} else "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _apply_cyberlife_ui(*, water_uri: str | None, overlay_uri: str | None) -> None:
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
        --line: rgba(75,180,255,0.40);
        --line2: rgba(167,240,255,0.28);
        --glass: rgba(255,255,255,0.10);
      }

      html, body, [data-testid="stAppViewContainer"]{
        background:
          radial-gradient(1200px 760px at 70% 10%, rgba(75,180,255,0.42), transparent 58%),
          radial-gradient(980px 600px at 25% 45%, rgba(167,240,255,0.24), transparent 62%),
          linear-gradient(180deg, var(--bg0), var(--bg1));
        color: var(--ink);
      }

      /* Water texture overlay */
      [data-testid="stAppViewContainer"]::before{
        content:"";
        position: fixed;
        inset: 0;
        __WATER_CSS__
        background-size: cover;
        background-position: center;
        opacity: 0.46;
        filter: saturate(1.45) contrast(1.10) brightness(1.18);
        animation: driftA 22s ease-in-out infinite alternate;
        pointer-events: none;
        z-index: 0;
      }

      /* Bright overlay shards */
      [data-testid="stAppViewContainer"]::after{
        content:"";
        position: fixed;
        inset: -10%;
        __OVERLAY_CSS__
        background-size: cover;
        background-position: center;
        opacity: 0.30;
        filter: saturate(1.45) contrast(1.18) brightness(1.20) blur(0.25px);
        mix-blend-mode: screen;
        animation: driftB 28s ease-in-out infinite alternate;
        pointer-events: none;
        z-index: 0;
      }

      @keyframes driftA {
        0%   { transform: translate3d(0px, 0px, 0px) scale(1.02); }
        100% { transform: translate3d(-10px, 14px, 0px) scale(1.05); }
      }
      @keyframes driftB {
        0%   { transform: translate3d(0px, 0px, 0px) scale(1.03); }
        100% { transform: translate3d(16px, -12px, 0px) scale(1.06); }
      }

      /* Lift app above overlay */
      [data-testid="stAppViewContainer"] > .main {
        position: relative;
        z-index: 1;
      }

      [data-testid="stHeader"]{ background: transparent; }
      [data-testid="stSidebar"]{
        background: rgba(255,255,255,0.06);
        border-right: 1px solid rgba(167,240,255,0.25);
        backdrop-filter: blur(10px);
      }

      .block-container{ padding-top: 1.0rem; }

      h1, h2, h3{
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }

      /* Buttons */
      button[kind="primary"]{
        background: linear-gradient(90deg, rgba(167,240,255,0.95), rgba(75,180,255,0.95)) !important;
        color: #03101F !important;
        border: 0 !important;
        letter-spacing: 0.03em;
        text-transform: uppercase;
        box-shadow:
          0 0 0 1px rgba(167,240,255,0.25),
          0 12px 30px rgba(75,180,255,0.28),
          0 0 30px rgba(167,240,255,0.18) !important;
      }

      /* Progress */
      div[data-testid="stProgress"] > div{ background: rgba(75,180,255,0.22); }
      div[data-testid="stProgress"] div[role="progressbar"]{
        background: linear-gradient(90deg, var(--blue), var(--cyan));
        box-shadow: 0 0 22px rgba(167,240,255,0.25);
      }

      /* Alerts */
      [data-testid="stAlert"]{
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(167,240,255,0.24);
      }

      /* HUD */
      .hud{
        border: 1px solid rgba(167,240,255,0.26);
        border-radius: 18px;
        padding: 14px 16px;
        background: linear-gradient(180deg, rgba(255,255,255,0.12), rgba(255,255,255,0.05));
        position: relative;
        overflow: hidden;
        box-shadow:
          0 0 0 1px rgba(167,240,255,0.20),
          0 22px 54px rgba(0,0,0,0.35),
          0 0 46px rgba(167,240,255,0.12);
        backdrop-filter: blur(10px);
      }

      .hud:before{
        content:"";
        position:absolute;
        left:-20%; top:-50%;
        width: 140%; height: 200%;
        background: repeating-linear-gradient(
          0deg,
          rgba(66,165,255,0.00),
          rgba(66,165,255,0.00) 8px,
          rgba(66,165,255,0.06) 9px
        );
        transform: rotate(7deg);
        pointer-events:none;
      }

      .tag{
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        color: rgba(236,243,255,0.94);
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-size: 0.85rem;
        text-shadow: 0 0 22px rgba(167,240,255,0.28);
      }
      .tag .blue{ color: var(--blue); }
      .sub{ color: var(--muted); margin-top: 0.25rem; }

      .micro{
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        color: rgba(236,243,255,0.80);
        letter-spacing: 0.10em;
        text-transform: uppercase;
        font-size: 0.78rem;
      }

      .y2k-chip{
        display:inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        border: 1px solid rgba(167,240,255,0.30);
        background: rgba(255,255,255,0.08);
        backdrop-filter: blur(8px);
        box-shadow: 0 0 22px rgba(167,240,255,0.18);
      }

      /* Footer */
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
        border: 1px solid rgba(167,240,255,0.16);
        background: rgba(255,255,255,0.04);
        box-shadow: 0 0 24px rgba(167,240,255,0.10);
      }
    </style>
    """

    css = css.replace("__WATER_CSS__", water_css).replace("__OVERLAY_CSS__", overlay_css)
    st.markdown(css, unsafe_allow_html=True)


st.set_page_config(page_title="TRANSCRIBER", layout="centered")
assets_dir = Path(__file__).parent / "assets" / "theme"
_apply_cyberlife_ui(
    water_uri=_data_uri(assets_dir / "background.jpg"),
    overlay_uri=_data_uri(assets_dir / "overlay.jpg"),
)

st.markdown(
    """
    <div class="hud">
      <div class="tag"><span class="blue">CYBERLIFE</span> AUDIO TRANSCRIPTION SUITE <span class="y2k-chip">Y2K</span></div>
      <div class="sub">Local transcription (MP3/M4A/MP4) - outputs with timestamps + optional speakers</div>
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

with st.sidebar:
    st.header("Settings")
    whisper_model = st.selectbox("Model", ["tiny", "base", "small", "medium", "large"], index=2)
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
    )
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

    if not uploaded:
        st.info("Upload one or more audio files to start.")
        st.stop()

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
                "output": "In final ZIP",
            }
        )
    st.dataframe(queue_rows, use_container_width=True, hide_index=True)
    st.caption(f"{eta_note}. Total audio: `{_format_duration(total_audio_seconds)}` • Total ETA: `{_format_eta(total_eta_seconds)}`")

    start = st.button("Transcribe", type="primary", use_container_width=True)
    if not start:
        st.caption("Press Transcribe when ready.")
        st.stop()

    try:
        ensure_ffmpeg_available()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    options = TranscriptionOptions(
        whisper_model=whisper_model,
        language=language.strip() or "en",
        chunk_seconds=600,
        num_speakers=int(num_speakers) if (enable_speakers and speakers_available) else None,
        retain_audio=True,
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
            st.stop()
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

            audio_path = tmp_dir / uf.name
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
                st.stop()

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
            outputs[uf.name] = {"stem": result.output_dir.name, "segments": segs}

            status_rows[idx - 1]["status"] = "Done"
            table.dataframe(status_rows, use_container_width=True, hide_index=True)

            file_bar.progress(100)
            overall_bar.progress(int(idx / total * 100))

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
    use_hash = st.checkbox("Safer de-dupe (SHA256 hashing, slower)", value=False)

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
            st.stop()
        if not out_dir_path:
            st.error("Pick an output folder.")
            st.stop()

        out_dir_path.mkdir(parents=True, exist_ok=True)
        state = load_state(out_dir_path)
        files = iter_audio_files(folder_path, recursive=bool(recursive))
        new_files: list[Path] = []
        for f in files:
            key = rel_key(folder_path, f)
            sig = stat_signature(f)
            prev = state.get(key)
            if prev and prev.size == sig.size and prev.mtime_ns == sig.mtime_ns and (not use_hash or prev.sha256):
                continue
            new_files.append(f)

        st.write(f"Found {len(files)} audio file(s). New/changed: {len(new_files)}.")
        if not new_files:
            st.stop()

        try:
            ensure_ffmpeg_available()
        except RuntimeError as e:
            st.error(str(e))
            st.stop()

        options = TranscriptionOptions(
            whisper_model=whisper_model,
            language=(language.strip() or "en"),
            chunk_seconds=600,
            num_speakers=int(num_speakers) if (enable_speakers and speakers_available) else None,
        )
        prepare_whisper_model(options.whisper_model, progress_cb=None)

        bar = st.progress(0)
        status = st.empty()
        for i, f in enumerate(new_files, start=1):
            status.markdown(f"**Transcribing:** `{f.name}` (`{i}/{len(new_files)}`)")
            try:
                transcribe_file(in_path=f, out_dir=out_dir_path, options=options, progress_cb=None, preview_cb=None)
                sig = stat_signature(f)
                key = rel_key(folder_path, f)
                sha = sha256_file(f) if use_hash else None
                state[key] = FileSignature(size=sig.size, mtime_ns=sig.mtime_ns, sha256=sha)
                save_state(out_dir_path, state)
            except Exception as e:
                st.error(f"{f.name}: {e}")
            bar.progress(int(i / len(new_files) * 100))
        st.success("Hot-folder scan complete.")

    if start_watch:
        if not folder_path or not folder_path.exists() or not folder_path.is_dir():
            st.error("Pick an existing folder.")
            st.stop()
        if not out_dir_path:
            st.error("Pick an output folder.")
            st.stop()

        proc = st.session_state.hotfolder_proc
        if proc is not None and proc.poll() is None:
            st.info("Watcher already running.")
            st.stop()

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
        if enable_speakers and speakers_available:
            cmd += ["--speakers", str(int(num_speakers))]

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
          <div class="sub">Search and skim. Download the ZIP from the Transcribe tab.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    transcripts: dict[str, str] = st.session_state.get("last_transcripts") or {}
    outputs: dict[str, dict] = st.session_state.get("last_outputs") or {}
    if not transcripts:
        st.info("No transcript yet. Run a transcription first.")
        st.stop()

    files = sorted(transcripts.keys())
    selected = st.selectbox("File", files, index=0)
    query = st.text_input("Search", value="", placeholder="Type to filter...")

    text = transcripts.get(selected, "")
    briefs: dict[str, dict[str, str]] = st.session_state.get("last_briefs") or {}
    segs = (outputs.get(selected) or {}).get("segments") or []
    stem = (outputs.get(selected) or {}).get("stem")
    if query.strip():
        q = query.strip().lower()
        filtered = "\n".join([ln for ln in text.splitlines() if q in ln.lower()])
        st.text_area("Transcript (filtered)", value=filtered, height=420)
    else:
        st.text_area("Transcript", value=text, height=420)

    # Playback sync (best-effort).
    zip_bytes = st.session_state.get("last_zip_bytes")
    audio_bytes: bytes | None = None
    audio_mime: str | None = None
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

    if audio_bytes:
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

    # Confidence-highlighted segment view (uses segments.json metadata).
    if segs:
        st.markdown(
            """
            <div class="hud" style="padding:10px 12px; margin-top: 10px;">
              <div class="micro">SEGMENTS (QA)</div>
              <div class="sub">Highlights low-confidence lines using Whisper metadata.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

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

        only_low = st.checkbox("Show only low-confidence", value=False)
        threshold = st.slider("Low-confidence threshold", min_value=0.05, max_value=0.75, value=0.35, step=0.05)

        shown = 0
        blocks: list[str] = []
        for s in segs:
            txt = (s.get("text") or "").strip()
            if not txt:
                continue
            sc = _conf_score(s)
            if only_low and sc >= float(threshold):
                continue
            start = float(s.get("start") or 0.0)
            spk = (s.get("speaker") or "").strip()
            cls = "good"
            if sc < float(threshold):
                cls = "low"
            elif sc < float(threshold) + 0.15:
                cls = "mid"

            blocks.append(
                f"""
                <div class="seg {cls}" onclick="window.__transcriber_jump && window.__transcriber_jump({start:.3f});">
                  <div class="seg-h">{_html.escape(_format_duration(start))} <span class="spk">{_html.escape(spk)}</span> <span class="sc">{sc:.2f}</span></div>
                  <div class="seg-t">{_html.escape(txt)}</div>
                </div>
                """
            )
            shown += 1
            if shown >= 120:
                break

        st.markdown(
            """
            <style>
              .seg{ border-radius: 16px; padding: 10px 12px; border:1px solid rgba(167,240,255,0.14); background: rgba(255,255,255,0.05); margin-top:10px; }
              .seg{ cursor: pointer; transition: transform .08s ease, box-shadow .12s ease; }
              .seg:hover{ transform: translateY(-1px); box-shadow: 0 18px 40px rgba(0,0,0,0.22); }
              .seg-h{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
                      color: rgba(236,243,255,0.82); letter-spacing: .10em; text-transform: uppercase; font-size: .75rem; display:flex; gap:10px; align-items:center; }
              .seg-h .spk{ color: rgba(167,240,255,0.95); }
              .seg-h .sc{ margin-left:auto; color: rgba(185,212,255,0.85); }
              .seg-t{ margin-top:6px; color: rgba(236,243,255,0.92); }
              .seg.low{ border-color: rgba(255, 96, 136, 0.45); box-shadow: 0 0 24px rgba(255, 96, 136, 0.12); }
              .seg.mid{ border-color: rgba(255, 210, 107, 0.40); box-shadow: 0 0 24px rgba(255, 210, 107, 0.10); }
              .seg.good{ border-color: rgba(167,240,255,0.16); }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("".join(blocks), unsafe_allow_html=True)

    brief = briefs.get(selected)
    if brief:
        st.markdown(
            """
            <div class="hud" style="padding:10px 12px; margin-top: 10px;">
              <div class="micro">BRIEF PACK</div>
              <div class="sub">Copy/paste for leadership or ops channels.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        email_txt = str(brief.get("email") or "").strip()
        wa_txt = str(brief.get("whatsapp") or "").strip()

        def _copy_widget(key: str, label: str, value: str) -> None:
            display = _html.escape(value)
            js = (
                value.replace("\\", "\\\\")
                .replace("`", "\\`")
                .replace("${", "\\${")
                .replace("</script", "<\\/script")
            )
            st.markdown(
                f"""
                <div style="margin-top:10px;">
                  <div class="micro" style="margin-bottom:6px;">{label}</div>
                  <button id="{key}_btn" style="width:100%; padding:10px 12px; border-radius:14px; border:1px solid rgba(167,240,255,0.18); background: rgba(255,255,255,0.06); color: rgba(236,243,255,0.92); letter-spacing:0.06em; text-transform:uppercase;">
                    Copy
                  </button>
                  <pre id="{key}_txt" style="white-space:pre-wrap; word-break:break-word; margin-top:10px; background: rgba(0,0,0,0.18); border:1px solid rgba(167,240,255,0.14); border-radius:14px; padding:12px 12px; color: rgba(236,243,255,0.92);">{display}</pre>
                </div>
                <script>
                  (function(){{
                    const btn = document.getElementById("{key}_btn");
                    const txt = `{js}`;
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
