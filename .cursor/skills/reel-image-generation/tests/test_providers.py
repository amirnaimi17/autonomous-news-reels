#!/usr/bin/env python3
"""Hardware gates for image providers. No GPU and no network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from providers import fitting_local_models, load_hardware, select_provider  # noqa: E402


class ProviderTests(unittest.TestCase):
    def test_measured_card_rejects_sdxl_and_flux(self) -> None:
        hardware = load_hardware()
        self.assertEqual(hardware["vram_mib"], 4096)
        self.assertEqual(fitting_local_models(hardware["vram_mib"]), [])
        decision = select_provider(hardware, comfy_up=False)
        self.assertEqual(decision["selected"], "cursor-generate-image")
        self.assertFalse(decision["replace_cursor"])
        self.assertIn("sdxl", decision["rejected"])
        self.assertIn("flux-dev", decision["rejected"])

    def test_comfy_without_a_fitting_model_does_not_replace_cursor(self) -> None:
        decision = select_provider({"vram_mib": 4096}, comfy_up=True)
        self.assertEqual(decision["selected"], "cursor-generate-image")
        self.assertFalse(decision["replace_cursor"])


if __name__ == "__main__":
    unittest.main()
