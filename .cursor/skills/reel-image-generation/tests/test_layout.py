#!/usr/bin/env python3
"""Layout defaults. No image calls."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from layout import choose_treatment  # noqa: E402


class LayoutTests(unittest.TestCase):
    def test_a_results_story_does_not_buy_four_images(self) -> None:
        choice = choose_treatment("رأی اول حدود 50.1 درصد در برابر 45.8 درصد. 56 کرسی.")
        self.assertEqual(choice["generated_images"], 0)
        self.assertGreaterEqual(choice["charts"], 1)
        self.assertFalse(choice["present_ai_as_photograph"])

    def test_a_hero_is_one_image_when_explicitly_allowed(self) -> None:
        choice = choose_treatment("یک خبر بدون رقم.", allow_one_hero=True)
        self.assertEqual(choice["generated_images"], 1)


if __name__ == "__main__":
    unittest.main()
