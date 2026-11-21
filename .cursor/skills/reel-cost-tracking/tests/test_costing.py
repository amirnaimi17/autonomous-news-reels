#!/usr/bin/env python3
"""Budget gate tests. No network and no provider calls."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from costing import (  # noqa: E402
    authorize_image_test,
    authorize_voice_test,
    estimate_plan,
    gate,
    load_budget,
    load_pricing,
    month_spend,
    project_month,
    record,
)

PRICING = load_pricing()
BUDGET = load_budget()


def plan_for(requests: list[dict]) -> dict:
    return {"reel_id": "test-reel", "requests": requests}


class CostTests(unittest.TestCase):
    def test_four_unpriced_cursor_images_are_rejected(self) -> None:
        estimate = estimate_plan(
            plan_for([{"provider": "cursor-generate-image", "model": "not-returned", "images": 4}]),
            PRICING,
            BUDGET,
        )
        decision = gate(estimate, BUDGET, spent_usd=0)
        self.assertFalse(decision["allowed"])
        self.assertGreater(estimate["estimated_usd"], -1)

    def test_one_priced_image_stays_under_the_reel_cap(self) -> None:
        estimate = estimate_plan(
            plan_for(
                [
                    {"provider": "edge-tts", "model": "fa-IR-FaridNeural", "characters": 800},
                    {"provider": "google", "model": "gemini-nano-banana-2.1", "images": 1},
                    {"provider": "ffmpeg", "model": "local", "renders": 1},
                ]
            ),
            PRICING,
            BUDGET,
        )
        decision = gate(estimate, BUDGET, spent_usd=0)
        self.assertTrue(decision["allowed"])
        self.assertLess(estimate["estimated_usd"], 0.50)
        self.assertFalse(decision["budget_guaranteed"])

    def test_four_pro_images_exceed_the_reel_cap(self) -> None:
        estimate = estimate_plan(
            plan_for([{"provider": "google", "model": "gemini-3-pro-image", "images": 4}]),
            PRICING,
            BUDGET,
        )
        decision = gate(estimate, BUDGET, spent_usd=0)
        self.assertFalse(decision["allowed"])
        self.assertGreater(estimate["estimated_usd"], 0.50)

    def test_openai_mini_tts_is_not_priced_from_characters_alone(self) -> None:
        estimate = estimate_plan(
            plan_for([{"provider": "openai", "model": "gpt-4o-mini-tts", "characters": 800}]),
            PRICING,
            BUDGET,
        )
        self.assertEqual(estimate["lines"][0]["status"], "incomplete")
        self.assertFalse(gate(estimate, BUDGET, spent_usd=0)["allowed"])

    def test_multilingual_v2_is_not_a_persian_model(self) -> None:
        estimate = estimate_plan(
            plan_for([{"provider": "elevenlabs", "model": "eleven_multilingual_v2", "characters": 800}]),
            PRICING,
            BUDGET,
        )
        self.assertEqual(estimate["lines"][0]["status"], "unsupported_language")

    def test_company_remotion_minimum_exceeds_the_monthly_target(self) -> None:
        estimate = estimate_plan(
            plan_for([{"provider": "remotion", "model": "automators", "renders": 1, "license": "company_automator"}]),
            PRICING,
            BUDGET,
        )
        decision = gate(estimate, BUDGET, spent_usd=0)
        self.assertFalse(decision["allowed"])
        self.assertIn(100, [line.get("monthly_minimum_usd") for line in estimate["lines"]])

    def test_retries_and_cache(self) -> None:
        doubled = estimate_plan(
            plan_for([{"provider": "elevenlabs", "model": "eleven_v4", "characters": 1000, "attempts": 2}]),
            PRICING,
            BUDGET,
        )
        once = estimate_plan(
            plan_for([{"provider": "elevenlabs", "model": "eleven_v4", "characters": 1000, "attempts": 1}]),
            PRICING,
            BUDGET,
        )
        cached = estimate_plan(
            plan_for([{"provider": "elevenlabs", "model": "eleven_v4", "characters": 1000, "cache_hit": True}]),
            PRICING,
            BUDGET,
        )
        self.assertAlmostEqual(doubled["estimated_usd"], once["estimated_usd"] * 2)
        self.assertEqual(cached["estimated_usd"], 0)
        unbounded = estimate_plan(
            plan_for([{"provider": "elevenlabs", "model": "eleven_v4", "characters": 10, "attempts": 9}]),
            PRICING,
            BUDGET,
        )
        self.assertFalse(gate(unbounded, BUDGET, spent_usd=0)["allowed"])

    def test_month_ledger_blocks_the_next_reel(self) -> None:
        ledger = Path(self.id().replace(".", "-") + ".jsonl")
        try:
            record(ledger, {"recorded_at": "2026-11-02T00:00:00Z", "reel_id": "old", "usd": 59.98, "cost_kind": "actual"})
            estimate = estimate_plan(
                plan_for([{"provider": "google", "model": "gemini-nano-banana-2.1", "images": 1}]),
                PRICING,
                BUDGET,
            )
            spent, _uncertain = month_spend(ledger, "2026-11")
            self.assertFalse(gate(estimate, BUDGET, spent_usd=spent)["allowed"])
        finally:
            ledger.unlink(missing_ok=True)

    def test_a_priced_voice_test_does_not_wait_for_the_image_price(self) -> None:
        voice = authorize_voice_test(characters=216, voice_rate_confirmed=True)
        image = authorize_image_test()
        self.assertTrue(voice["decision"]["allowed"])
        self.assertAlmostEqual(voice["estimate"]["estimated_usd"], 0.01728)
        self.assertEqual(voice["decision"]["per_reel_max_usd"], 0.5)
        self.assertFalse(image["decision"]["allowed"])
        self.assertEqual(image["estimate"]["lines"][0]["status"], "incomplete")

    def test_the_sunburst_calculator_cell_is_an_estimate_without_a_ceiling(self) -> None:
        decision = authorize_image_test(text_input_tokens=120, image_input_tokens=0)
        image = decision["estimate"]["lines"][0]
        self.assertEqual(image["price_basis"], "official_calculator")
        self.assertEqual(image["image_output_tokens"], 1372)
        self.assertAlmostEqual(image["usd"], 0.04176)
        self.assertFalse(image["ceiling"])
        self.assertFalse(decision["decision"]["budget_guaranteed"])
        self.assertTrue(decision["decision"]["allowed"])
        self.assertLess(decision["estimate"]["estimated_usd"], 0.50)

    def test_sunburst_token_rate_is_applied_only_to_measured_tokens(self) -> None:
        decision = authorize_image_test(image_output_tokens=1000, text_input_tokens=200, image_input_tokens=0)
        image = decision["estimate"]["lines"][0]
        self.assertEqual(image["status"], "estimated")
        self.assertAlmostEqual(image["usd"], 0.031)
        self.assertTrue(decision["decision"]["allowed"])
        self.assertLess(decision["estimate"]["estimated_usd"], 0.50)

    def test_a_custom_elevenlabs_rate_is_not_replaced_with_the_catalog_rate(self) -> None:
        decision = authorize_voice_test(characters=216, voice_rate_confirmed=True, voice_fiat_rate_per_1000=0.2)
        self.assertEqual(decision["estimate"]["lines"][0]["status"], "unknown")
        self.assertFalse(decision["decision"]["allowed"])

    def test_projection_is_arithmetic_not_a_bill(self) -> None:
        self.assertEqual(project_month(0.25, 120)["month_usd"], 30)
        catalog = json.loads(Path(__file__).resolve().parents[1].joinpath("config/pricing.json").read_text())
        self.assertEqual(catalog["currency"], "USD")
        self.assertTrue(catalog["entries"][0]["source"])


if __name__ == "__main__":
    unittest.main()
