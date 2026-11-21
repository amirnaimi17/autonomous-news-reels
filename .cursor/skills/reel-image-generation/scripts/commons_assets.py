"""Decide whether a Wikimedia Commons file is reusable in a Reel.

This does not search the web by itself. The caller passes the license fields
returned by the Commons API. Non-commercial and no-derivatives licenses are
rejected, as is any file with an extra restriction.
"""

from __future__ import annotations


def reuse_decision(license_name: str | None, restrictions: str | None = None) -> dict:
    """Return whether the license is clear enough to download."""

    name = " ".join((license_name or "").casefold().split())
    extra = " ".join((restrictions or "").split())
    if not name:
        return {"accepted": False, "reason": "missing license"}
    if extra:
        return {"accepted": False, "reason": "the file page adds a reuse restriction"}
    if any(flag in name for flag in ("noncommercial", "non-commercial", "-nc", " nc", "no derivatives", "-nd")):
        return {"accepted": False, "reason": "the license blocks commercial use or adaptation"}
    reusable = (
        name.startswith("cc0")
        or name.startswith("cc by")
        or name.startswith("public domain")
    )
    if not reusable:
        return {"accepted": False, "reason": "the license is not an approved Commons license"}
    return {"accepted": True, "reason": "license allows reuse when attribution is kept"}
