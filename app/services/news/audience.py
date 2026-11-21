"""Cheap audience filter for Iranians living in Germany.

Keyword hits are a candidate filter. A clear household match may be ranked.
A borderline mention stays out of the automatic list until an editor approves
it with source evidence. The filter never invents a connection to Germany.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CLEAR_TERMS = (
    "deutschlandticket",
    "deutschland-ticket",
    "kindergeld",
    "bürgergeld",
    "buergergeld",
    "wohngeld",
    "elterngeld",
    "aufenthaltstitel",
    "niederlassungserlaubnis",
    "einbürgerung",
    "einbuergerung",
    "ausländerbehörde",
    "auslaenderbehoerde",
    "bamf",
    "mindestlohn",
    "krankenversicherung",
    "mietpreisbremse",
    "integrationskurs",
    "berufsanerkennung",
    "verbraucherzentrale",
    "produktrückruf",
    "produktrueckruf",
    "residence permit",
    "child benefit",
    "botschaft",
    "konsulat",
    "reisewarnung",
)
_GOVERNMENT_TERMS = (
    "bundesregierung",
    "bundestag",
    "bundesrat",
    "verordnung",
    "gesetzentwurf",
)
_EVERYDAY_TERMS = (
    "steuer",
    "rente",
    "miete",
    "zuschuss",
    "gehalt",
    "versicherung",
    "ticket",
)
_WORLD_TERMS = ("sanction", "sanktion", "election", "krieg", "war", "invasion")
_HOUSEHOLD_LINK_TERMS = ("geldtransfer", "überweisung", "uberweisung", "konto")
_PLACE_TERMS = (
    "deutschland",
    "germany",
    "berlin",
    "hamburg",
    "münchen",
    "muenchen",
    "munich",
    "köln",
    "koeln",
    "cologne",
    "frankfurt",
)


@dataclass(frozen=True)
class AudienceFilter:
    """Result of the keyword filter. `clear` can be ranked; `borderline` cannot."""

    result: str
    tier: str
    matched_terms: tuple[str, ...]


def _hit(text: str, folded: str, term: str) -> bool:
    if any("\u0600" <= char <= "\u06ff" for char in term):
        return term in text
    pattern = r"(?<![a-z0-9äöüß])" + re.escape(term) + r"(?![a-z0-9äöüß])"
    return re.search(pattern, folded) is not None


def _hits(text: str, folded: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(term for term in terms if _hit(text, folded, term))


def audience_filter(text: str) -> AudienceFilter:
    """Classify text without treating a keyword as proof of a Germany connection."""

    folded = text.casefold()
    clear = _hits(text, folded, _CLEAR_TERMS)
    if clear:
        return AudienceFilter("clear", "A", clear[:8])
    government = _hits(text, folded, _GOVERNMENT_TERMS)
    everyday = _hits(text, folded, _EVERYDAY_TERMS)
    if government and everyday:
        return AudienceFilter("clear", "B", (government + everyday)[:8])
    world = _hits(text, folded, _WORLD_TERMS)
    link = _hits(text, folded, _HOUSEHOLD_LINK_TERMS)
    if world and link:
        return AudienceFilter("borderline", "C", (world + link)[:8])
    places = _hits(text, folded, _PLACE_TERMS)
    if places:
        return AudienceFilter("borderline", "C", places[:8])
    return AudienceFilter("none", "", ())
