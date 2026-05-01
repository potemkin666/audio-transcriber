## What changed?

## How to test

- [ ] `cd app && python -m compileall -q streamlit_app.py transcribe_cli.py transcriber`
- [ ] `cd app && bash -n setup_unix.sh`
- [ ] `cd app && python - <<'PY'`
  `from transcriber.formats import Segment, segments_to_srt, segments_to_vtt`
  `segments = [Segment(0.0, 1.25, "Hello", "Speaker 1"), Segment(61.5, 62.0, "Bye")]`
  `assert "WEBVTT" in segments_to_vtt(segments)`
  `assert "00:00:00,000 --> 00:00:01,250" in segments_to_srt(segments)`
  `PY`
