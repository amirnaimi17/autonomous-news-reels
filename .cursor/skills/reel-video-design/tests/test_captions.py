#!/usr/bin/env python3
"""Caption grouping stays on phrases and sentence ends."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from render_reel import group_words  # noqa: E402


class CaptionTests(unittest.TestCase):
    def test_sentence_end_starts_a_new_caption(self) -> None:
        words = [
            {"text": "تا", "start": 0.0, "end": 0.2},
            {"text": "نوزدهم.", "start": 0.2, "end": 0.5},
            {"text": "نتیجه", "start": 0.6, "end": 0.9},
        ]
        groups = group_words(words)
        self.assertEqual(groups[0]["text"], "تا نوزدهم.")
        self.assertEqual(groups[1]["text"], "نتیجه")

    def test_groups_are_words_not_characters(self) -> None:
        words = [{"text": "آلاسکا", "start": 0.0, "end": 0.4}]
        self.assertEqual(group_words(words)[0]["text"], "آلاسکا")


if __name__ == "__main__":
    unittest.main()
