"""CLDR plural category hints for the translation editing UI."""

import functools

from live_translations import conf
from live_translations.types import LanguageCode

__all__ = ["get_plural_hints"]

type PluralHint = tuple[str, str]  # (category_name, examples_str)
type PluralHints = dict[LanguageCode, list[PluralHint]]

# Static CLDR data: maps language code -> ordered list of (category, examples).
# Each list is indexed by gettext form index.
# Source: CLDR v45 supplemental/language_plural_rules.html
#
# The nplurals=4 variants for cs/sk/pl/... follow Django's own PO headers
# which use the CLDR-influenced rule including a fractional-numbers form.
_CLDR_PLURAL_FORMS: PluralHints = {
    # --- nplurals=1: other ---
    "ja": [("other", "0, 1, 2, ...")],
    "ko": [("other", "0, 1, 2, ...")],
    "zh": [("other", "0, 1, 2, ...")],
    "vi": [("other", "0, 1, 2, ...")],
    "th": [("other", "0, 1, 2, ...")],
    "id": [("other", "0, 1, 2, ...")],
    "ms": [("other", "0, 1, 2, ...")],
    "tr": [("other", "0, 1, 2, ...")],
    "ka": [("other", "0, 1, 2, ...")],
    # --- nplurals=2: one, other ---
    "en": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "de": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "nl": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "es": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "it": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "pt": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "sv": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "da": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "nb": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "nn": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "fi": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "el": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "he": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "hu": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "et": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "bg": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "ca": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "eu": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "gl": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "af": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "sq": [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")],
    "hy": [("one", "0, 1"), ("other", "2, 3, 4, 5, ...")],
    "fr": [("one", "0, 1"), ("other", "2, 3, 4, 5, ...")],
    "hi": [("one", "0, 1"), ("other", "2, 3, 4, 5, ...")],
    "bn": [("one", "0, 1"), ("other", "2, 3, 4, 5, ...")],
    "fa": [("one", "0, 1"), ("other", "2, 3, 4, 5, ...")],
    # --- nplurals=3 (one/few/other) ---
    "ro": [("one", "1"), ("few", "0, 2\u201319, 101\u2013119, ..."), ("other", "20\u2013100, 120\u2013200, ...")],
    "lt": [("one", "1, 21, 31, ..."), ("few", "2\u20139, 22\u201329, ..."), ("other", "0, 10\u201320, 30, ...")],
    # --- nplurals=3 (one/two/other) ---
    "mk": [("one", "1, 21, 31, ..."), ("two", "2, 22, 32, ..."), ("other", "0, 3\u201320, 23\u201330, ...")],
    # --- nplurals=4 (one/few/many/other) — Django CLDR-influenced ---
    "cs": [
        ("one", "1"),
        ("few", "2, 3, 4"),
        ("many", "0.5, 1.5, ..."),
        ("other", "0, 5, 6, 7, ..."),
    ],
    "sk": [
        ("one", "1"),
        ("few", "2, 3, 4"),
        ("many", "0.5, 1.5, ..."),
        ("other", "0, 5, 6, 7, ..."),
    ],
    "pl": [
        ("one", "1"),
        ("few", "2\u20134, 22\u201324, ..."),
        ("many", "0, 5\u201321, 25\u201331, ..."),
        ("other", "0.5, 1.5, ..."),
    ],
    "hr": [
        ("one", "1, 21, 31, ..."),
        ("few", "2\u20134, 22\u201324, ..."),
        ("many", "0.5, 1.5, ..."),
        ("other", "0, 5\u201320, 25\u201330, ..."),
    ],
    "sr": [
        ("one", "1, 21, 31, ..."),
        ("few", "2\u20134, 22\u201324, ..."),
        ("many", "0.5, 1.5, ..."),
        ("other", "0, 5\u201320, 25\u201330, ..."),
    ],
    "bs": [
        ("one", "1, 21, 31, ..."),
        ("few", "2\u20134, 22\u201324, ..."),
        ("many", "0.5, 1.5, ..."),
        ("other", "0, 5\u201320, 25\u201330, ..."),
    ],
    "uk": [
        ("one", "1, 21, 31, ..."),
        ("few", "2\u20134, 22\u201324, ..."),
        ("many", "0, 5\u201320, 25\u201330, ..."),
        ("other", "0.5, 1.5, ..."),
    ],
    "ru": [
        ("one", "1, 21, 31, ..."),
        ("few", "2\u20134, 22\u201324, ..."),
        ("many", "0, 5\u201320, 25\u201330, ..."),
        ("other", "0.5, 1.5, ..."),
    ],
    "be": [
        ("one", "1, 21, 31, ..."),
        ("few", "2\u20134, 22\u201324, ..."),
        ("many", "0, 5\u201320, 25\u201330, ..."),
        ("other", "0.5, 1.5, ..."),
    ],
    # --- nplurals=4 (one/two/few/other) ---
    "sl": [
        ("one", "1, 101, 201, ..."),
        ("two", "2, 102, 202, ..."),
        ("few", "3, 4, 103, ..."),
        ("other", "0, 5\u2013100, 105\u2013200, ..."),
    ],
    "ga": [("one", "1"), ("two", "2"), ("few", "3\u20136"), ("other", "7\u201310, 11, ...")],
    # --- nplurals=6 ---
    "ar": [
        ("zero", "0"),
        ("one", "1"),
        ("two", "2"),
        ("few", "3\u201310, 103\u2013110, ..."),
        ("many", "11\u201399, 111\u2013199, ..."),
        ("other", "100\u2013102, 200\u2013202, ..."),
    ],
    # --- nplurals=3 (zero/one/other) ---
    "lv": [("zero", "0"), ("one", "1, 21, 31, ..."), ("other", "2\u201320, 22\u201330, ...")],
}


def _lookup_hints(lang: "LanguageCode", nplurals: int) -> list[PluralHint]:
    """Look up CLDR hints for a language, with regional fallback and nplurals validation."""
    lower = lang.lower().replace("_", "-")
    cldr = _CLDR_PLURAL_FORMS.get(lower) or _CLDR_PLURAL_FORMS.get(lower.split("-")[0])

    if cldr is None:
        return []

    if len(cldr) == nplurals:
        return list(cldr)

    # Mismatch: truncate or pad
    if len(cldr) > nplurals:
        return list(cldr[:nplurals])

    return list(cldr) + [("", "")] * (nplurals - len(cldr))


@functools.cache
def get_plural_hints() -> PluralHints:
    """Build plural hints for each configured language.

    Returns ``{lang: [(category, examples), ...]}`` where the list is indexed by form index.
    Falls back gracefully: unknown languages get no hints (empty list).
    """
    settings = conf.get_settings()
    nplurals = conf.get_nplurals()
    result: PluralHints = {}

    for lang in settings.languages:
        n = nplurals.get(lang, 2)
        result[lang] = _lookup_hints(lang, n)

    return result
