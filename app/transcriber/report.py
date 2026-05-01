from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "in",
    "into",
    "is",
    "it",
    "its",
    "me",
    "my",
    "no",
    "not",
    "of",
    "on",
    "or",
    "our",
    "she",
    "so",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "to",
    "up",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "who",
    "will",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class BriefSnippets:
    email: str
    whatsapp: str


def _hms(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s2 = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s2:02d}"


def _truncate(text: str, n: int) -> str:
    t = " ".join((text or "").split()).strip()
    if len(t) <= n:
        return t
    return t[: max(0, n - 3)].rstrip() + "..."


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9’']{2,}")


def _keywords(segments: list[dict], *, top_n: int = 12) -> list[str]:
    freq: dict[str, int] = {}
    for s in segments:
        text = (s.get("text") or "").lower()
        for m in _TOKEN_RE.finditer(text):
            w = m.group(0).strip("’'").lower()
            if w in _STOPWORDS:
                continue
            if w.isdigit():
                continue
            freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for (w, _) in ranked[:top_n]]


def _speaker_stats(segments: list[dict]) -> list[dict]:
    totals: dict[str, float] = {}
    for s in segments:
        spk = (s.get("speaker") or "Speaker").strip()
        start = float(s.get("start") or 0.0)
        end = float(s.get("end") or start)
        dur = max(0.0, end - start)
        totals[spk] = totals.get(spk, 0.0) + dur
    total = sum(totals.values()) or 1.0
    rows = []
    for spk, sec in sorted(totals.items(), key=lambda kv: -kv[1]):
        rows.append({"speaker": spk, "seconds": sec, "pct": 100.0 * (sec / total)})
    return rows


def _moment_score(seg: dict) -> float:
    text = " ".join((seg.get("text") or "").split()).strip()
    start = float(seg.get("start") or 0.0)
    end = float(seg.get("end") or start)
    dur = max(0.0, end - start)

    # Whisper confidence proxy: higher avg_logprob is better (less negative).
    w = seg.get("whisper") or {}
    avg_logprob = w.get("avg_logprob")
    try:
        alp = float(avg_logprob)
    except Exception:
        alp = None

    # Heuristics: numbers/dates/keywords are often salient.
    has_digits = 1.0 if re.search(r"\d", text) else 0.0
    has_question = 1.0 if "?" in text else 0.0
    caps = 1.0 if re.search(r"\b[A-Z][a-z]{2,}\b", seg.get("text") or "") else 0.0

    conf = 0.0
    if alp is not None:
        # Map roughly [-3..0] -> [0..1]
        conf = max(0.0, min(1.0, (alp + 3.0) / 3.0))

    # Favor: longer, confident, information-dense.
    return (0.6 * min(12.0, dur)) + (2.0 * conf) + (1.2 * has_digits) + (0.6 * has_question) + (0.6 * caps)


