#!/usr/bin/env python3
"""The production script refuses to speed up a long narration."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

SPEAK = Path(__file__).resolve().parents[1] / "scripts" / "speak.py"


class RatePolicyTests(unittest.TestCase):
    def test_nonzero_rate_is_refused_before_synthesis(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SPEAK),
                "--story",
                "missing-story.json",
                "--out-dir",
                "/tmp/persian-tts-rate-test",
                "--rate",
                "+19%",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing a non-zero rate", result.stderr)
        self.assertNotIn("espeak", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
