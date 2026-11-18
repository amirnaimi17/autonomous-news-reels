"""Plain text extracted from source fields.

RSS descriptions often contain markup. Narration must use the words, not the tags.
"""

import html
import re

_SCRIPT = re.compile(r"(?is)<script\b.*?>.*?</script>")
_STYLE = re.compile(r"(?is)<style\b.*?>.*?</style>")
_TAG = re.compile(r"(?s)<[^>]+>")


def plain_text(value: str) -> str:
    """Remove markup and collapse whitespace. The remaining words are kept."""

    text = _SCRIPT.sub(" ", value)
    text = _STYLE.sub(" ", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return " ".join(text.split())
