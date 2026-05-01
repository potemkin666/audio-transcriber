from __future__ import annotations

import unittest

from transcriber.formats import Segment, segments_to_srt, segments_to_txt_timestamps, segments_to_vtt


class FormatTests(unittest.TestCase):
    def test_timestamp_formats_are_stable(self) -> None:
        segments = [
            Segment(start=0.0, end=1.25, text="Hello", speaker="Speaker 1"),
            Segment(start=61.5, end=62.0, text="Bye"),
        ]

        self.assertEqual(
            segments_to_srt(segments),
            "1\n"
            "00:00:00,000 --> 00:00:01,250\n"
            "Speaker 1: Hello\n\n"
            "2\n"
            "00:01:01,500 --> 00:01:02,000\n"
            "Bye\n",
        )
        self.assertEqual(
            segments_to_vtt(segments),
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:01.250\n"
            "Speaker 1: Hello\n\n"
            "00:01:01.500 --> 00:01:02.000\n"
            "Bye\n",
        )
        self.assertEqual(
            segments_to_txt_timestamps(segments),
            "00:00:00 Speaker 1\n"
            "Hello\n"
            "00:01:01\n"
            "Bye\n",
        )


if __name__ == "__main__":
    unittest.main()
