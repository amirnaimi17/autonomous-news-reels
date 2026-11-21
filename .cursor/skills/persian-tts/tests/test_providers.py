#!/usr/bin/env python3
"""Voice selection. No network and no speech synthesis."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from providers import select_voice  # noqa: E402


class VoiceSelectionTests(unittest.TestCase):
    def test_aran_is_the_default_when_the_key_is_set(self) -> None:
        os.environ["ELEVENLABS_API_KEY"] = "present"
        try:
            choice = select_voice()
        finally:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        self.assertEqual(choice["selected"], "elevenlabs")
        self.assertEqual(choice["voice_id"], "PEdcOLzbXYhL8IKOswXB")
        self.assertEqual(choice["model"], "eleven_v4")
        self.assertEqual(choice["language_code"], "fa")
        self.assertEqual(choice["speed"], 1.0)
        self.assertEqual(choice["fallback"]["model"], "fa-IR-FaridNeural")
        names = {item["name"] for item in choice["options"]}
        self.assertEqual(names, {"Aran", "Arash", "Connery", "Farid", "Dilara"})
        self.assertNotIn("present", str(choice))

    def test_edge_farid_is_the_fallback_without_a_key(self) -> None:
        os.environ.pop("ELEVENLABS_API_KEY", None)
        choice = select_voice()
        self.assertEqual(choice["selected"], "edge-tts")
        self.assertEqual(choice["model"], "fa-IR-FaridNeural")
        self.assertEqual(choice["production"]["voice_id"], "PEdcOLzbXYhL8IKOswXB")


if __name__ == "__main__":
    unittest.main()
