"""Search, license-gate, and download real photographs for Reel scenes.

Discovery uses Openverse (Creative Commons catalog) and optionally Wikimedia
Commons. Google Images is not scraped. License acceptance reuses
``.cursor/skills/reel-image-generation/scripts/commons_assets.reuse_decision``.
AI image generation is never used.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
_COMMONS_ASSETS = (
    ROOT / ".cursor" / "skills" / "reel-image-generation" / "scripts" / "commons_assets.py"
)
USER_AGENT = "autonomous-news-reels/1.0 (local pilot; licensed photo retrieval)"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

Transport = Callable[[urllib.request.Request, float], bytes]


class PhotoError(RuntimeError):
    """Licensed photograph retrieval or validation failed."""


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


def load_reuse_decision():
    spec = importlib.util.spec_from_file_location("reel_commons_assets", _COMMONS_ASSETS)
    if spec is None or spec.loader is None:
        raise PhotoError("commons_assets.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.reuse_decision


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
            if exc.code == 429 and attempt + 1 < retries:
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
    """Discover CC0 / BY / BY-SA / public-domain photographs via Openverse."""

    params = {
        "q": query,
        "page_size": str(page_size),
        "license": "cc0,by,by-sa,pdm",
        "mature": "false",
    }
    url = OPENVERSE_API + "?" + urllib.parse.urlencode(params)
    payload = http_get_json(url, transport=transport, log=log)
    reuse = load_reuse_decision()
    found: list[PhotoCandidate] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        license_name = normalize_openverse_license(item.get("license"), item.get("license_version"))
        decision = reuse(license_name)
        if not decision.get("accepted"):
            if log is not None:
                log.add(action="reject_license", query=query, title=item.get("title"), license=license_name, reason=decision.get("reason"))
            continue
        download = str(item.get("url") or "").strip()
        source = str(item.get("foreign_landing_url") or item.get("detail_url") or "").strip()
        if not download or not source:
            continue
        found.append(
            PhotoCandidate(
                title=str(item.get("title") or ""),
                download_url=download,
                source_page=source,
                author=str(item.get("creator") or "unknown"),
                license_name=license_name,
                license_url=str(item.get("license_url") or ""),
                width=int(item["width"]) if item.get("width") else None,
                height=int(item["height"]) if item.get("height") else None,
                provider=str(item.get("provider") or item.get("source") or "openverse"),
                attribution=str(item.get("attribution") or ""),
            )
        )
    if log is not None:
        log.add(action="search_openverse", query=query, accepted=len(found))
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
    reuse = load_reuse_decision()
    pages = (payload.get("query") or {}).get("pages") or {}
    found: list[PhotoCandidate] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = str(info.get("mime") or "")
        if not mime.startswith("image/"):
            continue
        meta = info.get("extmetadata") or {}
        license_name = str((meta.get("LicenseShortName") or {}).get("value") or "")
        restrictions = str((meta.get("Restrictions") or {}).get("value") or "")
        decision = reuse(license_name, restrictions or None)
        if not decision.get("accepted"):
            if log is not None:
                log.add(action="reject_license", query=query, title=page.get("title"), license=license_name, reason=decision.get("reason"))
            continue
        artist_html = str((meta.get("Artist") or {}).get("value") or "")
        author = re.sub(r"<[^>]+>", "", artist_html).strip() or "unknown"
        license_url = str((meta.get("LicenseUrl") or {}).get("value") or "")
        download = str(info.get("thumburl") or info.get("url") or "").strip()
        source = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(str(page.get("title") or "").replace(" ", "_"))
        if not download:
            continue
        found.append(
            PhotoCandidate(
                title=str(page.get("title") or ""),
                download_url=download,
                source_page=source,
                author=author,
                license_name=license_name,
                license_url=license_url,
                width=int(info["thumbwidth"]) if info.get("thumbwidth") else info.get("width"),
                height=int(info["thumbheight"]) if info.get("thumbheight") else info.get("height"),
                provider="wikimedia_commons",
                attribution=f"{author} / {license_name}",
            )
        )
    if log is not None:
        log.add(action="search_commons", query=query, accepted=len(found))
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
    """Return problems if any scene lacks a usable local photograph + license metadata."""

    problems: list[str] = []
    if len(assets) < expected_scenes:
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
        if not str(asset.get("license_name") or "").strip():
            problems.append(f"scene {index + 1}: missing license_name")
        if not str(asset.get("source_url") or "").strip():
            problems.append(f"scene {index + 1}: missing source_url")
        if not str(asset.get("author") or "").strip():
            problems.append(f"scene {index + 1}: missing author")
        license_name = str(asset.get("license_name") or "").strip().casefold()
        if license_name in {"original-graphic", "remotion-graphic", "silent-fixture"}:
            problems.append(f"scene {index + 1}: graphic placeholder is not a photograph")
    return problems


def _candidate_priority(item: PhotoCandidate) -> tuple[int, int]:
    """Prefer non-Wikimedia hotlink hosts when Commons is rate-limited."""

    host = urllib.parse.urlparse(item.download_url).netloc.casefold()
    if "staticflickr.com" in host or "live.staticflickr.com" in host:
        return (0, -(item.width or 0))
    if "images.unsplash.com" in host or "images.pexels.com" in host:
        return (1, -(item.width or 0))
    if "upload.wikimedia.org" in host:
        return (5, -(item.width or 0))
    return (3, -(item.width or 0))


def _iter_candidates(candidates: list[PhotoCandidate], *, used_urls: set[str]):
    ordered = sorted(
        (item for item in candidates if item.download_url not in used_urls and item.source_page not in used_urls),
        key=_candidate_priority,
    )
    yield from ordered


def collect_scene_photos(
    scene_queries: list[list[str]],
    destination_dir: Path,
    *,
    transport: Transport | None = None,
    prefer_openverse: bool = True,
) -> tuple[list[PhotoAsset], SearchLog]:
    """Search and download one licensed photograph per scene query list."""

    log = SearchLog()
    destination_dir.mkdir(parents=True, exist_ok=True)
    assets: list[PhotoAsset] = []
    used: set[str] = set()
    for scene_index, queries in enumerate(scene_queries):
        pools: list[PhotoCandidate] = []
        for query in queries:
            if prefer_openverse:
                pools.extend(search_openverse(query, transport=transport, log=log))
            # Commons search is optional; 429s are logged and skipped.
            pools.extend(search_commons(query, transport=transport, log=log))
        chosen_asset: PhotoAsset | None = None
        last_error: Exception | None = None
        for chosen in _iter_candidates(pools, used_urls=used):
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
                if log is not None:
                    log.add(action="candidate_failed", scene=scene_index + 1, url=chosen.download_url, error=str(exc))
                continue
            attribution = chosen.attribution or f"{chosen.author} / {chosen.license_name}"
            chosen_asset = PhotoAsset(
                scene_index=scene_index,
                path=str(path.resolve()),
                source_url=chosen.source_page,
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
            used.add(chosen.source_page)
            log.add(
                action="assigned",
                scene=scene_index + 1,
                path=chosen_asset.path,
                source=chosen_asset.source_url,
                license=chosen_asset.license_name,
            )
            break
        if chosen_asset is None:
            raise PhotoError(
                f"no downloadable licensed photograph for scene {scene_index + 1}; "
                f"queries={queries}; last_error={last_error}"
            )
        assets.append(chosen_asset)
    return assets, log


def write_attribution_manifest(assets: list[PhotoAsset], path: Path, *, reel_id: str) -> Path:
    payload = {
        "reel_id": reel_id,
        "note": "Only photographs with verified reusable licenses are listed. An estimate is not a rights clearance opinion.",
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


FRUEHSTART_SCENE_QUERIES: list[list[str]] = [
    [
        "Bundesrat Berlin building",
        "Bundesrat Berlin Preußenhaus exterior",
        "Herrenhaus Berlin Bundesrat",
    ],
    [
        "euro coins close up",
        "euro coins on table",
        "euro change purse",
    ],
    [
        "pink piggy bank coins",
        "piggy bank money savings",
        "ceramic piggy bank",
    ],
    [
        "retirement calculator paperwork",
        "financial planning documents desk",
        "pension folder documents",
    ],
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
    """Build Openverse/Commons query lists dynamically for every storyboard scene."""

    scenes = _scene_list_from_script(script)
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
    topic = " ".join(title_tokens[:4]) or "Germany news"
    germany = "Germany"
    if not scenes:
        # Still require photographs even when the storyboard is empty: four topic plates.
        return [
            [f"{topic} building {germany}", f"{topic} government {germany}", f"{topic} news {germany}"],
            [f"{topic} money euro", f"{topic} coins", "euro coins savings"],
            [f"{topic} family savings", f"{topic} household", "piggy bank savings"],
            [f"{topic} documents", f"{topic} planning", "financial documents desk"],
        ]

    queries: list[list[str]] = []
    for index, scene in enumerate(scenes):
        visual = str(scene.get("visual_prompt") or "").strip()
        on_screen = str(scene.get("on_screen_text") or "").strip()
        narration = str(scene.get("narration") or "").strip()
        visual_tokens = _tokenize(visual)[:6]
        # Prefer English visual prompts for Openverse; fall back to topic tokens.
        primary = visual if re.search(r"[A-Za-z]{3,}", visual) else ""
        secondary_bits = visual_tokens or title_tokens[:3] or summary_tokens[:3]
        secondary = " ".join(secondary_bits)
        tertiary = " ".join((title_tokens[:2] + fact_tokens[:2] + summary_tokens[:2])[:5])
        scene_queries = []
        if primary:
            scene_queries.append(primary)
            scene_queries.append(f"{primary} {germany}")
        if secondary:
            scene_queries.append(f"{secondary} {germany}".strip())
        if tertiary:
            scene_queries.append(f"{tertiary} photograph")
        # Keep Persian on-screen text out of search strings; use topic anchors instead.
        if not scene_queries:
            scene_queries = [f"{topic} scene {index + 1}", f"{topic} {germany}"]
        # Deduplicate while preserving order.
        ordered = list(dict.fromkeys(item for item in scene_queries if item.strip()))
        queries.append(ordered[:4])
        del on_screen, narration  # reserved for future relevance scoring
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

    queries = build_scene_photo_queries(
        candidate_title,
        candidate_summary,
        script,
        fact_pack=script.get("fact_pack") if isinstance(script.get("fact_pack"), dict) else None,
    )
    if not queries:
        raise PhotoError("no scene photo queries could be built")
    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    photos, log = collect_scene_photos(queries, destination_dir, transport=transport)
    log.write(destination_dir / "image_search_log.json")
    (destination_dir / "photo_queries.json").write_text(
        json.dumps({"queries": queries, "title": candidate_title}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_attribution_manifest(photos, destination_dir / "attribution_manifest.json", reel_id=reel_id or destination_dir.name)
    assets = assets_for_render(photos)
    problems = require_photographic_assets(assets, expected_scenes=len(queries))
    if problems:
        raise PhotoError("photographic acceptance gate failed: " + "; ".join(problems))
    if len(assets) != len(queries):
        raise PhotoError(f"expected {len(queries)} photographs, got {len(assets)}")
    return assets
