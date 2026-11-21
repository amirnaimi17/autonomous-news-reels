"""Spoken-Persian normalization. Display text is never rewritten here."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

_ARABIC_YEHS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه"})
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_ONES = [
    "صفر",
    "یک",
    "دو",
    "سه",
    "چهار",
    "پنج",
    "شش",
    "هفت",
    "هشت",
    "نه",
    "ده",
    "یازده",
    "دوازده",
    "سیزده",
    "چهارده",
    "پانزده",
    "شانزده",
    "هفده",
    "هجده",
    "نوزده",
]
_TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
_HUNDREDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"]
_ORDINALS = {
    1: "اول",
    2: "دوم",
    3: "سوم",
    4: "چهارم",
    5: "پنجم",
    6: "ششم",
    7: "هفتم",
    8: "هشتم",
    9: "نهم",
    10: "دهم",
    11: "یازدهم",
    12: "دوازدهم",
    13: "سیزدهم",
    14: "چهاردهم",
    15: "پانزدهم",
    16: "شانزدهم",
    17: "هفدهم",
    18: "هجدهم",
    19: "نوزدهم",
    20: "بیستم",
    21: "بیست و یکم",
    22: "بیست و دوم",
    23: "بیست و سوم",
    24: "بیست و چهارم",
    25: "بیست و پنجم",
    26: "بیست و ششم",
    27: "بیست و هفتم",
    28: "بیست و هشتم",
    29: "بیست و نهم",
    30: "سی‌ام",
    31: "سی و یکم",
}

_MONTHS = (
    "ژانویه|فوریه|مارس|آوریل|مه|ژوئن|ژوئیه|اوت|سپتامبر|اکتبر|نوامبر|دسامبر|"
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_MONTH_TO_FA = {
    "january": "ژانویه",
    "february": "فوریه",
    "march": "مارس",
    "april": "آوریل",
    "may": "مه",
    "june": "ژوئن",
    "july": "ژوئیه",
    "august": "اوت",
    "september": "سپتامبر",
    "october": "اکتبر",
    "november": "نوامبر",
    "december": "دسامبر",
}
_DIACRITICS = re.compile(r"[\u064b-\u0652\u0670\u200c]")


def normalize_letters(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_ARABIC_YEHS)
    text = text.replace("\u200c\u200c", "\u200c")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def integer_to_words(value: int) -> str:
    if value < 0 or value > 9999:
        raise ValueError(f"unsupported integer for spoken Persian: {value}")
    if value < 20:
        return _ONES[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        return _TENS[tens] if ones == 0 else f"{_TENS[tens]} و {_ONES[ones]}"
    if value < 1000:
        hundreds, rest = divmod(value, 100)
        return _HUNDREDS[hundreds] if rest == 0 else f"{_HUNDREDS[hundreds]} و {integer_to_words(rest)}"
    thousands, rest = divmod(value, 1000)
    head = "هزار" if thousands == 1 else f"{integer_to_words(thousands)} هزار"
    return head if rest == 0 else f"{head} و {integer_to_words(rest)}"


def _decimal_words(match: re.Match[str]) -> str:
    whole = int(match.group(1))
    frac = match.group(2)
    spoken = integer_to_words(whole)
    if len(frac) == 1:
        return f"{spoken} و {_ONES[int(frac)]}\u200cدهم"
    if len(frac) == 2:
        return f"{spoken} و {integer_to_words(int(frac))}\u200cصدم"
    return match.group(0)


def _percent_words(match: re.Match[str]) -> str:
    body = match.group(1).replace("٫", ".").replace(",", ".")
    if "." in body:
        whole, frac = body.split(".", 1)
        fake = re.match(r"(\d+)\.(\d+)", f"{int(whole)}.{frac}")
        words = _decimal_words(fake) if fake else body
    else:
        words = integer_to_words(int(body))
    return f"{words} درصد"


def _day_words(match: re.Match[str]) -> str:
    day = int(match.group(1))
    month = _MONTH_TO_FA.get(match.group(2).lower(), match.group(2))
    ordinal = _ORDINALS.get(day)
    if ordinal is None:
        return match.group(0)
    return f"{ordinal} {month}"


def segment_sentences(text: str) -> list[str]:
    """Split on sentence punctuation without dropping words."""

    cleaned = normalize_letters(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?؟])\s+", cleaned)
    return [part.strip() for part in parts if part.strip()]


def join_for_speech(sentences: list[str]) -> str:
    """Give each sentence a closing pause. This does not change the words."""

    ready = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if sentence[-1] in ":：":
            sentence = sentence[:-1].rstrip() + "."
        elif sentence[-1] not in ".!?؟":
            sentence += "."
        ready.append(sentence)
    return " ".join(ready)


def prepare_narration(text: str, dictionary: dict[str, str] | None = None) -> str:
    """Spoken news copy. The caller keeps the display string unchanged."""

    spoken = to_spoken(text, dictionary)
    spoken = re.sub(r":\s+", ". ", spoken)
    return join_for_speech(segment_sentences(spoken))


def content_tokens(text: str) -> list[str]:
    plain = _DIACRITICS.sub("", normalize_letters(text))
    plain = re.sub(r"[^\w]+", " ", plain, flags=re.UNICODE)
    return [token for token in plain.split() if token]


def uncovered_tokens(spoken: str, heard_words: list[str]) -> list[str]:
    """Script tokens the word list does not contain, even if the engine split them."""

    heard = "".join(content_tokens(" ".join(heard_words)))
    missing = []
    cursor = 0
    for token in content_tokens(spoken):
        at = heard.find(token, cursor)
        if at == -1:
            missing.append(token)
        else:
            cursor = at + len(token)
    return missing


def apply_dictionary(text: str, dictionary: dict[str, str]) -> str:
    for source, spoken in sorted(dictionary.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(re.escape(source), spoken, text, flags=re.IGNORECASE)
    return text


def load_dictionary(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError("pronunciation dictionary must be a JSON object of strings")
    return data


def to_spoken(text: str, dictionary: dict[str, str] | None = None) -> str:
    """Return narration for speech. The caller keeps the original display string."""

    spoken = normalize_letters(text).translate(_DIGIT_MAP)
    spoken = spoken.replace("٫", ".").replace("٪", "%")
    spoken = apply_dictionary(spoken, dictionary or {})
    spoken = re.sub(r"(\d+(?:\.\d+)?)\s*%", _percent_words, spoken)
    spoken = re.sub(r"(\d+)\.(\d{1,2})(?!\d)", _decimal_words, spoken)
    spoken = re.sub(rf"(\d{{1,2}})\s+({_MONTHS})", _day_words, spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\b(\d{1,4})\b", lambda m: integer_to_words(int(m.group(1))), spoken)
    return normalize_letters(spoken)
