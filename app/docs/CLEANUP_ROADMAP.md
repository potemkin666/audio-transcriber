# Cleanup Roadmap

The project is now easier to approach, but these follow-up changes would make it feel more like a finished user app.

## Highest Value

1. Turn the release ZIP into a real installer with Start Menu shortcuts and uninstall support.
2. Move advanced CLI files into a proper module entry point, then expose commands like `python -m transcriber.cli`.
3. Add an in-app Help/About page with the setup status, FFmpeg status, model cache location, and where outputs are saved.
4. Move runtime logs and temporary outputs to a dedicated app data folder instead of the project folder.

## Nice Polish

1. Consolidate optional dependency notes so speaker labels and hot-folder watch are explained in one place.
2. Add a small troubleshooting page for first-run model downloads, FFmpeg errors, and missing Python.
3. Add a release checklist covering setup, launch, LAN launch, speaker setup, and hot-folder behavior.
4. Add screenshots to `README.md` once the UI is stable.

## Lower Priority

1. Convert the project to a `src/` package layout if it will be published as a Python package.
2. Add automated tests for transcript formatting, output file generation, and hot-folder state handling.
3. Add a lightweight sample-audio smoke test that can run without downloading a large Whisper model.
