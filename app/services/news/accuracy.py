"""Catch the Deutschlandticket confirmation mistake.

Checked against the pages opened on 19 November 2026:

- Bundesregierung, "Was ist neu im November 2026": from 1 January 2027 the
  monthly price rises from 63 euro to 66.80 euro. A holder must actively
  agree only when that holder's transport company asks. If the company
  makes no contact, the new price is applied automatically.
  https://www.bundesregierung.de/breg-de/aktuelles/gesetzliche-neuregelungen-november-2026-2459132
- Deutsche Bahn, bahn.de: customers of tickets sold by DB Regio must agree
  by 30 November 2026 or the subscription ends on 31 December 2026. An order
  placed from 15 October 2026 does not need a separate agreement. Bahn tells
  readers to ask other companies about their own procedure.
  https://www.bahn.de/angebot/regio/deutschland-ticket
- BVG FAQ: a BVG subscription does not need agreement. The debit changes to
  66.80 euro on 1 January 2027 by itself.
  https://www.bvg.de/de/deutschlandticket/faqs-deutschlandticket
"""

from __future__ import annotations

_TICKET_TERMS = ("deutschlandticket", "deutschland-ticket", "دویچلندتیکت")
_CONFIRMATION_TERMS = (
    "aktiv zustimmen",
    "müssen zustimmen",
    "muss der fortführung",
    "must actively confirm",
    "must confirm",
    "باید تأیید",
    "باید تایید",
    "فعالانه تأیید",
    "فعالانه تایید",
)
_HOLDER_TERMS = ("inhaber", "abonnent", "holders", "subscribers", "دارندگان", "مشترک")
_UNIVERSAL_TERMS = (
    "alle inhaber",
    "alle abonnenten",
    "jeder abonnent",
    "all holders",
    "every holder",
    "all subscribers",
    "همه دارندگان",
    "همه مشترک",
)
_PROVIDER_LIMITS = (
    "verkehrsunternehmen",
    "deutsche bahn",
    "db regio",
    "bvg",
    "anbieter",
    "transport company",
    "ticket provider",
    "دویچه بان",
    "شرکت حمل",
    "ارائه‌دهنده",
    "ارائه دهنده",
)
_DB_TERMS = ("deutsche bahn", "db regio", "دویچه بان")
_DEADLINE_TERMS = ("30. november 2026", "30 november 2026", "۳۰ نوامبر ۲۰۲۶", "۳۰ نوامبر 2026")
_AUTOMATIC_TERMS = ("automatisch", "automatic", "خودکار")
_ALL_PROVIDERS = ("alle anbieter", "every provider", "all companies", "همه شرکت")


def mentions_deutschlandticket(text: str) -> bool:
    folded = text.casefold()
    return any(term in folded or term in text for term in _TICKET_TERMS)


def deutschlandticket_accuracy_errors(text: str) -> list[str]:
    """Return the overbroad claims. An unrelated story returns no errors."""

    if not mentions_deutschlandticket(text):
        return []
    folded = text.casefold()
    errors: list[str] = []
    limited = any(term in folded or term in text for term in _PROVIDER_LIMITS)
    confirms = any(term in folded or term in text for term in _CONFIRMATION_TERMS)
    holders = any(term in folded or term in text for term in _HOLDER_TERMS)
    universal = any(term in folded or term in text for term in _UNIVERSAL_TERMS)
    if confirms and not limited and (universal or holders):
        errors.append("confirmation depends on the ticket provider; do not say every holder must confirm")
    deadline = any(term in folded or term in text for term in _DEADLINE_TERMS)
    names_db = any(term in folded or term in text for term in _DB_TERMS)
    if deadline and not names_db:
        errors.append("the 30 November 2026 deadline is a Deutsche Bahn condition, not a rule for every provider")
    automatic = any(term in folded or term in text for term in _AUTOMATIC_TERMS)
    all_providers = any(term in folded or term in text for term in _ALL_PROVIDERS)
    if automatic and all_providers:
        errors.append("automatic continuation is not true for every provider; Deutsche Bahn asks some existing customers")
    return errors
