"""RSS parsing, clustering, and scoring."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.config import NewsSourceConfig
from app.services.dedup.cluster import ClusterText, MatchThresholds, same_story
from app.services.dedup.language import load_aliases, normalized_numbers
from app.services.news.scoring import eligible, score_event
from app.services.news.selection import RankedEvent, order_events
from app.services.news_sources.rss import RssNewsSource, parse_feed, parse_timestamp
from app.services.translation.base import DictionaryTranslator

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
THRESHOLDS = MatchThresholds()
STOPWORDS = {
    "en": frozenset({"the", "a", "an", "in", "at", "of", "to", "and"}),
    "de": frozenset({"die", "der", "das", "bei", "und"}),
}


class MapTransport:
    def __init__(self, bodies: dict[str, bytes], failures: set[str] | None = None) -> None:
        self.bodies = bodies
        self.failures = failures or set()

    def fetch(self, url: str) -> bytes:
        if url in self.failures:
            raise OSError("feed unavailable")
        return self.bodies[url]


def test_rss_fixture_drops_undated_and_keeps_dated() -> None:
    payload = (ROOT / "tests" / "fixtures" / "rss_sample.xml").read_bytes()
    source = NewsSourceConfig(name="Example", url="https://example.com/feed.xml", language="en")
    client = RssNewsSource((source,), MapTransport({source.url: payload}))
    result = client.fetch(window_start=NOW - timedelta(hours=72), window_end=NOW + timedelta(minutes=15))
    assert [article.title for article in result.articles] == ["Central bank holds rates"]
    assert result.articles[0].language == "en"
    assert result.failures == []


def test_atom_entry_parses_link_and_timestamp() -> None:
    payload = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Court ruling in Italy</title>
        <link href="https://example.com/court"/>
        <summary>A court issued a ruling.</summary>
        <updated>2026-11-18T07:00:00Z</updated>
      </entry>
    </feed>
    """
    source = NewsSourceConfig(name="Atom", url="https://example.com/atom", language="de")
    articles = parse_feed(payload, source)
    assert articles[0].canonical_url == "https://example.com/court"
    assert articles[0].language == "de"
    assert parse_timestamp("2026-11-18T07:00:00Z") == datetime(2026, 11, 18, 7, tzinfo=timezone.utc)


def test_one_feed_failure_keeps_the_other_feed() -> None:
    good = NewsSourceConfig(name="Good", url="https://example.com/good.xml", language="en")
    bad = NewsSourceConfig(name="Bad", url="https://example.com/bad.xml", language="en")
    payload = (ROOT / "tests" / "fixtures" / "rss_sample.xml").read_bytes()
    client = RssNewsSource((bad, good), MapTransport({good.url: payload}, failures={bad.url}))
    result = client.fetch(window_start=NOW - timedelta(hours=72), window_end=NOW)
    assert len(result.articles) == 1
    assert result.failures[0].source_name == "Bad"


def test_old_and_future_items_are_outside_the_window() -> None:
    source = NewsSourceConfig(name="Example", url="https://example.com/feed.xml", language="en")
    old = (NOW - timedelta(hours=80)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    payload = f"""<?xml version="1.0"?>
    <rss><channel><item>
      <title>Old earthquake report</title>
      <link>https://example.com/old</link>
      <description>An earthquake report.</description>
      <pubDate>{old}</pubDate>
    </item></channel></rss>""".encode()
    result = RssNewsSource((source,), MapTransport({source.url: payload})).fetch(
        window_start=NOW - timedelta(hours=72),
        window_end=NOW + timedelta(minutes=15),
    )
    assert result.articles == []


def test_english_word_order_variants_cluster() -> None:
    left = ClusterText("Central bank holds rates", "The central bank held rates.", "en")
    right = ClusterText("Rates holds central bank", "Rates held by the central bank.", "en")
    assert same_story(left, right, thresholds=THRESHOLDS, aliases={}, stopwords=STOPWORDS)


def test_france_and_germany_stay_distinct() -> None:
    left = ClusterText("Election results in France", "Election results from France.", "en")
    right = ClusterText("Election results in Germany", "Election results from Germany.", "en")
    assert not same_story(left, right, thresholds=THRESHOLDS, aliases={}, stopwords=STOPWORDS)


def test_entity_and_number_hint_matches_ecb_rate_story() -> None:
    aliases = load_aliases(ROOT / "config" / "entity_aliases.example.json")
    left = ClusterText("ECB holds rates at 4.5 percent", "The ECB holds rates.", "en")
    right = ClusterText("EZB belässt Leitzins bei 4,5 Prozent", "Die EZB belässt den Leitzins.", "de")
    assert normalized_numbers(left.body) == {"4.5"}
    assert normalized_numbers(right.body) == {"4.5"}
    assert same_story(left, right, thresholds=THRESHOLDS, aliases=aliases, stopwords=STOPWORDS)


def test_paraphrase_without_a_shared_number_stays_separate() -> None:
    aliases = load_aliases(ROOT / "config" / "entity_aliases.example.json")
    left = ClusterText("The European Central Bank left policy unchanged", "", "en")
    right = ClusterText("Die Europäische Zentralbank lässt die Zinsen unverändert", "", "de")
    assert not same_story(left, right, thresholds=THRESHOLDS, aliases=aliases, stopwords=STOPWORDS)


def test_dictionary_translator_clusters_a_paraphrase() -> None:
    german = "Die Europäische Zentralbank lässt die Zinsen unverändert"
    english = "The European Central Bank left policy unchanged"
    translator = DictionaryTranslator({("de", german.lower()): english})
    left = ClusterText(english, "", "en")
    right = ClusterText(german, "", "de")
    assert same_story(
        left,
        right,
        thresholds=THRESHOLDS,
        aliases={},
        stopwords=STOPWORDS,
        translator=translator,
    )


def test_today_ranks_before_a_higher_scoring_yesterday_story() -> None:
    ordered = order_events(
        [
            RankedEvent("yesterday", 0.95, "major", "yesterday", 3),
            RankedEvent("today", 0.64, "minor_update", "today", 1),
        ]
    )
    assert [item.event_id for item in ordered] == ["today", "yesterday"]


def test_score_thresholds_match_the_published_formula() -> None:
    older_strong = score_event(band="older", source_count=3, impact=True, opinion=False)
    older_weak = score_event(band="older", source_count=1, impact=True, opinion=False)
    today_single = score_event(band="today", source_count=1, impact=False, opinion=False)
    opinion = score_event(band="today", source_count=3, impact=True, opinion=True)
    assert older_strong.score == 0.75
    assert eligible(older_strong, minimum=0.55, older_minimum=0.75)
    assert older_weak.score == pytest.approx(0.585)
    assert not eligible(older_weak, minimum=0.55, older_minimum=0.75)
    assert today_single.score == pytest.approx(0.635)
    assert eligible(today_single, minimum=0.55, older_minimum=0.75)
    assert opinion.score == 0.0
    assert not eligible(opinion, minimum=0.55, older_minimum=0.75)
