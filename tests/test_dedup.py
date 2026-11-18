"""URL identity and headline fingerprints."""

import pytest

from app.services.dedup.fingerprints import (
    block_key,
    hamming_distance,
    jaccard,
    normalize_headline,
    significant_tokens,
    simhash64,
    title_fingerprint,
)
from app.services.dedup.judge import UncertainJudge
from app.services.dedup.url import canonicalize_url
from app.services.grounding import numbers_missing_from_source, require_grounded_numbers
from app.core.exceptions import GroundingError
from app.services.text import plain_text


def test_canonical_url_ignores_tracking_host_case_and_slash() -> None:
    left = canonicalize_url("https://WWW.Example.com/world/story/?utm_source=rss&b=2&a=1#top")
    right = canonicalize_url("https://example.com/world/story?a=1&b=2")
    trailing = canonicalize_url("https://example.com/world/story/?a=1&b=2")
    assert left == right == trailing
    assert canonicalize_url("https://example.com/world/story/") == "https://example.com/world/story"


def test_canonical_url_rejects_a_non_http_value() -> None:
    with pytest.raises(ValueError):
        canonicalize_url("notaurl")


def test_outlet_suffix_does_not_erase_a_real_place_name() -> None:
    normalized = normalize_headline("President signs the bill - BBC News")
    assert normalized == "president signs the bill"
    france = title_fingerprint("Election results - France")
    germany = title_fingerprint("Election results - Germany")
    assert france != germany
    assert title_fingerprint("The President Signs a Bill") == title_fingerprint("President signs bill")


def test_jaccard_and_simhash_are_stable() -> None:
    assert jaccard(["bank", "rates"], ["bank", "rates"]) == 1
    assert jaccard(["bank"], ["weather"]) == 0
    assert significant_tokens("The bank holds rates") == ("bank", "holds", "rates")
    digest = simhash64("federal reserve holds rates")
    assert digest == simhash64("federal reserve holds rates")
    assert hamming_distance(digest, digest) == 0
    assert simhash64("federal reserve holds rates") != simhash64("storm closes mountain passes")
    assert block_key("Central bank holds rates") == "central"


def test_plain_text_and_grounding() -> None:
    assert plain_text("<p>Markets rose <b>2%</b>.</p><script>alert(1)</script>") == "Markets rose 2%."
    source = "The bill passed 51 to 49."
    assert numbers_missing_from_source("The bill passed 51 to 49.", source) == []
    assert numbers_missing_from_source("About 300 people were there.", source) == ["300"]
    with pytest.raises(GroundingError):
        require_grounded_numbers("About 300 people were there.", source)
