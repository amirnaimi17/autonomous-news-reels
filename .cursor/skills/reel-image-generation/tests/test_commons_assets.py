#!/usr/bin/env python3
"""License gate for Commons files. No network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from commons_assets import reuse_decision  # noqa: E402


class CommonsLicenseTests(unittest.TestCase):
    def test_by_and_by_sa_and_cc0_are_reusable(self) -> None:
        for name in ("CC BY 4.0", "CC BY-SA 4.0", "CC BY-SA 3.0", "CC0", "Public domain"):
            self.assertTrue(reuse_decision(name)["accepted"], name)

    def test_noncommercial_and_no_derivatives_are_rejected(self) -> None:
        for name in ("CC BY-NC 4.0", "CC BY-NC-SA 4.0", "CC BY-ND 4.0", "CC BY-NC-ND 4.0"):
            self.assertFalse(reuse_decision(name)["accepted"], name)

    def test_an_extra_restriction_rejects_an_otherwise_open_license(self) -> None:
        decision = reuse_decision("CC BY-SA 4.0", "private use only")
        self.assertFalse(decision["accepted"])

    def test_a_missing_license_is_rejected(self) -> None:
        self.assertFalse(reuse_decision(None)["accepted"])
        self.assertFalse(reuse_decision("All rights reserved")["accepted"])


if __name__ == "__main__":
    unittest.main()
