from __future__ import annotations

import runpy
import sys
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]


class _StopApp(RuntimeError):
    pass


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def button(self, *args, **kwargs):
        return False

    def checkbox(self, *args, value=False, **kwargs):
        return value

    def slider(self, *args, value=None, min_value=None, **kwargs):
        return value if value is not None else min_value

    def multiselect(self, *args, options=None, default=None, **kwargs):
        return default if default is not None else (options or [])

    def selectbox(self, *args, options=None, index=0, **kwargs):
        if not options:
            return None
        return options[index]

    def text_input(self, *args, value="", **kwargs):
        return value

    def write(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None

    def markdown(self, *args, **kwargs):
        return None

    def text_area(self, *args, **kwargs):
        return None

    def dataframe(self, *args, **kwargs):
        return None

    def progress(self, *args, **kwargs):
        return self

    def empty(self):
        return self

    def image(self, *args, **kwargs):
        return None


def _fake_streamlit_module() -> types.ModuleType:
    module = types.ModuleType("streamlit")
    module.session_state = _SessionState()
    module.query_params = {}
    module.sidebar = _DummyContext()
    module.set_page_config = lambda *a, **k: None
    module.markdown = lambda *a, **k: None
    module.caption = lambda *a, **k: None
    module.write = lambda *a, **k: None
    module.header = lambda *a, **k: None
    module.info = lambda *a, **k: None
    module.error = lambda *a, **k: None
    module.success = lambda *a, **k: None
    module.warning = lambda *a, **k: None
    module.audio = lambda *a, **k: None
    module.image = lambda *a, **k: None
    module.text_area = lambda *a, **k: None
    module.download_button = lambda *a, **k: None
    module.toast = lambda *a, **k: None
    module.rerun = lambda: None
    module.stop = lambda: (_ for _ in ()).throw(_StopApp())
    module.file_uploader = lambda *a, **k: None
    module.text_input = lambda *a, value="", **k: value
    module.checkbox = lambda *a, value=False, **k: value
    module.selectbox = lambda label, options, index=0, **k: options[index] if options else None
    module.slider = lambda *a, value=None, min_value=None, **k: value if value is not None else min_value
    module.multiselect = lambda *a, options=None, default=None, **k: default if default is not None else (options or [])
    module.button = lambda *a, **k: False
    module.progress = lambda *a, **k: _DummyContext()
    module.empty = lambda: _DummyContext()
    module.dataframe = lambda *a, **k: None
    module.columns = lambda spec: [_DummyContext() for _ in range(spec if isinstance(spec, int) else len(spec))]
    module.tabs = lambda labels: [_DummyContext() for _ in labels]
    module.expander = lambda *a, **k: _DummyContext()
    return module


def _fake_transcriber_modules() -> dict[str, types.ModuleType]:
    core = types.ModuleType("transcriber.core")

    class _Options:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    core.TranscriptionOptions = _Options
    core.prepare_whisper_model = lambda *a, **k: None
    core.transcribe_file = lambda *a, **k: None
    core.transcribe_path = lambda *a, **k: []

    ffmpeg = types.ModuleType("transcriber.ffmpeg")
    ffmpeg.ensure_ffmpeg_available = lambda: None
    ffmpeg.probe_duration_seconds = lambda *a, **k: None
    ffmpeg.ffmpeg_version_line = lambda: "ffmpeg"
    ffmpeg.ffprobe_version_line = lambda: "ffprobe"
    ffmpeg.find_ffmpeg_tools = lambda: {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}

    hotfolder = types.ModuleType("transcriber.hotfolder")

    class _Decision:
        should_process = True
        persist_state = False
        signature = types.SimpleNamespace(size=0, mtime_ns=0, sha256=None)

    hotfolder.decide_file_action = lambda *a, **k: _Decision()
    hotfolder.iter_audio_files = lambda *a, **k: []
    hotfolder.load_state = lambda *a, **k: {}
    hotfolder.rel_key = lambda *a, **k: ""
    hotfolder.save_state = lambda *a, **k: None

    telemetry = types.ModuleType("transcriber.telemetry")
    telemetry.get_rtf = lambda *a, **k: (1.0, 0)

    return {
        "transcriber.core": core,
        "transcriber.ffmpeg": ffmpeg,
        "transcriber.hotfolder": hotfolder,
        "transcriber.telemetry": telemetry,
    }


class SmokeTests(unittest.TestCase):
    def test_cli_help_exits_cleanly(self) -> None:
        fake_core = types.ModuleType("transcriber.core")

        class _Options:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        fake_core.TranscriptionOptions = _Options
        fake_core.prepare_whisper_model = lambda *a, **k: None
        fake_core.transcribe_path = lambda *a, **k: []

        fake_ffmpeg = types.ModuleType("transcriber.ffmpeg")
        fake_ffmpeg.ensure_ffmpeg_available = lambda: None

        with ExitStack() as stack:
            stack.enter_context(mock.patch.dict(sys.modules, {"transcriber.core": fake_core, "transcriber.ffmpeg": fake_ffmpeg}))
            stack.enter_context(mock.patch.object(sys, "argv", ["transcribe_cli.py", "--help"]))
            with self.assertRaises(SystemExit) as exc:
                runpy.run_path(str(APP_DIR / "transcribe_cli.py"), run_name="__main__")
        self.assertEqual(exc.exception.code, 0)

    def test_streamlit_app_smoke_starts_until_empty_state(self) -> None:
        fake_streamlit = _fake_streamlit_module()
        fake_components = types.ModuleType("streamlit.components.v1")
        fake_components.html = lambda *a, **k: None

        patches = {
            "streamlit": fake_streamlit,
            "streamlit.components": types.ModuleType("streamlit.components"),
            "streamlit.components.v1": fake_components,
            **_fake_transcriber_modules(),
        }
        patches["streamlit.components"].v1 = fake_components

        with mock.patch.dict(sys.modules, patches):
            with self.assertRaises(_StopApp):
                runpy.run_path(str(APP_DIR / "streamlit_app.py"), run_name="__main__")


if __name__ == "__main__":
    unittest.main()
