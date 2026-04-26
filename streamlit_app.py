from __future__ import annotations

import base64
import io
import tempfile
import zipfile
import importlib.util
from pathlib import Path

import streamlit as st

from transcriber.core import TranscriptionOptions, prepare_whisper_model, transcribe_file
from transcriber.ffmpeg import ensure_ffmpeg_available


SUPPORTED_TYPES = ["mp3", "m4a", "mp4", "aac", "wav", "flac", "ogg", "m4b", "webm"]


def _zip_dir(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in root.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(root))
    return buf.getvalue()


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

tabs = st.tabs(["Transcribe", "Transcript"])

if "last_zip_bytes" not in st.session_state:
    st.session_state.last_zip_bytes = None
if "last_transcripts" not in st.session_state:
    st.session_state.last_transcripts = {}

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
    st.caption("Tip: start with Small. If it's slow, use Base.")

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

    queue_rows = []
    for uf in uploaded:
        queue_rows.append(
            {
                "file": uf.name,
                "size_mb": round(len(uf.getbuffer()) / (1024 * 1024), 2),
                "status": "Queued",
                "output": "In final ZIP",
            }
        )
    st.dataframe(queue_rows, use_container_width=True, hide_index=True)

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

            status_rows[idx - 1]["status"] = "Done"
            table.dataframe(status_rows, use_container_width=True, hide_index=True)

            file_bar.progress(100)
            overall_bar.progress(int(idx / total * 100))

        status.markdown("**Done.**")
        zip_bytes = _zip_dir(out_dir)

        st.session_state.last_zip_bytes = zip_bytes
        st.session_state.last_transcripts = transcripts

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
          <div class="micro">TRANSCRIPT VIEW</div>
          <div class="sub">Search and skim. Download the ZIP from the Transcribe tab.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    transcripts: dict[str, str] = st.session_state.get("last_transcripts") or {}
    if not transcripts:
        st.info("No transcript yet. Run a transcription first.")
        st.stop()

    files = sorted(transcripts.keys())
    selected = st.selectbox("File", files, index=0)
    query = st.text_input("Search", value="", placeholder="Type to filter...")

    text = transcripts.get(selected, "")
    if query.strip():
        q = query.strip().lower()
        filtered = "\n".join([ln for ln in text.splitlines() if q in ln.lower()])
        st.text_area("Transcript (filtered)", value=filtered, height=420)
    else:
        st.text_area("Transcript", value=text, height=420)

st.markdown(
    '<div class="footer"><span class="dot" title="I listened all the way through.">•</span></div>',
    unsafe_allow_html=True,
)
