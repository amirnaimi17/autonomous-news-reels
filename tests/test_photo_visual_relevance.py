"""Regression tests for reel(6) UK–EU irrelevant photograph failures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.reels.photo_vision import (
    VisionScore,
    parse_vision_response,
    pick_best_accepted,
)
from app.reels.photos import (
    PhotoCandidate,
    PhotoError,
    build_scene_photo_queries,
    collect_scene_photos,
    misleading_metadata_problems,
    retrieve_licensed_photos_for_script,
    story_is_uk_eu,
)


def _jpeg(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x336699:s=800x600:d=0.1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


def _uk_eu_script() -> dict:
    scenes = [
        {
            "number": 1,
            "duration_seconds": 9,
            "narration": "خبر خوب برای جوانان.",
            "on_screen_text": "خبر خوب",
            "visual_prompt": "young people celebrating in a city square",
        },
        {
            "number": 2,
            "duration_seconds": 10,
            "narration": "بریتانیا و اتحادیه اروپا نزدیک می‌شوند.",
            "on_screen_text": "بریتانیا و اتحادیه اروپا",
            "visual_prompt": "UK and EU flags together",
        },
        {
            "number": 3,
            "duration_seconds": 10,
            "narration": "فرصت‌های جدید برای جوانان.",
            "on_screen_text": "فرصت‌ها",
            "visual_prompt": "young professionals networking event",
        },
        {
            "number": 4,
            "duration_seconds": 11,
            "narration": "بهبود شرایط زندگی و کار.",
            "on_screen_text": "شرایط زندگی",
            "visual_prompt": "young people working in an office",
        },
    ]
    return {
        "status": "ready",
        "story_package": {
            "event_id": "uk-eu-test",
            "scenes": scenes,
        },
        "storyboard_json": json.dumps({"scenes": scenes}, ensure_ascii=False),
        "fact_pack": {
            "event_summary": "Young people benefit as the UK and EU draw closer again.",
            "verified_facts": [{"text": "Britain left the EU years ago; a new agreement helps youth."}],
        },
    }


def test_story_is_uk_eu_ignores_substring_false_positives() -> None:
    # "eu" inside Deutschland and "uk" inside Zukunft must not flip the detector.
    assert not story_is_uk_eu(
        "Bilger fordert Bekenntnis der Autoindustrie zu Deutschland",
        "Die Zukunft der Produktion in Deutschland ist unklar.",
    )
    assert story_is_uk_eu(
        "Junge Menschen profitieren: EU und Großbritannien nähern sich wieder an",
        "Britain and the European Union agree on new opportunities for young people.",
    )


def test_uk_eu_queries_avoid_german_fallbacks_and_weak_flag_only_terms() -> None:
    title = "Junge Menschen profitieren: EU und Großbritannien nähern sich wieder an"
    summary = "Britain and the European Union agree on new opportunities for young people."
    assert story_is_uk_eu(title, summary)
    queries = build_scene_photo_queries(title, summary, _uk_eu_script())
    flat = " ".join(q for group in queries for q in group).casefold()
    assert "united kingdom european union flags" in flat or "uk eu" in flat
    assert "european university students" in flat or "student exchange" in flat
    assert "german parliament berlin" not in flat
    assert "berlin residential street" not in flat
    assert "german germany" not in flat
    # Scene 2 must not rely on bare "flags together" alone.
    assert any(
        ("kingdom" in q.casefold() or "british" in q.casefold() or "uk" in q.casefold())
        and ("european" in q.casefold() or "eu" in q.casefold())
        and "flag" in q.casefold()
        for q in queries[1]
    )


def test_israeli_flag_metadata_rejected_for_uk_eu_topic() -> None:
    candidate = PhotoCandidate(
        title="Together we will win Slogans and Flags of Israel in Givatayim",
        download_url="https://example.org/israel.jpg",
        source_page="https://commons.wikimedia.org/wiki/File:Israel_flags.jpg",
        author="x",
        license_name="CC BY-SA 4.0",
        license_url="",
        tags=["israel", "flags", "together"],
        description="Hebrew signs and Israeli flags",
    )
    problems = misleading_metadata_problems(
        candidate,
        topic_blob="UK and EU flags together Britain European Union agreement",
    )
    assert problems
    assert any("misleading" in item for item in problems)


def test_historical_illustration_rejected_for_modern_uk_eu_news() -> None:
    candidate = PhotoCandidate(
        title="Romantic Germany (1910) etching",
        download_url="https://example.org/romantic.jpg",
        source_page="https://commons.wikimedia.org/wiki/File:Romantic_Germany.jpg",
        author="archive",
        license_name="No restrictions",
        license_url="",
        description="1910 book plate of a German town square",
    )
    problems = misleading_metadata_problems(
        candidate,
        topic_blob="young people celebrating UK EU agreement Europe",
    )
    assert any("historical" in item for item in problems)


def test_vision_rejects_israeli_flags_and_accepts_uk_eu(tmp_path: Path, monkeypatch) -> None:
    jpeg = tmp_path / "seed.jpg"
    payload = _jpeg(jpeg)
    monkeypatch.setattr("app.reels.photos.time.sleep", lambda *_a, **_k: None)

    # Openverse returns one bad Israel-flag hit and one good UK–EU hit for flag queries.
    def transport(request, timeout):
        url = request.full_url
        if "api.openverse.org" in url:
            import urllib.parse

            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", [""])[0]
            q = query.casefold()
            digest = abs(hash(query)) % 100000
            results = [
                {
                    "title": "Together we will win Slogans and Flags of Israel",
                    "url": "https://live.staticflickr.com/1/israel-shared.jpg",
                    "foreign_landing_url": "https://flickr.com/israel-shared",
                    "creator": "bad",
                    "license": "by",
                    "license_version": "2.0",
                    "license_url": "https://creativecommons.org/licenses/by/2.0/",
                    "provider": "flickr",
                    "width": 1200,
                    "height": 1600,
                    "tags": [{"name": "israel"}, {"name": "flags"}, {"name": "together"}],
                    "description": "Israeli flags and Hebrew signs",
                },
                {
                    "title": f"{query} United Kingdom European Union photograph",
                    "url": f"https://live.staticflickr.com/1/good-{digest}.jpg",
                    "foreign_landing_url": f"https://flickr.com/good-{digest}",
                    "creator": "good",
                    "license": "by",
                    "license_version": "2.0",
                    "license_url": "https://creativecommons.org/licenses/by/2.0/",
                    "provider": "flickr",
                    "width": 1200,
                    "height": 1600,
                    "tags": [{"name": part} for part in query.split()[:6] if len(part) > 2],
                    "description": f"{query} Britain European Union youth students flags",
                },
            ]
            if "flag" not in q:
                results = results[1:]  # keep Israel bait only on flag-like searches
            return json.dumps({"results": results}).encode("utf-8")
        if "commons.wikimedia.org" in url:
            return json.dumps({"query": {"pages": {}}}).encode("utf-8")
        return payload

    def vision_complete(context: dict) -> dict:
        brief = str(context.get("scene_brief") or "").casefold()
        rows = []
        for item in context["candidates"]:
            title = str(item.get("title") or "").casefold()
            if "israel" in title or "hebrew" in title:
                rows.append(
                    {
                        "id": item["id"],
                        "relevance": 15,
                        "misleading": True,
                        "unrelated_flags": True,
                        "suitable_vertical": True,
                        "reason": "Israeli flags unrelated to UK-EU",
                    }
                )
            elif "romantic" in title or "hatzenport" in title or "brazil" in title:
                rows.append(
                    {
                        "id": item["id"],
                        "relevance": 20,
                        "misleading": True,
                        "unrelated_flags": False,
                        "suitable_vertical": True,
                        "reason": "unrelated portrait or landscape",
                    }
                )
            elif "flag" in brief and "flag" not in title:
                rows.append(
                    {
                        "id": item["id"],
                        "relevance": 55,
                        "misleading": False,
                        "unrelated_flags": False,
                        "suitable_vertical": True,
                        "reason": "not flag imagery for a flag scene",
                    }
                )
            else:
                rows.append(
                    {
                        "id": item["id"],
                        "relevance": 88,
                        "misleading": False,
                        "unrelated_flags": False,
                        "suitable_vertical": True,
                        "reason": "matches UK-EU / youth Europe brief",
                    }
                )
        return {"candidates": rows}

    title = "EU und Großbritannien nähern sich wieder an"
    summary = "Young people benefit as Britain and the European Union draw closer."
    assets = retrieve_licensed_photos_for_script(
        title,
        summary,
        _uk_eu_script(),
        tmp_path / "assets",
        transport=transport,
        vision_complete=vision_complete,
        require_vision=True,
        reel_id="uk-eu-vision",
    )
    assert len(assets) == 4
    log = json.loads((tmp_path / "assets" / "image_search_log.json").read_text(encoding="utf-8"))
    vision_rows = [entry for entry in log if entry.get("action") == "vision_score"]
    assert vision_rows
    # Israeli flags must never be assigned: blocked by metadata and/or vision.
    assert any(
        entry.get("action") == "reject_misleading_metadata"
        or entry.get("unrelated_flags")
        for entry in log
    )
    assigned = [entry for entry in log if entry.get("action") == "assigned"]
    assert len(assigned) == 4
    assert all(int(entry.get("vision_relevance") or 0) >= 80 for entry in assigned)
    assert not any("israel" in str(entry.get("title") or "").casefold() for entry in assigned)


def test_vision_parse_and_acceptance_helpers() -> None:
    scores = parse_vision_response(
        {
            "candidates": [
                {
                    "id": "1",
                    "relevance": 92,
                    "misleading": False,
                    "unrelated_flags": False,
                    "suitable_vertical": True,
                    "reason": "UK EU flags",
                },
                {
                    "id": "2",
                    "relevance": 40,
                    "misleading": True,
                    "unrelated_flags": True,
                    "suitable_vertical": True,
                    "reason": "Israeli flags",
                },
            ]
        },
        expected_ids=["1", "2", "3"],
    )
    assert scores[2].relevance == 0  # missing id fails closed
    best = pick_best_accepted(scores)
    assert best is not None
    assert best.candidate_id == "1"
    assert pick_best_accepted([VisionScore("2", 90, True, False, True, "bad")]) is None


def test_generic_landscape_cannot_win_on_metadata_alone(tmp_path: Path, monkeypatch) -> None:
    jpeg = tmp_path / "seed.jpg"
    payload = _jpeg(jpeg)
    monkeypatch.setattr("app.reels.photos.time.sleep", lambda *_a, **_k: None)

    def transport(request, timeout):
        url = request.full_url
        if "api.openverse.org" in url:
            return json.dumps(
                {
                    "results": [
                        {
                            "title": "Hatzenport town landscape Germany Europe young professionals networking event",
                            "url": "https://live.staticflickr.com/1/landscape.jpg",
                            "foreign_landing_url": "https://flickr.com/landscape",
                            "creator": "x",
                            "license": "by",
                            "license_version": "2.0",
                            "license_url": "https://creativecommons.org/licenses/by/2.0/",
                            "provider": "flickr",
                            "width": 1200,
                            "height": 800,
                            "tags": [
                                {"name": "young"},
                                {"name": "professionals"},
                                {"name": "networking"},
                                {"name": "event"},
                                {"name": "Europe"},
                            ],
                            "description": "Mosel valley landscape",
                        }
                    ]
                }
            ).encode("utf-8")
        if "commons.wikimedia.org" in url:
            return json.dumps({"query": {"pages": {}}}).encode("utf-8")
        return payload

    def vision_complete(context: dict) -> dict:
        return {
            "candidates": [
                {
                    "id": item["id"],
                    "relevance": 25,
                    "misleading": True,
                    "unrelated_flags": False,
                    "suitable_vertical": False,
                    "reason": "generic landscape not a networking scene",
                }
                for item in context["candidates"]
            ]
        }

    with pytest.raises(PhotoError, match="no visually relevant photograph"):
        collect_scene_photos(
            [["young professionals networking event Europe", "European university students"]],
            tmp_path / "assets-land",
            transport=transport,
            relevance_terms=[["young", "professionals", "networking", "event", "Europe"]],
            story_topic="UK EU youth agreement",
            scene_briefs=["young professionals networking event for UK-EU youth"],
            vision_complete=vision_complete,
            require_vision=True,
            title="UK EU youth",
            summary="European agreement for young people",
        )
