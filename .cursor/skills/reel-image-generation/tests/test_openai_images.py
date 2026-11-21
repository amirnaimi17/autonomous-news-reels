#!/usr/bin/env python3
"""OpenAI image request shape. No network."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from openai_images import (  # noqa: E402
    ALASKA_TEST_PROMPT,
    IMAGE_PROMPT,
    PaidCallRefused,
    generate,
    image_request,
    probe_model,
    tokens_from_usage,
)


class OpenAIImageTests(unittest.TestCase):
    def test_request_matches_the_documented_portrait_settings(self) -> None:
        os.environ["OPENAI_API_KEY"] = "should-not-appear"
        try:
            spec = image_request()
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
        body = spec["body"]
        self.assertEqual(spec["url"], "https://api.openai.com/v1/images/generations")
        self.assertEqual(body["model"], "gpt-image-2.5-sunburst")
        self.assertEqual(body["size"], "1024x1536")
        self.assertEqual(body["quality"], "high")
        self.assertEqual(body["output_format"], "png")
        self.assertEqual(body["n"], 1)
        self.assertNotIn("response_format", body)
        self.assertNotIn("partial_images", body)
        self.assertNotIn("should-not-appear", json.dumps(spec))
        self.assertNotRegex(IMAGE_PROMPT, r"\d")

    def test_the_alaska_probe_reads_the_model_and_does_not_generate(self) -> None:
        seen = {}

        def transport(spec, key):
            seen["method"] = spec["method"]
            seen["url"] = spec["url"]
            self.assertNotIn(key, spec["url"])
            return b'{"id":"gpt-image-2.5-sunburst","owned_by":"system"}'

        os.environ["OPENAI_API_KEY"] = "unit-test-key"
        try:
            result = probe_model(transport=transport)
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
        self.assertEqual(seen["method"], "GET")
        self.assertTrue(seen["url"].endswith("/models/gpt-image-2.5-sunburst"))
        self.assertTrue(result["available"])
        request = image_request(ALASKA_TEST_PROMPT)
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["body"]["n"], 1)
        self.assertNotRegex(ALASKA_TEST_PROMPT, r"\d")

    def test_missing_usage_tokens_are_not_invented(self) -> None:
        with self.assertRaises(PaidCallRefused):
            tokens_from_usage({"output_tokens": 10})

    def test_unknown_price_blocks_the_image_call(self) -> None:
        calls = []

        def transport(spec, key):
            calls.append(spec)
            return b"{}"

        with self.assertRaises(PaidCallRefused):
            generate(
                approved=True,
                ledger_path=Path("/tmp/missing-api-quality-ledger.jsonl"),
                transport=transport,
            )
        self.assertEqual(calls, [])

    def test_a_priced_experiment_can_send_without_logging_the_key(self) -> None:
        os.environ["OPENAI_API_KEY"] = "unit-test-key"
        seen = {}

        def transport(spec, key):
            seen["spec"] = spec
            self.assertNotIn(key, json.dumps(spec))
            usage = {
                "output_tokens": 1000,
                "input_tokens_details": {"text_tokens": 50, "image_tokens": 0},
            }
            return json.dumps({"data": [{"b64_json": "aaaa"}], "usage": usage}).encode()

        try:
            result = generate(
                approved=True,
                image_output_tokens=1000,
                text_input_tokens=50,
                image_input_tokens=0,
                ledger_path=Path("/tmp/missing-api-quality-ledger.jsonl"),
                transport=transport,
            )
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
        self.assertEqual(seen["spec"]["body"]["quality"], "high")
        self.assertEqual(result["usage"]["image_output_tokens"], 1000)
        self.assertGreater(result["image_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
