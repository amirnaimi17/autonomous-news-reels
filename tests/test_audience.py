"""Audience filter, source class, scoring, ticket accuracy, and storyboard checks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.database.repository import _STORY_CLASSES
from app.services.news.accuracy import deutschlandticket_accuracy_errors
from app.services.news.editorial import editorial_approves, editorial_relevance_errors
from app.services.news.scoring import eligible, score_event
from app.services.news.selection import RankedEvent, order_events
from app.services.news.source_quality import classify_source

ROOT = Path(__file__).resolve().parents[1]
FEDERAL = "https://www.bundesregierung.de/breg-de/aktuelles/gesetzliche-neuregelungen-november-2026-2459132"
BAHN = "https://www.bahn.de/angebot/regio/deutschland-ticket"
BVG = "https://www.bvg.de/de/deutschlandticket/faqs-deutschlandticket"
ASSESSMENT = {
    "decision": "approve",
    "affected_audience": "People in Germany who commute with the Deutschlandticket",
    "practical_relevance": "The monthly price rises on 1 January 2027, and confirmation depends on the provider.",
    "evidence_urls": [FEDERAL],
    "publication_reason": "The price and the provider exception change a household transport cost.",
}


def _visual_module():
    path = ROOT / ".cursor/skills/verify-reel-pilot/scripts/validate_visual_plan.py"
    spec = importlib.util.spec_from_file_location("validate_visual_plan", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _story_module():
    path = ROOT / ".cursor/skills/verify-reel-pilot/scripts/validate_story_package.py"
    spec = importlib.util.spec_from_file_location("validate_story_package", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_clear_household_story_outranks_a_world_story() -> None:
    ticket = score_event(
        band="yesterday",
        source_count=1,
        impact=False,
        opinion=False,
        text="Kindergeld Änderung für Familien in Deutschland",
        source_urls=(FEDERAL,),
    )
    alaska = score_event(
        band="today",
        source_count=3,
        impact=True,
        opinion=False,
        text="Democrats win the Alaska Senate election",
        source_urls=("https://apnews.com/article/alaska",),
    )
    assert ticket.audience_filter == "clear"
    assert ticket.audience_tier == "A"
    assert eligible(ticket, minimum=0.55, older_minimum=0.75)
    assert alaska.audience_filter == "none"
    assert not eligible(alaska, minimum=0.55, older_minimum=0.75)


def test_borderline_story_needs_an_evidence_based_approval() -> None:
    text = "Sanktionen können Überweisungen von Konten in Deutschland verzögern"
    urls = ("https://www.tagesschau.de/ausland/sanktionen-100.html",)
    waiting = score_event(band="today", source_count=1, impact=True, opinion=False, text=text, source_urls=urls)
    assert waiting.audience_filter == "borderline"
    assert waiting.story_class in {"breaking", "major", "minor_update"}
    assert not eligible(waiting, minimum=0.55, older_minimum=0.75)
    approved = score_event(
        band="today",
        source_count=1,
        impact=True,
        opinion=False,
        text=text,
        source_urls=urls,
        editorial=ASSESSMENT | {"evidence_urls": list(urls)},
    )
    assert approved.audience_filter == "approved"
    assert approved.story_class in {"major", "minor_update", "breaking"}
    assert eligible(approved, minimum=0.55, older_minimum=0.75)


def test_editorial_approval_cannot_cite_an_outside_url() -> None:
    invented = dict(ASSESSMENT)
    invented["evidence_urls"] = ["https://example.com/not-a-source"]
    assert editorial_relevance_errors(invented, [FEDERAL])
    assert not editorial_approves(invented, [FEDERAL])


def test_newsrooms_are_not_government_sources() -> None:
    assert classify_source("https://www.bundesregierung.de/breg-de/aktuelles/example") == "primary"
    assert classify_source("https://www.tagesschau.de/inland/ticket-100.html") == "reputable"
    assert classify_source("https://www.deutschlandfunk.de/preis-106.html") == "reputable"
    assert classify_source("https://www.bahn.de/angebot/regio/deutschland-ticket") == "secondary"
    assert classify_source("https://apnews.com/article/alaska") == "secondary"
    reputable = score_event(
        band="today",
        source_count=2,
        impact=False,
        opinion=False,
        text="Deutschlandticket Preis",
        source_urls=("https://www.tagesschau.de/inland/ticket-100.html",),
    )
    primary = score_event(
        band="today",
        source_count=2,
        impact=False,
        opinion=False,
        text="Deutschlandticket Preis",
        source_urls=(FEDERAL,),
    )
    assert reputable.source_quality == "reputable"
    assert primary.source_quality == "primary"
    assert primary.score > reputable.score


def test_older_official_notice_clears_and_a_thin_one_does_not() -> None:
    official = score_event(
        band="older",
        source_count=1,
        impact=False,
        opinion=False,
        text="Kindergeld steigt",
        source_urls=("https://www.bundesregierung.de/breg-de/aktuelles/kindergeld",),
    )
    thin = score_event(
        band="older",
        source_count=1,
        impact=False,
        opinion=False,
        text="Kindergeld steigt",
        source_urls=("https://example.com/blog/kindergeld",),
    )
    assert official.audience_tier == "A"
    assert official.source_quality == "primary"
    assert official.score == 0.765
    assert eligible(official, minimum=0.55, older_minimum=0.75)
    assert thin.source_quality == "secondary"
    assert thin.score == 0.6675
    assert not eligible(thin, minimum=0.55, older_minimum=0.75)


def test_deutschlandticket_confirmation_stays_with_the_provider() -> None:
    federal = (
        "Zum 1. Januar 2027 steigt der Preis des Deutschlandtickets von 63 auf 66,80 Euro im Monat. "
        "Wer ein Abo abgeschlossen hat, muss der Fortführung aktiv zustimmen, wenn das Verkehrsunternehmen dazu auffordert. "
        "Erhalten Sie keine Kontaktaufnahme, erfolgt die Preisanpassung automatisch."
    )
    overbroad = "دارندگان اشتراک دویچلندتیکت باید ادامه آن را فعالانه تأیید کنند."
    every_holder = "All Deutschlandticket holders must actively confirm the new price."
    deutsche_bahn = (
        "Deutsche Bahn says existing DB Regio customers must respond by 30. November 2026. "
        "An order placed from 15 October 2026 needs no separate confirmation."
    )
    borrowed_deadline = "Every Deutschlandticket holder must reply by 30. November 2026."
    bvg = "BVG says no agreement is required. From 1 January 2027 the Deutschlandticket debit becomes 66.80 euro automatically."
    everyone_automatic = "The Deutschlandticket continues automatically for every provider."
    assert deutschlandticket_accuracy_errors(federal) == []
    assert deutschlandticket_accuracy_errors(deutsche_bahn) == []
    assert deutschlandticket_accuracy_errors(bvg) == []
    assert deutschlandticket_accuracy_errors(overbroad)
    assert deutschlandticket_accuracy_errors(every_holder)
    assert any("Deutsche Bahn" in error for error in deutschlandticket_accuracy_errors(borrowed_deadline))
    assert any("every provider" in error for error in deutschlandticket_accuracy_errors(everyone_automatic))


def test_tier_order_keeps_untagged_rows_on_the_old_band_order() -> None:
    ordered = order_events(
        [
            RankedEvent("tier-c-today", 0.9, "minor_update", "today", 2, "C"),
            RankedEvent("tier-a-yesterday", 0.7, "major", "yesterday", 1, "A"),
        ]
    )
    assert [item.event_id for item in ordered] == ["tier-a-yesterday", "tier-c-today"]
    legacy = order_events(
        [
            RankedEvent("yesterday", 0.95, "major", "yesterday", 3),
            RankedEvent("today", 0.64, "minor_update", "today", 1),
        ]
    )
    assert [item.event_id for item in legacy] == ["today", "yesterday"]


def test_story_class_labels_stay_compatible_with_stored_rows() -> None:
    assert _STORY_CLASSES == {"breaking", "major", "minor_update", "opinion", "duplicate"}


def test_storyboard_accepts_one_photograph_and_rejects_a_decorative_repeat() -> None:
    visual = _visual_module()
    prompt = (
        "Subject: one blank monthly transit card. Environment: a dark commuter table. "
        "Action: a hand waits beside the card. Composition: card at left, open navy field at right. "
        "Camera: close and slightly above. Lighting: one soft practical light. Mood: precise. "
        "Foreground: the card. Background: a blurred window. Negative space for later type. "
        "Palette: dark navy, bright yellow, and white."
    )
    plan = {
        "width": 1080,
        "height": 1920,
        "scenes": [
            {"number": 1, "format": "chart", "fact": "63 euro becomes 66.80 euro", "duration_seconds": 8},
            {"number": 2, "format": "editorial-photograph", "fact": "The card is the subscription", "duration_seconds": 8, "image_prompt": prompt},
            {"number": 3, "format": "typography", "fact": "Ask the company that sold the ticket", "duration_seconds": 8},
        ],
    }
    assert visual.validate(plan) == []
    repeated = {
        "width": 1080,
        "height": 1920,
        "image_count": 3,
        "scenes": [
            {"number": 1, "format": "decorative", "fact": "A station", "duration_seconds": 5, "image_prompt": prompt},
            {"number": 2, "format": "editorial-photograph", "fact": "Same station", "duration_seconds": 5, "image_prompt": prompt + " تیتر"},
        ],
    }
    errors = visual.validate(repeated)
    assert any("decorative" in error for error in errors)
    assert any("Persian" in error for error in errors)
    assert any("image_count" in error for error in errors)


def test_existing_story_packages_still_pass_structural_validation() -> None:
    story = _story_module()
    packages = [
        ROOT / "storage/generated/pilot/20261119-07300041-v3/story_package.json",
        ROOT / "storage/generated/pilot/20261119-07300041-news-report/story_package.json",
    ]
    found = [path for path in packages if path.exists()]
    assert found
    for path in found:
        assert story.validate(json.loads(path.read_text(encoding="utf-8"))) == []