def _top_moments(segments: list[dict], *, top_n: int = 10) -> list[dict]:
    scored = []
    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        scored.append((float(_moment_score(s)), s))
    scored.sort(key=lambda it: it[0], reverse=True)

    picked: list[dict] = []
    used_buckets: set[int] = set()
    # Avoid ten moments from the same minute.
    for _, s in scored:
        bucket = int(float(s.get("start") or 0.0) // 60)
        if bucket in used_buckets and len(picked) < 4:
            # allow some clustering early if needed
            pass
        elif bucket in used_buckets:
            continue
        used_buckets.add(bucket)
        picked.append(s)
        if len(picked) >= top_n:
            break
    picked.sort(key=lambda x: float(x.get("start") or 0.0))
    return picked


def _highlights_note() -> str:
    return (
        "Heuristic highlights are selected automatically. The scorer favors longer, higher-confidence, "
        "information-dense moments (such as digits, questions, and named entities) while spreading picks across the timeline."
    )


def build_brief_snippets(
    *,
    input_name: str,
    duration_hms: str,
    keywords: list[str],
    moments: list[dict],
    speaker_rows: list[dict],
) -> BriefSnippets:
    # Email: subject-ish header + bullets + quotes.
    spk_line = ", ".join([f"{r['speaker']} {int(round(r['pct']))}%" for r in speaker_rows[:4]]) or "N/A"
    kw_line = ", ".join(keywords[:10]) if keywords else "N/A"

    bullets = []
    for s in moments[:6]:
        ts = _hms(float(s.get("start") or 0.0))
        spk = (s.get("speaker") or "").strip()
        quote = _truncate(str(s.get("text") or ""), 160)
        bullets.append(f"- {ts} {spk}: {quote}".rstrip())

    email = "\n".join(
        [
            f"TRANSCRIBER Brief — {input_name}",
            f"Duration: {duration_hms}",
            f"Speakers: {spk_line}",
            f"Keywords: {kw_line}",
            "",
            "Heuristic highlights (timestamped):",
            *bullets,
        ]
    ).strip() + "\n"

    # WhatsApp: compact, copy/paste friendly.
    wa_lines = [
        f"TRANSCRIBER — {input_name}",
        f"Dur {duration_hms} | {spk_line}",
    ]
    if keywords:
        wa_lines.append(f"KW: {', '.join(keywords[:6])}")
    for s in moments[:4]:
        ts = _hms(float(s.get("start") or 0.0))
        spk = (s.get("speaker") or "").strip()
        quote = _truncate(str(s.get("text") or ""), 110)
        wa_lines.append(f"{ts} {spk}: {quote}".rstrip())
    whatsapp = "\n".join(wa_lines).strip() + "\n"

    return BriefSnippets(email=email, whatsapp=whatsapp)


def write_brief_pack(
    *,
    out_dir: Path,
    input_name: str,
    segments: list[dict],
    extras: dict | None = None,
) -> BriefSnippets:
    out_dir.mkdir(parents=True, exist_ok=True)
    extras = extras or {}

    duration = 0.0
    for s in segments:
        try:
            duration = max(duration, float(s.get("end") or 0.0))
        except Exception:
            continue
    duration_hms = _hms(duration)

    speaker_rows = _speaker_stats(segments)
    keywords = _keywords(segments)
    moments = _top_moments(segments)
    snippets = build_brief_snippets(
        input_name=input_name,
        duration_hms=duration_hms,
        keywords=keywords,
        moments=moments,
        speaker_rows=speaker_rows,
    )

    now = time.strftime("%Y-%m-%d %H:%M:%S")

    md_lines: list[str] = []
    md_lines.append(f"# Brief Pack — {input_name}")
    md_lines.append("")
    md_lines.append(f"- Generated: {now}")
    md_lines.append(f"- Duration: {duration_hms}")
    if speaker_rows:
        md_lines.append(f"- Speakers: {len(speaker_rows)}")
    md_lines.append("")

    warnings = (extras.get("preflight") or {}).get("warnings") if isinstance(extras.get("preflight"), dict) else None
    if warnings:
        md_lines.append("## Preflight")
        for w in warnings[:6]:
            md_lines.append(f"- {w}")
        md_lines.append("")

    md_lines.append("## Heuristic highlights")
    md_lines.append(_highlights_note())
    md_lines.append("")
    for s in moments[:10]:
        ts = _hms(float(s.get("start") or 0.0))
        spk = (s.get("speaker") or "").strip()
        md_lines.append(f"- **{ts} {spk}** — {_truncate(str(s.get('text') or ''), 220)}")
    md_lines.append("")

    md_lines.append("## Speaker talk-time")
    if speaker_rows:
        md_lines.append("| Speaker | Talk time | % |")
        md_lines.append("|---|---:|---:|")
        for r in speaker_rows:
            md_lines.append(f"| {r['speaker']} | {_hms(float(r['seconds']))} | {r['pct']:.0f}% |")
    else:
        md_lines.append("- N/A")
    md_lines.append("")

    md_lines.append("## Notable keywords")
    md_lines.append(", ".join(keywords) if keywords else "N/A")
    md_lines.append("")

    md_lines.append("## Timeline (key excerpts)")
    for s in moments[:15]:
        ts = _hms(float(s.get("start") or 0.0))
        spk = (s.get("speaker") or "").strip()
        md_lines.append(f"- {ts} {spk}: {_truncate(str(s.get('text') or ''), 260)}".rstrip())
    md_lines.append("")

    md_lines.append("## Email-ready")
    md_lines.append("```")
    md_lines.append(snippets.email.strip())
    md_lines.append("```")
    md_lines.append("")

    md_lines.append("## WhatsApp-ready")
    md_lines.append("```")
    md_lines.append(snippets.whatsapp.strip())
    md_lines.append("```")
    md_lines.append("")

    brief_md = "\n".join(md_lines).strip() + "\n"
    (out_dir / "brief.md").write_text(brief_md, encoding="utf-8")

    # Simple 1-page HTML with the same content.
    def esc(s: str) -> str:
        return html.escape(s, quote=True)

    moments_html = "\n".join(
        [
            f"<li><b>{esc(_hms(float(s.get('start') or 0.0)))} {esc((s.get('speaker') or '').strip())}</b>"
            f"<div class='q'>{esc(_truncate(str(s.get('text') or ''), 260))}</div></li>"
            for s in moments[:10]
        ]
    )
    speakers_html = "\n".join(
        [
            f"<tr><td>{esc(r['speaker'])}</td><td class='r'>{esc(_hms(float(r['seconds'])))}</td><td class='r'>{r['pct']:.0f}%</td></tr>"
            for r in speaker_rows
        ]
    )
    kw_html = esc(", ".join(keywords) if keywords else "N/A")
    preflight_html = ""
    if warnings:
        preflight_html = "<ul>" + "".join([f"<li>{esc(str(w))}</li>" for w in warnings[:6]]) + "</ul>"

    brief_html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Brief Pack — {esc(input_name)}</title>
  <style>
    :root {{
      --bg0:#071C34; --bg1:#0F3D6B; --ink:#ECF3FF; --muted:#B9D4FF; --blue:#4BB4FF; --cyan:#A7F0FF;
      --glass: rgba(255,255,255,0.08); --line: rgba(167,240,255,0.22);
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }}
    body {{
      margin: 0; color: var(--ink);
      background:
        radial-gradient(1200px 760px at 70% 10%, rgba(75,180,255,0.32), transparent 58%),
        radial-gradient(980px 600px at 25% 45%, rgba(167,240,255,0.20), transparent 62%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
    }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 24px 18px 44px; }}
    .card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.04));
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px 16px;
      box-shadow: 0 22px 54px rgba(0,0,0,0.35), 0 0 46px rgba(167,240,255,0.10);
      backdrop-filter: blur(10px);
      margin: 14px 0;
    }}
    h1 {{ letter-spacing: .06em; text-transform: uppercase; font-size: 20px; margin: 0 0 8px; }}
    h2 {{ letter-spacing: .06em; text-transform: uppercase; font-size: 14px; margin: 0 0 10px; color: var(--muted); }}
    .meta {{ color: rgba(236,243,255,0.82); font-size: 13px; }}
    ul {{ margin: 10px 0 0 18px; }}
    li {{ margin: 8px 0; }}
    .q {{ color: rgba(236,243,255,0.88); margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    td, th {{ padding: 8px 10px; border-bottom: 1px solid rgba(167,240,255,0.14); }}
    th {{ text-align: left; color: rgba(185,212,255,0.85); font-weight: 600; }}
    .r {{ text-align: right; }}
    pre {{
      white-space: pre-wrap; word-break: break-word; margin: 0;
      background: rgba(0,0,0,0.18); border: 1px solid rgba(167,240,255,0.14);
      border-radius: 14px; padding: 12px 12px; color: rgba(236,243,255,0.92);
    }}
    .chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .chip {{
      border:1px solid rgba(167,240,255,0.18); background: rgba(255,255,255,0.05);
      border-radius: 999px; padding: 6px 10px; font-size: 12px; color: rgba(236,243,255,0.86);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>Brief Pack — {esc(input_name)}</h1>
      <div class="meta">Generated: {esc(now)} • Duration: {esc(duration_hms)} • Speakers: {len(speaker_rows) if speaker_rows else 0}</div>
    </div>

    {"<div class='card'><h2>Preflight</h2>" + preflight_html + "</div>" if preflight_html else ""}

    <div class="card">
      <h2>Heuristic highlights</h2>
      <div class="meta">{esc(_highlights_note())}</div>
      <ul>{moments_html}</ul>
    </div>

    <div class="card">
      <h2>Speaker talk-time</h2>
      <table>
        <thead><tr><th>Speaker</th><th class="r">Talk time</th><th class="r">%</th></tr></thead>
        <tbody>{speakers_html or "<tr><td colspan='3'>N/A</td></tr>"}</tbody>
      </table>
    </div>

    <div class="card">
      <h2>Notable keywords</h2>
      <div class="chips">
        {"".join([f"<span class='chip'>{esc(k)}</span>" for k in (keywords or ["N/A"])])}
      </div>
    </div>

    <div class="card">
      <h2>Email-ready</h2>
      <pre>{esc(snippets.email)}</pre>
    </div>

    <div class="card">
      <h2>WhatsApp-ready</h2>
      <pre>{esc(snippets.whatsapp)}</pre>
    </div>
  </div>
</body>
</html>
"""
    (out_dir / "brief.html").write_text(brief_html, encoding="utf-8")

    (out_dir / "brief_snippets.json").write_text(
        json.dumps({"email": snippets.email, "whatsapp": snippets.whatsapp}, indent=2),
        encoding="utf-8",
    )

    return snippets
