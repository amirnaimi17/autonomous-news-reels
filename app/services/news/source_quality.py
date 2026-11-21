"""Classify a citation as a government source, a newsroom, or anything else.

A news publisher is never treated as a government authority.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_PRIMARY_DOMAINS = (
    "bundesregierung.de",
    "bundestag.de",
    "bundesrat.de",
    "bundesverfassungsgericht.de",
    "bamf.de",
    "auswaertiges-amt.de",
    "bmas.de",
    "bundesfinanzministerium.de",
    "bundesagentur.de",
    "arbeitsagentur.de",
    "deutsche-rentenversicherung.de",
    "bundesnetzagentur.de",
    "gesetze-im-internet.de",
    "hessen.de",
)
_REPUTABLE_DOMAINS = (
    "tagesschau.de",
    "zdf.de",
    "spiegel.de",
    "zeit.de",
    "sueddeutsche.de",
    "faz.net",
    "handelsblatt.com",
    "dw.com",
    "ndr.de",
    "wdr.de",
    "mdr.de",
    "br.de",
    "swr.de",
    "rbb.de",
    "deutschlandfunk.de",
)
_RANK = {"primary": 3, "reputable": 2, "secondary": 1}


def hostname(url: str) -> str:
    host = urlsplit(url).netloc.casefold().removeprefix("www.")
    return host.split(":", 1)[0]


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def classify_source(url: str) -> str:
    """Return `primary`, `reputable`, or `secondary`."""

    host = hostname(url)
    if not host:
        return "secondary"
    if host == "bund.de" or host.endswith(".bund.de") or any(_matches(host, domain) for domain in _PRIMARY_DOMAINS):
        return "primary"
    if any(_matches(host, domain) for domain in _REPUTABLE_DOMAINS):
        return "reputable"
    return "secondary"


def best_source_quality(urls: tuple[str, ...] | list[str]) -> str:
    """Use the strongest source attached to one event. No URLs stay secondary."""

    if not urls:
        return "secondary"
    return max((classify_source(url) for url in urls), key=_RANK.__getitem__)
