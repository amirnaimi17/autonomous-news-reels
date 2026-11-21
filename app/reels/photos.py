"""Search and download visually relevant photographs for Reel scenes.

Discovery uses Openverse and Wikimedia Commons. Google Images is not scraped.
Selection prioritizes scene relevance, resolution, and downloadability.
License, author, and attribution metadata are recorded when present but are
never required to accept an image. AI image generation is never used.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "autonomous-news-reels/1.0 (local pilot; scene photo retrieval)"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
MIN_IMAGE_WIDTH = 640
MIN_IMAGE_HEIGHT = 480

Transport = Callable[[urllib.request.Request, float], bytes]


class PhotoError(RuntimeError):
    """Photograph retrieval or validation failed."""


@dataclass
class PhotoCandidate:
    title: str
    download_url: str
    source_page: str
    author: str
    license_name: str
    license_url: str
    width: int | None = None
    height: int | None = None
    provider: str = ""
    attribution: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class PhotoAsset:
    scene_index: int
    path: str
    source_url: str
    download_url: str
    author: str
    license_name: str
    license_url: str
    attribution: str
    width: int
    height: int
    bytes: int
    role: str = "scene"
    title: str = ""
    provider: str = ""


@dataclass
class SearchLog:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def add(self, **kwargs: Any) -> None:
        self.entries.append(dict(kwargs))

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path


_GRAPHIC_PROMPT_HINTS = (
    "graphic",
    "typography",
    "type card",
    "title card",
    "opener",
    "closing",
    "amount card",
    "calendar graphic",
    "text only",
    "no faces",
    "solid color",
)


def looks_like_graphic_prompt(visual: str) -> bool:
    folded = (visual or "").casefold()
    return any(hint in folded for hint in _GRAPHIC_PROMPT_HINTS)


def _openverse_tags(item: dict[str, Any]) -> list[str]:
    raw = item.get("tags") or []
    tags: list[str] = []
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                name = str(entry.get("name") or entry.get("display_name") or "").strip()
            else:
                name = str(entry).strip()
            if name:
                tags.append(name)
    elif isinstance(raw, str) and raw.strip():
        tags.extend(part.strip() for part in raw.split(",") if part.strip())
    return tags[:24]


def license_evidence_problems(
    *,
    license_name: str,
    license_url: str,
    source_url: str,
    author: str,
    restrictions: str | None = None,
) -> list[str]:
    """Deprecated no-op kept for callers/tests.

    Licensing metadata is optional for scene photo selection. Always returns [].
    """

    del license_name, license_url, source_url, author, restrictions
    return []


def quality_problems(
    *,
    width: int | None,
    height: int | None,
    min_width: int = MIN_IMAGE_WIDTH,
    min_height: int = MIN_IMAGE_HEIGHT,
) -> list[str]:
    """Reject images that are too small for Reel framing."""

    problems: list[str] = []
    w = int(width or 0)
    h = int(height or 0)
    if w and w < min_width:
        problems.append(f"width {w} below {min_width}")
    if h and h < min_height:
        problems.append(f"height {h} below {min_height}")
    return problems


def candidate_metadata_blob(candidate: PhotoCandidate) -> str:
    parts = [
        candidate.title,
        candidate.description,
        candidate.attribution,
        " ".join(candidate.tags),
        candidate.author,
        candidate.provider,
    ]
    return " ".join(part for part in parts if part).casefold()


def relevance_terms_from_queries(queries: list[str], *, extra: list[str] | None = None) -> list[str]:
    terms: list[str] = []
    for query in queries:
        terms.extend(_tokenize(query))
    if extra:
        terms.extend(_tokenize(" ".join(extra)))
    # Drop ultra-generic anchors that alone prove nothing.
    # Institutional search fallbacks are excluded by using only early queries for
    # relevance; acceptance still requires scene-specific term overlap.
    generic = {
        "germany",
        "german",
        "deutschland",
        "berlin",
        "photograph",
        "photo",
        "image",
        "news",
        "scene",
    }
    ordered = [term for term in dict.fromkeys(terms) if term.casefold() not in generic]
    return ordered[:16]


def candidate_relevance_score(candidate: PhotoCandidate, terms: list[str]) -> int:
    """Count meaningful metadata overlaps with the scene search terms."""

    if not terms:
        return 0
    blob = candidate_metadata_blob(candidate)
    return sum(1 for term in terms if term.casefold() in blob)


def candidate_is_relevant(candidate: PhotoCandidate, terms: list[str], *, min_hits: int = 1) -> bool:
    if not terms:
        return False
    return candidate_relevance_score(candidate, terms) >= min_hits


_RELAX_DROP = {
    "close",
    "close-up",
    "taking",
    "notes",
    "person",
    "people",
    "with",
    "from",
    "into",
    "over",
    "under",
    "about",
    "after",
    "before",
    "simple",
    "modern",
    "beautiful",
    "collage",
    "thoughtful",
    "looking",
    "watching",
    "standing",
    "sitting",
    "holding",
}


_VISUAL_FILLER = _RELAX_DROP | {
    "photo",
    "photograph",
    "image",
    "picture",
    "showing",
    "depicting",
    "scene",
    "view",
    "near",
    "next",
    "some",
    "many",
    "several",
}


_GEO_ONLY = {
    "germany",
    "german",
    "deutschland",
    "berlin",
    "europe",
    "european",
}


def _is_weak_search_query(query: str) -> bool:
    """Reject meaningless or geo-only queries such as 'German Germany'."""

    tokens = [
        token.casefold()
        for token in _tokenize(query)
        if token.casefold() not in _STOPWORDS
    ]
    if len(tokens) < 2:
        return True
    non_geo = [token for token in tokens if token not in _GEO_ONLY]
    return len(non_geo) < 1


def _with_location(phrase: str, *, germany: str = "Germany") -> list[str]:
    """Return phrase plus an optional location variant without redundant geo stacking."""

    cleaned = " ".join(str(phrase or "").split()).strip()
    if not cleaned:
        return []
    variants = [cleaned]
    folded = cleaned.casefold()
    if germany.casefold() not in folded and "deutschland" not in folded:
        # Avoid "German Germany" / "Berlin Germany" style redundancy.
        lead = _tokenize(cleaned)
        if lead and lead[0].casefold() not in _GEO_ONLY:
            variants.append(f"{cleaned} {germany}")
    return variants


def searchable_visual_queries(visual: str, *, germany: str = "Germany") -> list[str]:
    """Turn a long art-direction prompt into short Commons/Openverse search phrases.

    Poetic prompts like "a thoughtful person looking at a car factory" return zero
    hits; noun-focused queries like "car factory Germany" succeed.
    """

    text = " ".join(str(visual or "").split()).strip()
    if not text:
        return []
    tokens = [
        token
        for token in _tokenize(text)
        if token.casefold() not in _VISUAL_FILLER and re.fullmatch(r"[A-Za-z][A-Za-z-]{2,}", token or "")
    ]
    queries: list[str] = []
    if len(tokens) >= 2:
        short = " ".join(tokens[:4])
        queries.extend(_with_location(short, germany=germany))
    elif len(tokens) == 1 and tokens[0].casefold() not in _GEO_ONLY:
        queries.extend(_with_location(tokens[0], germany=germany))
    # Keep the original last so search still tries it, but short forms run first.
    if re.search(r"[A-Za-z]{3,}", text) and not _is_weak_search_query(text):
        queries.extend(_with_location(text, germany=germany))
    return list(dict.fromkeys(item for item in queries if item.strip() and not _is_weak_search_query(item)))


def topic_synonym_queries(title: str, summary: str, visual: str = "") -> list[str]:
    """Produce short English synonym queries for common news visual subjects."""

    blob = f"{title} {summary} {visual}".casefold()
    keys = {token.casefold() for token in _tokenize(f"{title} {summary} {visual}")}
    out: list[str] = []
    auto_keys = {
        "auto",
        "car",
        "cars",
        "factory",
        "fahrzeug",
        "industrie",
        "automotive",
        "hybrid",
        "hybride",
        "verbrenner",
        "autoindustrie",
        "autokonzern",
        "autokonzernen",
        "volkswagen",
        "bmw",
        "mercedes",
    }
    if keys & auto_keys or "autoindustrie" in blob:
        out.extend(
            [
                "German automotive factory",
                "Volkswagen production line",
                "German car manufacturing workers",
                "Car assembly plant Germany",
                "car factory Germany",
                "automobile factory Germany",
                "car assembly line Germany",
                "automotive manufacturing plant",
            ]
        )
    if keys & {"document", "legal", "law", "contract", "pen", "note", "calculator", "paperwork"}:
        out.extend(
            [
                "calculator paperwork desk",
                "financial planning documents desk",
                "euro coins calculator Germany",
            ]
        )
    if keys & {"pension", "riester", "retire", "retirement", "vorsorge"} or any(
        hint in blob for hint in ("riester", "altersvorsorge", "pension")
    ):
        out.extend(
            [
                "retirement savings Germany",
                "pension documents Germany",
            ]
        )
    if keys & {"family", "everyday", "community", "home", "people", "elderly", "kindergeld"}:
        out.extend(
            [
                "everyday life Germany city street",
                "Berlin residential street photograph",
                "family benefits office Germany",
            ]
        )
    if keys & {"parliament", "bundesrat", "bundestag", "government", "reichstag"}:
        out.extend(
            [
                "German parliament Berlin",
                "Bundesrat building Berlin",
                "Reichstag Berlin exterior",
            ]
        )
    return list(dict.fromkeys(item for item in out if not _is_weak_search_query(item)))


def relaxed_relevance_terms(strict_terms: Sequence[str], queries: Sequence[str]) -> list[str]:
    """Broader scene terms for a second search pass. Never empty-on-purpose.

    Drops modifier noise from the strict list, then keeps tokens from the most
    specific (early) queries. Returns [] when no meaningful scene terms remain
    so callers fail closed instead of accepting unrelated photos.
    """

    strict = [str(term) for term in strict_terms if str(term).strip()]
    narrowed = [term for term in strict if term.casefold() not in _RELAX_DROP]
    primary_queries = list(queries[:3]) if queries else []
    from_primary = relevance_terms_from_queries([str(item) for item in primary_queries])
    from_primary = [term for term in from_primary if term.casefold() not in _RELAX_DROP]
    ordered = list(dict.fromkeys([*narrowed, *from_primary]))
    # Require at least one concrete term so "Germany"/"Berlin" alone cannot pass.
    concrete = [
        term
        for term in ordered
        if term.casefold() not in {"berlin", "germany", "german", "deutschland", "photograph", "photo"}
    ]
    return concrete[:12]


def normalize_openverse_license(code: str | None, version: str | None = None) -> str:
    raw = (code or "").strip().casefold()
    ver = (version or "").strip()
    mapping = {
        "cc0": "CC0",
        "pdm": "Public domain",
        "by": "CC BY",
        "by-sa": "CC BY-SA",
        "by-nc": "CC BY-NC",
        "by-nd": "CC BY-ND",
        "by-nc-sa": "CC BY-NC-SA",
        "by-nc-nd": "CC BY-NC-ND",
    }
    base = mapping.get(raw, (code or "").strip())
    if base.startswith("CC BY") and ver:
        return f"{base} {ver}"
    if base == "CC0":
        return "CC0"
    return base


def _default_transport(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def http_get_json(
    url: str,
    *,
    transport: Transport | None = None,
    timeout: float = 45.0,
    retries: int = 5,
    log: SearchLog | None = None,
) -> dict[str, Any]:
    sender = transport or _default_transport
    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            raw = sender(request, timeout)
            payload = json.loads(raw.decode("utf-8"))
            if log is not None:
                log.add(action="http_get_json", url=url, attempt=attempt + 1, ok=True)
            return payload
        except urllib.error.HTTPError as exc:
            last_error = exc
            if log is not None:
                log.add(action="http_get_json", url=url, attempt=attempt + 1, ok=False, status=exc.code)
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                time.sleep(5 * (attempt + 1))
                continue
            raise PhotoError(f"HTTP {exc.code} for {url}") from exc
        except Exception as exc:  # noqa: BLE001 - network/parse failures become PhotoError
            last_error = exc
            if log is not None:
                log.add(action="http_get_json", url=url, attempt=attempt + 1, ok=False, error=str(exc))
            if attempt + 1 < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise PhotoError(f"request failed for {url}: {exc}") from exc
    raise PhotoError(f"request failed for {url}: {last_error}")


def search_openverse(
    query: str,
    *,
    page_size: int = 12,
    transport: Transport | None = None,
    log: SearchLog | None = None,
) -> list[PhotoCandidate]:
    """Discover photographs via Openverse. License filters are not applied."""

    params = {
        "q": query,
        "page_size": str(page_size),
        "mature": "false",
    }
    url = OPENVERSE_API + "?" + urllib.parse.urlencode(params)
    try:
        payload = http_get_json(url, transport=transport, log=log)
    except PhotoError as exc:
        # Openverse outages (504/429) must not abort the whole reel; Commons still runs.
        if log is not None:
            log.add(action="search_openverse_failed", query=query, error=str(exc))
        return []
    found: list[PhotoCandidate] = []
    discovered = 0
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        discovered += 1
        license_name = normalize_openverse_license(item.get("license"), item.get("license_version"))
        download = str(item.get("url") or "").strip()
        source = str(item.get("foreign_landing_url") or item.get("detail_url") or item.get("url") or "").strip()
        author = str(item.get("creator") or "").strip()
        license_url = str(item.get("license_url") or "").strip()
        width = int(item["width"]) if item.get("width") else None
        height = int(item["height"]) if item.get("height") else None
        quality = quality_problems(width=width, height=height)
        if quality:
            if log is not None:
                log.add(
                    action="reject_quality",
                    query=query,
                    title=item.get("title"),
                    reason="; ".join(quality),
                    width=width,
                    height=height,
                )
            continue
        if not download:
            if log is not None:
                log.add(action="reject_missing_download", query=query, title=item.get("title"))
            continue
        found.append(
            PhotoCandidate(
                title=str(item.get("title") or ""),
                download_url=download,
                source_page=source or download,
                author=author,
                license_name=license_name,
                license_url=license_url,
                width=width,
                height=height,
                provider=str(item.get("provider") or item.get("source") or "openverse"),
                attribution=str(item.get("attribution") or ""),
                tags=_openverse_tags(item),
                description=str(item.get("description") or ""),
            )
        )
    if log is not None:
        log.add(
            action="search_openverse",
            query=query,
            discovered=discovered,
            accepted=len(found),
        )
    return found


def search_commons(
    query: str,
    *,
    limit: int = 8,
    transport: Transport | None = None,
    log: SearchLog | None = None,
) -> list[PhotoCandidate]:
    """Discover photographs on Wikimedia Commons (with 429 backoff)."""

    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": query,
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": "1280",
        "origin": "*",
    }
    url = COMMONS_API + "?" + urllib.parse.urlencode(params)
    try:
        payload = http_get_json(url, transport=transport, retries=6, log=log)
    except PhotoError as exc:
        if log is not None:
            log.add(action="search_commons_failed", query=query, error=str(exc))
        return []
    pages = (payload.get("query") or {}).get("pages") or {}
    found: list[PhotoCandidate] = []
    discovered = 0
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = str(info.get("mime") or "")
        if not mime.startswith("image/"):
            continue
        discovered += 1
        meta = info.get("extmetadata") or {}
        license_name = str((meta.get("LicenseShortName") or {}).get("value") or "")
        artist_html = str((meta.get("Artist") or {}).get("value") or "")
        author = re.sub(r"<[^>]+>", "", artist_html).strip()
        license_url = str((meta.get("LicenseUrl") or {}).get("value") or "")
        download = str(info.get("thumburl") or info.get("url") or "").strip()
        source = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
            str(page.get("title") or "").replace(" ", "_")
        )
        description = re.sub(
            r"<[^>]+>", "", str((meta.get("ImageDescription") or {}).get("value") or "")
        ).strip()
        categories = str((meta.get("Categories") or {}).get("value") or "")
        tags = [part.strip() for part in categories.split("|") if part.strip()][:24]
        width = int(info["thumbwidth"]) if info.get("thumbwidth") else info.get("width")
        height = int(info["thumbheight"]) if info.get("thumbheight") else info.get("height")
        quality = quality_problems(width=width, height=height)
        if quality:
            if log is not None:
                log.add(
                    action="reject_quality",
                    query=query,
                    title=page.get("title"),
                    reason="; ".join(quality),
                    width=width,
                    height=height,
                )
            continue
        if not download:
            if log is not None:
                log.add(action="reject_missing_download", query=query, title=page.get("title"))
            continue
        attribution = " / ".join(part for part in (author, license_name) if part) or ""
        found.append(
            PhotoCandidate(
                title=str(page.get("title") or ""),
                download_url=download,
                source_page=source or download,
                author=author,
                license_name=license_name,
                license_url=license_url,
                width=width,
                height=height,
                provider="wikimedia_commons",
                attribution=attribution,
                tags=tags,
                description=description,
            )
        )
    if log is not None:
        log.add(
            action="search_commons",
            query=query,
            discovered=discovered,
            accepted=len(found),
        )
    return found


def download_image(
    url: str,
    destination: Path,
    *,
    transport: Transport | None = None,
    timeout: float = 60.0,
    retries: int = 6,
    log: SearchLog | None = None,
) -> Path:
    sender = transport or _default_transport
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            data = sender(request, timeout)
            if len(data) < 2048:
                raise PhotoError(f"download too small ({len(data)} bytes): {url}")
            # Reject HTML error pages masquerading as images.
            head = data[:200].lstrip().lower()
            if head.startswith(b"<!doctype") or head.startswith(b"<html") or b"too many requests" in head:
                raise PhotoError(f"download returned HTML, not an image: {url}")
            destination.write_bytes(data)
            if log is not None:
                log.add(action="download", url=url, path=str(destination), bytes=len(data), attempt=attempt + 1, ok=True)
            return destination
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if log is not None:
                log.add(action="download", url=url, attempt=attempt + 1, ok=False, error=str(exc))
            if attempt + 1 < retries:
                time.sleep(4 * (attempt + 1))
                continue
            raise PhotoError(f"download failed for {url}: {exc}") from exc
    raise PhotoError(f"download failed for {url}: {last_error}")


def validate_image_file(path: Path, *, min_width: int = 640, min_height: int = 480) -> dict[str, Any]:
    if not path.is_file():
        raise PhotoError(f"image missing: {path}")
    data = path.read_bytes()[:32]
    if data.startswith(b"\xff\xd8\xff"):
        fmt = "JPEG"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        fmt = "PNG"
    elif data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        fmt = "WEBP"
    else:
        raise PhotoError(f"unsupported or corrupt image header: {path}")
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,codec_name",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        stream = (payload.get("streams") or [{}])[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    except Exception as exc:  # noqa: BLE001
        raise PhotoError(f"invalid image file {path}: {exc}") from exc
    if width < min_width or height < min_height:
        raise PhotoError(f"image too small {width}x{height}: {path}")
    return {"width": width, "height": height, "format": fmt, "bytes": path.stat().st_size}


def require_photographic_assets(assets: list[dict[str, Any]], *, expected_scenes: int = 4) -> list[str]:
    """Return problems if any scene lacks a usable local photograph file."""

    problems: list[str] = []
    if expected_scenes < 1:
        problems.append("expected_scenes must be >= 1")
        return problems
    if len(assets) != expected_scenes:
        problems.append(f"expected {expected_scenes} photographic assets, got {len(assets)}")
    for index in range(expected_scenes):
        asset = assets[index] if index < len(assets) else {}
        path = Path(str(asset.get("path") or ""))
        if not path.is_file():
            problems.append(f"scene {index + 1}: missing photograph file")
            continue
        try:
            validate_image_file(path)
        except PhotoError as exc:
            problems.append(f"scene {index + 1}: {exc}")
        license_name = str(asset.get("license_name") or "").strip().casefold()
        if license_name in {"original-graphic", "remotion-graphic", "silent-fixture"}:
            problems.append(f"scene {index + 1}: graphic placeholder is not a photograph")
    return problems


def _candidate_priority(item: PhotoCandidate, *, relevance: int = 0) -> tuple[int, int, int, int]:
    """Prefer relevance, portrait-friendly aspect, reliable hosts, then resolution."""

    host = urllib.parse.urlparse(item.download_url).netloc.casefold()
    if "staticflickr.com" in host or "live.staticflickr.com" in host:
        host_rank = 0
    elif "images.unsplash.com" in host or "images.pexels.com" in host:
        host_rank = 1
    elif "upload.wikimedia.org" in host:
        host_rank = 2
    else:
        host_rank = 3
    width = int(item.width or 0)
    height = int(item.height or 0)
    if height and width and height >= width:
        aspect_rank = 0
    elif height and width:
        aspect_rank = 2
    else:
        aspect_rank = 1
    pixels = width * height
    return (-relevance, aspect_rank, host_rank, -pixels)


def _iter_candidates(
    candidates: list[PhotoCandidate],
    *,
    used_urls: set[str],
    relevance_terms: list[str] | None = None,
    log: SearchLog | None = None,
    scene_number: int = 0,
):
    terms = [str(term) for term in (relevance_terms or []) if str(term).strip()]
    # Relevance is mandatory: empty term lists never accept a photograph.
    if not terms:
        if log is not None:
            log.add(action="reject_empty_relevance", scene=scene_number)
        return
    scored: list[tuple[PhotoCandidate, int]] = []
    for item in candidates:
        if item.download_url in used_urls or item.source_page in used_urls:
            if log is not None:
                log.add(
                    action="reject_duplicate",
                    scene=scene_number,
                    url=item.download_url,
                    source=item.source_page,
                )
            continue
        score = candidate_relevance_score(item, terms)
        if score < 1:
            if log is not None:
                log.add(
                    action="reject_relevance",
                    scene=scene_number,
                    title=item.title,
                    source=item.source_page,
                    terms=terms[:8],
                    score=score,
                )
            continue
        scored.append((item, score))
    ordered = sorted(scored, key=lambda pair: _candidate_priority(pair[0], relevance=pair[1]))
    for item, _score in ordered:
        yield item


def collect_scene_photos(
    scene_queries: list[list[str]],
    destination_dir: Path,
    *,
    transport: Transport | None = None,
    prefer_openverse: bool = True,
    relevance_terms: list[list[str]] | None = None,
    log: SearchLog | None = None,
) -> tuple[list[PhotoAsset], SearchLog]:
    """Search and download one relevant photograph per scene query list."""

    if not scene_queries:
        raise PhotoError("scene_queries is empty; storyboard must define scenes")
    log = log or SearchLog()
    destination_dir.mkdir(parents=True, exist_ok=True)
    assets: list[PhotoAsset] = []
    used: set[str] = set()
    for scene_index, queries in enumerate(scene_queries):
        if not queries:
            raise PhotoError(f"scene {scene_index + 1} has no photo search queries")
        pools: list[PhotoCandidate] = []
        for query in queries:
            if prefer_openverse:
                pools.extend(search_openverse(query, transport=transport, log=log))
            pools.extend(search_commons(query, transport=transport, log=log))
        log.add(
            action="scene_pool",
            scene=scene_index + 1,
            queries=queries,
            discovered=len(pools),
            unique_urls=len({item.download_url for item in pools}),
        )
        default_terms = relevance_terms_from_queries(queries[:3] if len(queries) > 3 else queries)
        terms = (
            relevance_terms[scene_index]
            if relevance_terms is not None and scene_index < len(relevance_terms)
            else default_terms
        )
        chosen_asset: PhotoAsset | None = None
        last_error: Exception | None = None
        # Relevance stays mandatory: never accept an unrelated image just to fill a slot.
        if not terms:
            log.add(action="scene_failed", scene=scene_index + 1, reason="empty_relevance", queries=queries)
            raise PhotoError(
                f"no relevant photograph for scene {scene_index + 1}; "
                f"relevance terms are empty; queries={queries}"
            )
        relaxed = relaxed_relevance_terms(terms, queries)
        attempt_terms = [terms]
        if relaxed and relaxed != terms:
            attempt_terms.append(relaxed)
        for pass_index, active_terms in enumerate(attempt_terms):
            if chosen_asset is not None:
                break
            if not active_terms:
                continue
            if pass_index:
                log.add(
                    action="relax_relevance",
                    scene=scene_index + 1,
                    pass_index=pass_index,
                    terms=active_terms[:8],
                )
            for chosen in _iter_candidates(
                pools,
                used_urls=used,
                relevance_terms=active_terms,
                log=log,
                scene_number=scene_index + 1,
            ):
                if chosen.download_url in used or chosen.source_page in used:
                    log.add(
                        action="reject_duplicate",
                        scene=scene_index + 1,
                        url=chosen.download_url,
                        source=chosen.source_page,
                    )
                    continue
                ext = ".jpg"
                lower = chosen.download_url.casefold()
                if ".png" in lower:
                    ext = ".png"
                elif ".webp" in lower:
                    ext = ".webp"
                path = destination_dir / f"scene-{scene_index + 1:02d}{ext}"
                try:
                    download_image(chosen.download_url, path, transport=transport, log=log, retries=3)
                    meta = validate_image_file(path)
                except PhotoError as exc:
                    last_error = exc
                    log.add(
                        action="download_failed",
                        scene=scene_index + 1,
                        url=chosen.download_url,
                        error=str(exc),
                    )
                    continue
                attribution = chosen.attribution or " / ".join(
                    part for part in (chosen.author, chosen.license_name) if part
                )
                chosen_asset = PhotoAsset(
                    scene_index=scene_index,
                    path=str(path.resolve()),
                    source_url=chosen.source_page or chosen.download_url,
                    download_url=chosen.download_url,
                    author=chosen.author,
                    license_name=chosen.license_name,
                    license_url=chosen.license_url,
                    attribution=attribution,
                    width=int(meta["width"]),
                    height=int(meta["height"]),
                    bytes=int(meta["bytes"]),
                    title=chosen.title,
                    provider=chosen.provider,
                )
                used.add(chosen.download_url)
                if chosen.source_page:
                    used.add(chosen.source_page)
                log.add(
                    action="assigned",
                    scene=scene_index + 1,
                    path=chosen_asset.path,
                    source=chosen_asset.source_url,
                    title=chosen_asset.title,
                    provider=chosen_asset.provider,
                    width=chosen_asset.width,
                    height=chosen_asset.height,
                    relevance=candidate_relevance_score(chosen, active_terms),
                    relaxed=pass_index > 0,
                )
                break
        if chosen_asset is None:
            log.add(
                action="scene_failed",
                scene=scene_index + 1,
                queries=queries,
                discovered=len(pools),
                last_error=str(last_error) if last_error else None,
            )
            raise PhotoError(
                f"no relevant photograph for scene {scene_index + 1}; "
                f"queries={queries}; discovered={len(pools)}; last_error={last_error}"
            )
        assets.append(chosen_asset)
    return assets, log


def write_attribution_manifest(assets: list[PhotoAsset], path: Path, *, reel_id: str) -> Path:
    payload = {
        "reel_id": reel_id,
        "note": (
            "Scene photographs selected for visual relevance. License/author fields are "
            "optional metadata when the provider supplied them; they are not a clearance opinion."
        ),
        "assets": [
            {
                "scene_index": asset.scene_index,
                "scene_number": asset.scene_index + 1,
                "path": asset.path,
                "source_url": asset.source_url,
                "download_url": asset.download_url,
                "author": asset.author,
                "license_name": asset.license_name,
                "license_url": asset.license_url,
                "attribution": asset.attribution,
                "width": asset.width,
                "height": asset.height,
                "bytes": asset.bytes,
                "title": asset.title,
                "provider": asset.provider,
                "role": asset.role,
            }
            for asset in assets
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def assets_for_render(photos: list[PhotoAsset]) -> list[dict[str, Any]]:
    """Map PhotoAsset rows onto the index-aligned render asset dicts."""

    return [
        {
            "path": photo.path,
            "source_url": photo.source_url,
            "author": photo.author,
            "license_name": photo.license_name,
            "license_url": photo.license_url,
            "role": "scene",
            "attribution": photo.attribution,
        }
        for photo in photos
    ]


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "over",
    "under",
    "about",
    "after",
    "before",
    "eine",
    "einer",
    "einem",
    "einen",
    "oder",
    "auch",
    "nicht",
    "sich",
    "wird",
    "werden",
    "sind",
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "und",
    "mit",
    "von",
    "zu",
    "im",
    "in",
    "auf",
    "für",
    "bei",
    "amp",
}


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-zÄÖÜäöüß0-9]{3,}", text or "")
    cleaned: list[str] = []
    seen: set[str] = set()
    for word in words:
        key = word.casefold()
        if key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        cleaned.append(word)
    return cleaned


def _scene_list_from_script(script: dict[str, Any]) -> list[dict[str, Any]]:
    package = script.get("story_package")
    if isinstance(package, dict) and isinstance(package.get("scenes"), list):
        return [scene for scene in package["scenes"] if isinstance(scene, dict)]
    board = script.get("storyboard_json") or "[]"
    if isinstance(board, str):
        try:
            parsed = json.loads(board)
        except json.JSONDecodeError:
            return []
    else:
        parsed = board
    if isinstance(parsed, dict) and isinstance(parsed.get("scenes"), list):
        return [scene for scene in parsed["scenes"] if isinstance(scene, dict)]
    if isinstance(parsed, list):
        return [scene for scene in parsed if isinstance(scene, dict)]
    return []


def build_scene_photo_queries(
    candidate_title: str,
    candidate_summary: str,
    script: dict[str, Any],
    *,
    fact_pack: dict[str, Any] | None = None,
) -> list[list[str]]:
    """Build Openverse/Commons query lists dynamically for every storyboard scene.

    Raises ``PhotoError`` when the storyboard is missing or has no scenes.
    """

    scenes = _scene_list_from_script(script)
    if not scenes:
        raise PhotoError("storyboard is missing or invalid; cannot build photo queries")
    title_tokens = _tokenize(candidate_title)[:6]
    summary_tokens = _tokenize(candidate_summary)[:8]
    fact_tokens: list[str] = []
    pack = fact_pack if isinstance(fact_pack, dict) else script.get("fact_pack")
    if isinstance(pack, dict):
        fact_tokens = _tokenize(str(pack.get("event_summary") or ""))[:8]
        for item in pack.get("verified_facts") or []:
            if isinstance(item, dict):
                fact_tokens.extend(_tokenize(str(item.get("text") or ""))[:4])
        fact_tokens = list(dict.fromkeys(fact_tokens))[:10]
    topic = " ".join(title_tokens[:4]).strip()
    if not topic:
        raise PhotoError("cannot derive topic tokens from the story title")
    germany = "Germany"

    queries: list[list[str]] = []
    for index, scene in enumerate(scenes):
        visual = str(scene.get("visual_prompt") or "").strip()
        graphic_like = looks_like_graphic_prompt(visual)
        scene_queries: list[str] = []
        # Short searchable English phrases first — long art-direction lines often hit 0 results.
        if visual and not graphic_like:
            scene_queries.extend(searchable_visual_queries(visual, germany=germany))
        scene_queries.extend(
            topic_synonym_queries(candidate_title, candidate_summary, visual if not graphic_like else "")
        )
        # English topic leftovers from the title/summary (skip German-only token soup).
        english_tokens = [
            token
            for token in (title_tokens + summary_tokens + fact_tokens)
            if re.fullmatch(r"[A-Za-z][A-Za-z-]{2,}", token or "") and token.casefold() not in _GEO_ONLY
        ]
        if len(english_tokens) >= 2:
            english_topic = " ".join(english_tokens[:5])
            scene_queries.extend(_with_location(english_topic, germany=germany))
        elif len(english_tokens) == 1:
            scene_queries.extend(_with_location(english_tokens[0], germany=germany))
        # Durable institutional English fallbacks last (search coverage only).
        scene_queries.extend(
            [
                "German parliament Berlin",
                "German government building Berlin",
                "Berlin city skyline photograph",
                "euro banknotes Germany",
            ]
        )
        ordered = [
            item
            for item in dict.fromkeys(item for item in scene_queries if item.strip())
            if not _is_weak_search_query(item)
        ]
        if not ordered:
            raise PhotoError(f"scene {index + 1} produced no photo search queries")
        queries.append(ordered[:8])
    return queries


def retrieve_licensed_photos_for_script(
    candidate_title: str,
    candidate_summary: str,
    script: dict[str, Any],
    destination_dir: Path,
    *,
    transport: Transport | None = None,
    reel_id: str = "",
) -> list[dict[str, Any]]:
    """Search, download, validate, and return index-aligned photograph assets.

    Raises ``PhotoError`` when any required scene photograph is missing or invalid.
    Never returns Remotion graphic placeholders.
    """

    scenes = _scene_list_from_script(script)
    if not scenes:
        raise PhotoError("storyboard is missing or invalid; refusing photo retrieval")
    queries = build_scene_photo_queries(
        candidate_title,
        candidate_summary,
        script,
        fact_pack=script.get("fact_pack") if isinstance(script.get("fact_pack"), dict) else None,
    )
    if len(queries) != len(scenes):
        raise PhotoError(f"query count {len(queries)} does not match scene count {len(scenes)}")
    relevance = [
        relevance_terms_from_queries(group[:3] if len(group) > 3 else group) for group in queries
    ]
    if any(not terms for terms in relevance):
        raise PhotoError("one or more scenes lack relevance terms for photograph selection")
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    (destination_dir / "photo_queries.json").write_text(
        json.dumps(
            {"queries": queries, "relevance_terms": relevance, "title": candidate_title, "scenes": len(scenes)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log = SearchLog()
    try:
        photos, log = collect_scene_photos(
            queries,
            destination_dir,
            transport=transport,
            relevance_terms=relevance,
            log=log,
        )
    except PhotoError:
        log.write(destination_dir / "image_search_log.json")
        raise
    log.write(destination_dir / "image_search_log.json")
    write_attribution_manifest(photos, destination_dir / "attribution_manifest.json", reel_id=reel_id or destination_dir.name)
    assets = assets_for_render(photos)
    problems = require_photographic_assets(assets, expected_scenes=len(scenes))
    if problems:
        raise PhotoError("photographic acceptance gate failed: " + "; ".join(problems))
    if len(assets) != len(scenes):
        raise PhotoError(f"expected {len(scenes)} photographs, got {len(assets)}")
    return assets
