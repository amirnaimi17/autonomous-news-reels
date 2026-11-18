"""Canonical URL keys.

Tracking parameters and cosmetic differences must not look like a new story.
The stored key keeps the scheme so the value remains a usable URL.
"""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid"}


def canonicalize_url(url: str) -> str:
    """Return the stable identity of an article URL."""

    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"cannot canonicalize url: {url}")
    host = parsed.netloc.lower()
    if parsed.scheme == "http" and host.endswith(":80"):
        host = host[:-3]
    if parsed.scheme == "https" and host.endswith(":443"):
        host = host[:-4]
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_KEYS:
            continue
        pairs.append((lowered, value))
    pairs.sort()
    return urlunparse((parsed.scheme.lower(), host, path, "", urlencode(pairs), ""))
