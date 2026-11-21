#!/usr/bin/env python3
"""Regression checks for spoken Persian. No network and no espeak."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preprocess import load_dictionary, to_spoken  # noqa: E402
from test_cases import CASES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DICTIONARY = load_dictionary(ROOT / "config" / "pronunciation.json")


class PreprocessTests(unittest.TestCase):
    def test_challenging_sentences(self) -> None:
        self.assertGreaterEqual(len(CASES), 10)
        for raw, expected in CASES:
            with self.subTest(raw=raw):
                self.assertEqual(to_spoken(raw, DICTIONARY), expected)

    def test_display_string_is_not_the_spoken_string(self) -> None:
        display = "۱۷ نوامبر: ۵۰.۱٪"
        spoken = to_spoken(display, DICTIONARY)
        self.assertNotEqual(display, spoken)
        self.assertIn("هفدهم", spoken)
        self.assertIn("درصد", spoken)


if __name__ == "__main__":
    unittest.main()
