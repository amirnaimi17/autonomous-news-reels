#!/usr/bin/env python3
"""Sentence rhythm and pronunciation overrides. No network and no espeak."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preprocess import (  # noqa: E402
    load_dictionary,
    prepare_narration,
    segment_sentences,
    uncovered_tokens,
)

ROOT = Path(__file__).resolve().parents[1]
DICTIONARY = load_dictionary(ROOT / "config" / "pronunciation.json")
DISPLAY = (
    "انتخابات 3 نوامبر برگزار شد. "
    "17 نوامبر، Associated Press مری پلتولا را برنده سنای Alaska اعلام کرد. "
    "رقیب او دن سالیوان بود."
)


class NarrationPreparationTests(unittest.TestCase):
    def test_short_sentences_keep_every_word(self) -> None:
        spoken = prepare_narration(DISPLAY, DICTIONARY)
        sentences = segment_sentences(spoken)
        self.assertEqual(len(sentences), 3)
        self.assertIn("سوم نوامبر", spoken)
        self.assertIn("هفدهم نوامبر", spoken)
        self.assertIn("مِری", spoken)
        self.assertIn("دَن سالیوِن", spoken)
        self.assertIn("آسوشیِیتِد پرس", spoken)
        self.assertTrue(DISPLAY.startswith("انتخابات"))

    def test_a_colon_becomes_a_spoken_pause(self) -> None:
        spoken = prepare_narration("بی‌بی‌سی: 56 کرسی", DICTIONARY)
        self.assertTrue(spoken.endswith("."))
        self.assertNotIn(":", spoken)
        self.assertIn("پنجاه و شش", spoken)
        self.assertIn("بی بی سی", spoken)

    def test_split_name_still_counts_as_covered(self) -> None:
        spoken = prepare_narration("Mary Peltola", DICTIONARY)
        self.assertEqual(uncovered_tokens(spoken, ["مری", "پل", "تولا"]), [])

    def test_a_dropped_word_is_reported(self) -> None:
        spoken = prepare_narration("Dan Sullivan", DICTIONARY)
        self.assertEqual(uncovered_tokens(spoken, ["دن"]), ["سالیون"])


if __name__ == "__main__":
    unittest.main()
