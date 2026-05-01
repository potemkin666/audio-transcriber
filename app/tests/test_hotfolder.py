from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from transcriber.hotfolder import FileSignature, decide_file_action, load_state, save_state


class HotfolderTests(unittest.TestCase):
    def test_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            state = {"call.wav": FileSignature(size=12, mtime_ns=34, sha256="abc")}
            save_state(out_dir, state)
            restored = load_state(out_dir)
            self.assertEqual(restored, state)

    def test_always_hash_before_skip_detects_identical_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "clip.wav"
            file_path.write_bytes(b"same-audio")

            first = decide_file_action(file_path, None, use_hash=False, always_hash_before_skip=True)
            self.assertTrue(first.should_process)
            previous = first.signature

            file_path.touch()
            second = decide_file_action(file_path, previous, use_hash=False, always_hash_before_skip=True)
            self.assertFalse(second.should_process)
            self.assertTrue(second.persist_state)
            self.assertEqual(second.signature.sha256, previous.sha256)


if __name__ == "__main__":
    unittest.main()
