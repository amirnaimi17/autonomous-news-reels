#!/usr/bin/env python3
"""Eleven v4 request shape. No network."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from elevenlabs import (  # noqa: E402
    PaidCallRefused,
    account_voices_request,
    list_voices,
    shared_voices_request,
    speak_with_receipt,
    speech_request,
    synthesize,
)

SPOKEN = "هفدهم نوامبر، آزمون صدا."


class ElevenLabsTests(unittest.TestCase):
    def test_request_uses_v4_and_keeps_the_key_out(self) -> None:
        os.environ["ELEVENLABS_API_KEY"] = "should-not-appear"
        try:
            spec = speech_request(SPOKEN, "voice123")
        finally:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        self.assertEqual(spec["body"]["model_id"], "eleven_v4")
        self.assertEqual(spec["body"]["language_code"], "fa")
        self.assertEqual(spec["body"]["apply_text_normalization"], "off")
        self.assertEqual(spec["body"]["voice_settings"]["speed"], 1.0)
        self.assertEqual(spec["query"]["output_format"], "mp3_44100_128")
        self.assertNotIn("should-not-appear", json.dumps(spec))
        self.assertTrue(spec["url"].endswith("/v1/text-to-speech/voice123"))

    def test_listing_requests_can_filter_persian_narration(self) -> None:
        shared = shared_voices_request()
        account = account_voices_request()
        self.assertEqual(shared["url"], "https://api.elevenlabs.io/v1/shared-voices")
        self.assertEqual(shared["query"]["language"], "fa")
        self.assertEqual(shared["query"]["search"], "narration")
        self.assertEqual(account["url"], "https://api.elevenlabs.io/v2/voices")
        self.assertEqual(account["query"]["language"], "fa")

    def test_listing_and_speech_do_not_call_without_approval(self) -> None:
        def transport(spec, key):
            raise AssertionError("network was called")

        with self.assertRaises(PaidCallRefused):
            list_voices(shared_voices_request(), approve_list=False, transport=transport)
        with self.assertRaises(PaidCallRefused):
            synthesize(SPOKEN, "voice123", approved=False, transport=transport)

    def test_an_unpriced_image_does_not_block_priced_speech(self) -> None:
        os.environ["ELEVENLABS_API_KEY"] = "unit-test-key"

        def transport(spec, key):
            return b"ID3sample"

        try:
            audio = synthesize(
                SPOKEN,
                "voice123",
                approved=True,
                voice_rate_confirmed=True,
                ledger_path=Path("/tmp/missing-api-quality-ledger.jsonl"),
                transport=transport,
            )
        finally:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        self.assertEqual(audio, b"ID3sample")

    def test_a_priced_experiment_can_send_without_logging_the_key(self) -> None:
        os.environ["ELEVENLABS_API_KEY"] = "unit-test-key"
        seen = {}

        def transport(spec, key):
            seen["key"] = key
            seen["spec"] = spec
            if key in json.dumps(spec):
                raise AssertionError("key leaked into the request body")
            return b"ID3sample"

        try:
            audio = synthesize(
                SPOKEN,
                "voice123",
                approved=True,
                voice_rate_confirmed=True,
                ledger_path=Path("/tmp/missing-api-quality-ledger.jsonl"),
                transport=transport,
            )
        finally:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        self.assertEqual(audio, b"ID3sample")
        self.assertEqual(seen["key"], "unit-test-key")
        self.assertEqual(seen["spec"]["body"]["model_id"], "eleven_v4")

    def test_the_experiment_cap_is_checked_before_the_request(self) -> None:
        os.environ["ELEVENLABS_API_KEY"] = "unit-test-key"

        def transport(spec, key):
            raise AssertionError("network was called")

        try:
            with self.assertRaises(PaidCallRefused):
                speak_with_receipt(
                    "ا" * 200,
                    "voice123",
                    approved=True,
                    voice_rate_confirmed=True,
                    spent_usd=0.05,
                    max_usd=0.06,
                    ledger_path=Path("/tmp/missing-api-quality-ledger.jsonl"),
                    transport=transport,
                )
        finally:
            os.environ.pop("ELEVENLABS_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
