"""Tests for live_translations.plurals — CLDR plural hint lookup."""

from live_translations import conf, plurals
from live_translations.plurals import _lookup_hints


class TestLookupHints:
    def test_known_language_returns_hints(self) -> None:
        result = _lookup_hints("en", 2)
        assert result == [("one", "1"), ("other", "0, 2, 3, 4, 5, ...")]

    def test_czech_returns_four_forms(self) -> None:
        result = _lookup_hints("cs", 4)
        assert len(result) == 4
        assert result[0][0] == "one"
        assert result[1][0] == "few"
        assert result[2][0] == "many"
        assert result[3][0] == "other"

    def test_regional_variant_falls_back_to_base(self) -> None:
        result = _lookup_hints("pt-BR", 2)
        assert result == _lookup_hints("pt", 2)

    def test_underscore_regional_variant_falls_back(self) -> None:
        result = _lookup_hints("pt_BR", 2)
        assert result == _lookup_hints("pt", 2)

    def test_unknown_language_returns_empty(self) -> None:
        result = _lookup_hints("xx", 2)
        assert result == []

    def test_nplurals_less_than_cldr_truncates(self) -> None:
        # Czech CLDR has 4 entries; request only 2
        result = _lookup_hints("cs", 2)
        assert len(result) == 2
        assert result[0][0] == "one"
        assert result[1][0] == "few"

    def test_nplurals_more_than_cldr_pads(self) -> None:
        # English CLDR has 2 entries; request 4
        result = _lookup_hints("en", 4)
        assert len(result) == 4
        assert result[0] == ("one", "1")
        assert result[1] == ("other", "0, 2, 3, 4, 5, ...")
        assert result[2] == ("", "")
        assert result[3] == ("", "")

    def test_returns_new_list_each_call(self) -> None:
        a = _lookup_hints("en", 2)
        b = _lookup_hints("en", 2)
        assert a == b
        assert a is not b


class TestGetPluralHints:
    def test_returns_hints_for_configured_languages(self, settings) -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"]}
        conf.get_settings.cache_clear()
        # Mock get_nplurals since there are no real PO files in the test env
        original = conf.get_nplurals

        def mock_nplurals() -> dict[str, int]:
            return {"en": 2, "cs": 4}

        conf.get_nplurals = mock_nplurals  # type: ignore[assignment]
        try:
            result = plurals.get_plural_hints()
            assert "en" in result
            assert "cs" in result
            assert len(result["en"]) == 2
            assert len(result["cs"]) == 4
        finally:
            conf.get_nplurals = original  # type: ignore[assignment]

    def test_unknown_language_gets_empty_hints(self, settings) -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["xx"]}
        conf.get_settings.cache_clear()
        original = conf.get_nplurals

        def mock_nplurals() -> dict[str, int]:
            return {"xx": 2}

        conf.get_nplurals = mock_nplurals  # type: ignore[assignment]
        try:
            result = plurals.get_plural_hints()
            assert result["xx"] == []
        finally:
            conf.get_nplurals = original  # type: ignore[assignment]
