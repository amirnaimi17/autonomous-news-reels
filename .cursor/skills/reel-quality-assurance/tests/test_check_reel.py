#!/usr/bin/env python3
"""Pure checks for the Reel QA script. No media files required."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_reel import technical_checks  # noqa: E402


GOOD = {
    "format": {"duration": "40.0"},
    "streams": [
        {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920, "avg_frame_rate": "30/1"},
        {"codec_type": "audio", "codec_name": "aac"},
    ],
}


class QaTests(unittest.TestCase):
    def test_good_probe_passes(self) -> None:
        checks = technical_checks(GOOD, {"max_volume_db": -4.0, "mean_volume_db": -20.0}, [], min_seconds=38, max_seconds=42)
        self.assertTrue(all(item["ok"] for item in checks))
        self.assertTrue(all(item["kind"] == "technical" for item in checks))

    def test_clipping_and_wrong_size_fail(self) -> None:
        info = json_copy()
        checks = technical_checks(info, {"max_volume_db": 0.0, "mean_volume_db": -20.0}, ["black_start:0"], min_seconds=38, max_seconds=42)
        names = {item["name"]: item["ok"] for item in checks}
        self.assertFalse(names["resolution"])
        self.assertFalse(names["not_clipping"])
        self.assertFalse(names["no_long_black"])


def json_copy() -> dict:
    return {
        "format": {"duration": "50.0"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280, "avg_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }


if __name__ == "__main__":
    unittest.main()
