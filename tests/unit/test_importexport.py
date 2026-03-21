"""Unit tests for import/export logic."""

import base64
import csv
import io
import pathlib
import typing as t
import unittest.mock
import zipfile

import django.contrib.admin
import django.contrib.auth
import django.http
import django.template.response
import django.test
import polib
import pytest

from live_translations import admin, conf, importexport, models
from live_translations.backends.po import LT_PENDING_PREFIX
from live_translations.importexport import ExportRow

if t.TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin_request(
    method: str = "get",
    path: str = "/admin/live_translations/translationentry/",
    data: dict[str, str] | None = None,
) -> django.http.HttpRequest:
    factory = django.test.RequestFactory()
    request = factory.post(path, data=data or {}) if method == "post" else factory.get(path)
    user_model = django.contrib.auth.get_user_model()
    request.user = user_model(username="admin", is_superuser=True, is_staff=True)
    return request


def _get_admin_instance() -> admin.TranslationEntryAdmin:
    return django.contrib.admin.site._registry[models.TranslationEntry]  # type: ignore[return-value]


def _parse_csv(content: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content)))


def _setup_po_files(tmp_path: pathlib.Path, translations: dict[str, dict[str, str]]) -> pathlib.Path:
    locale_dir = tmp_path / "locale"
    for lang, entries in translations.items():
        lc = locale_dir / lang / "LC_MESSAGES"
        lc.mkdir(parents=True, exist_ok=True)
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=utf-8", "Language": lang}
        for msgid, msgstr in entries.items():
            po.append(polib.POEntry(msgid=msgid, msgstr=msgstr))
        po.save(str(lc / "django.po"))
    return locale_dir


def _configure_db_backend(
    settings: "SettingsWrapper",
    locale_dir: pathlib.Path,
    languages: list[str],
) -> None:
    settings.LIVE_TRANSLATIONS = {
        "LANGUAGES": languages,
        "LOCALE_DIR": str(locale_dir),
        "BACKEND": "live_translations.backends.db.DatabaseBackend",
    }
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()


# ---------------------------------------------------------------------------
# ExportRow
# ---------------------------------------------------------------------------


class TestExportRow:
    def test_named_tuple_fields(self) -> None:
        row = ExportRow(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        assert row.language == "cs"
        assert row.msgid == "hello"
        assert row.context == ""
        assert row.msgstr == "Ahoj"
        assert row.is_active is True

    def test_sorting(self) -> None:
        rows = [
            ExportRow(language="en", msgid="hello", context="", msgstr="Hello", is_active=True),
            ExportRow(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True),
            ExportRow(language="cs", msgid="bye", context="", msgstr="Nashle", is_active=True),
        ]
        sorted_rows = sorted(rows)
        assert sorted_rows[0].language == "cs"
        assert sorted_rows[0].msgid == "bye"
        assert sorted_rows[1].language == "cs"
        assert sorted_rows[1].msgid == "hello"
        assert sorted_rows[2].language == "en"


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportCSV:
    def test_empty_queryset(self) -> None:
        qs = models.TranslationEntry.objects.qs.none()
        result = importexport.export_csv(qs, include_defaults=False, languages=None)
        rows = _parse_csv(result)
        assert rows == []
        assert "language,msgid,context,msgstr,is_active" in result

    def test_overrides_only(self) -> None:
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr="Hello!", is_active=False
        )
        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_csv(qs, include_defaults=False, languages=None)
        rows = _parse_csv(result)
        assert len(rows) == 2
        assert rows[0]["language"] == "cs"
        assert rows[0]["msgid"] == "hello"
        assert rows[0]["msgstr"] == "Ahoj"
        assert rows[0]["is_active"] == "true"
        assert rows[1]["language"] == "en"
        assert rows[1]["is_active"] == "false"

    def test_language_filter(self) -> None:
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr="Hello!", is_active=True
        )
        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_csv(qs, include_defaults=False, languages=["cs"])
        rows = _parse_csv(result)
        assert len(rows) == 1
        assert rows[0]["language"] == "cs"

    def test_include_defaults_merges_po_and_db(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {"hello": "Ahoj", "bye": "Nashle"}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        # DB override for "hello"
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Cau", is_active=True)

        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_csv(qs, include_defaults=True, languages=["cs"])
        rows = _parse_csv(result)
        assert len(rows) == 2
        by_msgid = {r["msgid"]: r for r in rows}
        # DB override wins
        assert by_msgid["hello"]["msgstr"] == "Cau"
        # PO default preserved
        assert by_msgid["bye"]["msgstr"] == "Nashle"

    def test_csv_handles_commas_and_newlines(self) -> None:
        models.TranslationEntry.objects.create(
            language="cs", msgid="complex", context="", msgstr="Hello, world\nnew line", is_active=True
        )
        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_csv(qs, include_defaults=False, languages=None)
        rows = _parse_csv(result)
        assert len(rows) == 1
        assert rows[0]["msgstr"] == "Hello, world\nnew line"


# ---------------------------------------------------------------------------
# PO Export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportPO:
    def test_active_override_replaces_default(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {"hello": "Ahoj"}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Cau", is_active=True)

        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_po(qs, language="cs")
        po = polib.pofile(result)

        entry = po.find("hello")
        assert entry is not None
        assert entry.msgstr == "Cau"
        assert "fuzzy" not in entry.flags

    def test_inactive_override_uses_ltpending_and_fuzzy(
        self, tmp_path: pathlib.Path, settings: "SettingsWrapper"
    ) -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {"hello": "Ahoj"}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Cau", is_active=False)

        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_po(qs, language="cs")
        po = polib.pofile(result)

        entry = po.find("hello")
        assert entry is not None
        # msgstr should be the PO default (active value), not the override
        assert entry.msgstr == "Ahoj"
        assert "fuzzy" in entry.flags
        # ltpending comment should contain the override value
        assert entry.comment is not None
        assert LT_PENDING_PREFIX in entry.comment
        decoded = base64.b64decode(entry.comment.split(LT_PENDING_PREFIX)[1]).decode()
        assert decoded == "Cau"

    def test_inactive_override_without_po_default(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        models.TranslationEntry.objects.create(
            language="cs", msgid="new_key", context="", msgstr="Novy", is_active=False
        )

        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_po(qs, language="cs")
        po = polib.pofile(result)

        entry = po.find("new_key")
        assert entry is not None
        assert entry.msgstr == ""  # no PO default
        assert "fuzzy" in entry.flags
        assert LT_PENDING_PREFIX in entry.comment

    def test_po_default_without_override(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {"hello": "Ahoj"}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_po(qs, language="cs")
        po = polib.pofile(result)

        entry = po.find("hello")
        assert entry is not None
        assert entry.msgstr == "Ahoj"
        assert "fuzzy" not in entry.flags

    def test_po_metadata(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        qs = models.TranslationEntry.objects.qs.none()
        result = importexport.export_po(qs, language="cs")
        po = polib.pofile(result)
        assert po.metadata["Language"] == "cs"

    def test_empty_export(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        qs = models.TranslationEntry.objects.qs.none()
        result = importexport.export_po(qs, language="cs")
        po = polib.pofile(result)
        assert len(po) == 0

    def test_msgctxt_preserved(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        models.TranslationEntry.objects.create(
            language="cs", msgid="hello", context="greeting", msgstr="Ahoj", is_active=True
        )

        qs = models.TranslationEntry.objects.qs.all()
        result = importexport.export_po(qs, language="cs")
        po = polib.pofile(result)

        entry = po.find("hello", msgctxt="greeting")
        assert entry is not None
        assert entry.msgstr == "Ahoj"


# ---------------------------------------------------------------------------
# PO Zip Export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportPOZip:
    def test_zip_contains_per_language_files(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {}, "en": {}})
        _configure_db_backend(settings, locale_dir, ["cs", "en"])

        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr="Hello!", is_active=True
        )
        qs = models.TranslationEntry.objects.qs.all()
        data = importexport.export_po_zip(qs, languages=None)
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = sorted(zf.namelist())
        assert names == ["cs.po", "en.po"]

        cs_po = polib.pofile(zf.read("cs.po").decode("utf-8"))
        assert len(cs_po) == 1
        assert cs_po[0].msgstr == "Ahoj"

    def test_zip_language_filter(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {}, "en": {}})
        _configure_db_backend(settings, locale_dir, ["cs", "en"])

        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr="Hello!", is_active=True
        )
        qs = models.TranslationEntry.objects.qs.all()
        data = importexport.export_po_zip(qs, languages=["cs"])
        zf = zipfile.ZipFile(io.BytesIO(data))
        assert zf.namelist() == ["cs.po"]


# ---------------------------------------------------------------------------
# CSV Import
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportCSV:
    def _make_csv(self, rows: list[dict[str, str]]) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["language", "msgid", "context", "msgstr", "is_active"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buf.getvalue()

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_basic_import(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        content = self._make_csv(
            [
                {"language": "cs", "msgid": "hello", "context": "", "msgstr": "Ahoj", "is_active": "true"},
                {"language": "en", "msgid": "hello", "context": "", "msgstr": "Hi", "is_active": "false"},
            ]
        )
        result = importexport.import_csv(content)
        assert result["created"] == 2
        assert result["updated"] == 0
        assert result["errors"] == []

        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert entry.msgstr == "Ahoj"
        assert entry.is_active is True

        entry_en = models.TranslationEntry.objects.qs.get(language="en", msgid="hello")
        assert entry_en.is_active is False

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_update_existing(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        content = self._make_csv(
            [
                {"language": "cs", "msgid": "hello", "context": "", "msgstr": "Cau", "is_active": "true"},
            ]
        )
        result = importexport.import_csv(content)
        assert result["created"] == 0
        assert result["updated"] == 1

        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert entry.msgstr == "Cau"

    def test_missing_columns(self) -> None:
        content = "language,msgid\ncs,hello\n"
        result = importexport.import_csv(content)
        assert result["created"] == 0
        assert result["updated"] == 0
        assert any("Missing required columns" in e for e in result["errors"])

    def test_empty_csv(self) -> None:
        result = importexport.import_csv("")
        assert result["errors"] == ["Empty or invalid CSV file"]

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_empty_msgid_skipped(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        content = self._make_csv(
            [
                {"language": "cs", "msgid": "", "context": "", "msgstr": "Ahoj", "is_active": "true"},
                {"language": "cs", "msgid": "hello", "context": "", "msgstr": "Ahoj", "is_active": "true"},
            ]
        )
        result = importexport.import_csv(content)
        assert result["created"] == 1
        assert len(result["errors"]) == 1
        assert "empty msgid" in result["errors"][0]

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_context_defaults_to_empty(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        # CSV without context column
        content = "language,msgid,msgstr\ncs,hello,Ahoj\n"
        result = importexport.import_csv(content)
        assert result["created"] == 1
        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert entry.context == ""

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_is_active_defaults_to_true(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        content = "language,msgid,msgstr\ncs,hello,Ahoj\n"
        result = importexport.import_csv(content)
        assert result["created"] == 1
        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert entry.is_active is True


# ---------------------------------------------------------------------------
# PO Import
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportPO:
    def _make_po(self, entries: list[dict[str, t.Any]], language: str = "cs") -> str:
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=UTF-8", "Language": language}
        for e in entries:
            entry = polib.POEntry(
                msgid=e["msgid"],
                msgstr=e.get("msgstr", ""),
                msgctxt=e.get("msgctxt"),
            )
            if e.get("fuzzy"):
                entry.flags.append("fuzzy")
            po.append(entry)
        return str(po)

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_basic_import(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        content = self._make_po(
            [
                {"msgid": "hello", "msgstr": "Ahoj"},
                {"msgid": "bye", "msgstr": "Nashle", "fuzzy": True},
            ]
        )
        result = importexport.import_po(content, language="cs")
        assert result["created"] == 2
        assert result["errors"] == []

        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert entry.msgstr == "Ahoj"
        assert entry.is_active is True

        entry_bye = models.TranslationEntry.objects.qs.get(language="cs", msgid="bye")
        assert entry_bye.is_active is False

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_with_msgctxt(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        content = self._make_po(
            [
                {"msgid": "hello", "msgstr": "Ahoj", "msgctxt": "greeting"},
            ]
        )
        result = importexport.import_po(content, language="cs")
        assert result["created"] == 1
        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello", context="greeting")
        assert entry.msgstr == "Ahoj"

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_language_from_metadata(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        content = self._make_po([{"msgid": "hello", "msgstr": "Ahoj"}], language="cs")
        result = importexport.import_po(content, language="")
        assert result["created"] == 1
        entry = models.TranslationEntry.objects.qs.get(msgid="hello")
        assert entry.language == "cs"

    def test_missing_language(self) -> None:
        po = polib.POFile()
        po.append(polib.POEntry(msgid="hello", msgstr="Ahoj"))
        content = str(po)
        result = importexport.import_po(content, language="")
        assert result["created"] == 0
        assert any("Language not specified" in e for e in result["errors"])

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_ltpending_takes_precedence_over_fuzzy(self, mock_backend: unittest.mock.MagicMock) -> None:
        """When a PO entry has both ltpending and fuzzy, the ltpending value is used as msgstr."""
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()

        po = polib.POFile()
        po.metadata = {"Language": "cs"}
        entry = polib.POEntry(msgid="hello", msgstr="Ahoj")  # PO default
        entry.flags.append("fuzzy")
        encoded = base64.b64encode(b"Cau").decode()
        entry.comment = f"{LT_PENDING_PREFIX}{encoded}"
        po.append(entry)

        result = importexport.import_po(str(po), language="cs")
        assert result["created"] == 1

        db_entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        # Should use the ltpending value, not msgstr
        assert db_entry.msgstr == "Cau"
        assert db_entry.is_active is False

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_fuzzy_without_ltpending(self, mock_backend: unittest.mock.MagicMock) -> None:
        """Standard fuzzy PO entry (no ltpending) uses msgstr as the value."""
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()

        po = polib.POFile()
        po.metadata = {"Language": "cs"}
        entry = polib.POEntry(msgid="hello", msgstr="Ahoj")
        entry.flags.append("fuzzy")
        po.append(entry)

        result = importexport.import_po(str(po), language="cs")
        assert result["created"] == 1

        db_entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert db_entry.msgstr == "Ahoj"
        assert db_entry.is_active is False


# ---------------------------------------------------------------------------
# PO Zip Import
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportPOZip:
    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_multi_language_zip(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            po_cs = polib.POFile()
            po_cs.metadata = {"Language": "cs"}
            po_cs.append(polib.POEntry(msgid="hello", msgstr="Ahoj"))
            zf.writestr("cs.po", str(po_cs))

            po_en = polib.POFile()
            po_en.metadata = {"Language": "en"}
            po_en.append(polib.POEntry(msgid="hello", msgstr="Hi"))
            zf.writestr("en.po", str(po_en))

        result = importexport.import_po_zip(buf.getvalue())
        assert result["created"] == 2
        assert result["errors"] == []

        assert models.TranslationEntry.objects.qs.get(language="cs", msgid="hello").msgstr == "Ahoj"
        assert models.TranslationEntry.objects.qs.get(language="en", msgid="hello").msgstr == "Hi"

    def test_invalid_zip(self) -> None:
        result = importexport.import_po_zip(b"not a zip")
        assert any("Invalid zip file" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Round-trip: export -> import
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRoundTrip:
    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_csv_round_trip(self, mock_backend: unittest.mock.MagicMock) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        models.TranslationEntry.objects.create(
            language="cs", msgid="bye", context="farewell", msgstr="Nashle", is_active=False
        )

        # Export
        qs = models.TranslationEntry.objects.qs.all()
        csv_content = importexport.export_csv(qs, include_defaults=False, languages=None)

        # Clear DB
        models.TranslationEntry.objects.qs.all().delete()
        assert models.TranslationEntry.objects.qs.count() == 0

        # Import
        result = importexport.import_csv(csv_content)
        assert result["created"] == 2
        assert result["errors"] == []

        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert entry.msgstr == "Ahoj"
        assert entry.is_active is True
        assert entry.context == ""

        entry_bye = models.TranslationEntry.objects.qs.get(language="cs", msgid="bye", context="farewell")
        assert entry_bye.msgstr == "Nashle"
        assert entry_bye.is_active is False

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_po_round_trip_with_ltpending(
        self,
        mock_backend: unittest.mock.MagicMock,
        tmp_path: pathlib.Path,
        settings: "SettingsWrapper",
    ) -> None:
        """PO round-trip: inactive entries use ltpending, import reads it back."""
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        locale_dir = _setup_po_files(tmp_path, {"cs": {"hello": "Ahoj", "bye": "Nashle"}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Cau", is_active=True)
        models.TranslationEntry.objects.create(language="cs", msgid="bye", context="", msgstr="Sbohem", is_active=False)

        # Export
        qs = models.TranslationEntry.objects.qs.all()
        po_content = importexport.export_po(qs, language="cs")

        # Clear DB
        models.TranslationEntry.objects.qs.all().delete()

        # Import
        result = importexport.import_po(po_content, language="cs")
        assert result["created"] == 2
        assert result["errors"] == []

        # Active override round-trips as the override value
        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert entry.msgstr == "Cau"
        assert entry.is_active is True

        # Inactive override round-trips via ltpending
        entry_bye = models.TranslationEntry.objects.qs.get(language="cs", msgid="bye")
        assert entry_bye.msgstr == "Sbohem"
        assert entry_bye.is_active is False

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_po_zip_round_trip(
        self,
        mock_backend: unittest.mock.MagicMock,
        tmp_path: pathlib.Path,
        settings: "SettingsWrapper",
    ) -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        locale_dir = _setup_po_files(tmp_path, {"cs": {}, "en": {}})
        _configure_db_backend(settings, locale_dir, ["cs", "en"])

        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        models.TranslationEntry.objects.create(language="en", msgid="hello", context="", msgstr="Hi", is_active=True)

        # Export
        qs = models.TranslationEntry.objects.qs.all()
        zip_data = importexport.export_po_zip(qs, languages=None)

        # Clear DB
        models.TranslationEntry.objects.qs.all().delete()

        # Import
        result = importexport.import_po_zip(zip_data)
        assert result["created"] == 2
        assert result["errors"] == []

        assert models.TranslationEntry.objects.qs.get(language="cs", msgid="hello").msgstr == "Ahoj"
        assert models.TranslationEntry.objects.qs.get(language="en", msgid="hello").msgstr == "Hi"


# ---------------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportAdminActions:
    def test_export_selected_csv_action(self) -> None:
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        ma = _get_admin_instance()
        request = _make_admin_request()
        qs = models.TranslationEntry.objects.qs.all()

        response = ma.export_selected_csv(request, qs)
        assert response["Content-Type"] == "text/csv"
        assert response["Content-Disposition"] == 'attachment; filename="translations.csv"'
        rows = _parse_csv(response.content.decode("utf-8"))
        assert len(rows) == 1
        assert rows[0]["msgid"] == "hello"

    def test_export_selected_po_zip_action(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {}})
        _configure_db_backend(settings, locale_dir, ["cs"])

        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        ma = _get_admin_instance()
        request = _make_admin_request()
        qs = models.TranslationEntry.objects.qs.all()

        response = ma.export_selected_po_zip(request, qs)
        assert response["Content-Type"] == "application/zip"
        zf = zipfile.ZipFile(io.BytesIO(response.content))
        assert "cs.po" in zf.namelist()

    def test_actions_registered(self) -> None:
        ma = _get_admin_instance()
        assert "export_selected_csv" in ma.actions
        assert "export_selected_po_zip" in ma.actions


# ---------------------------------------------------------------------------
# Admin custom URLs
# ---------------------------------------------------------------------------


class TestAdminCustomURLs:
    def test_get_urls_includes_export_and_import(self) -> None:
        ma = _get_admin_instance()
        urls = ma.get_urls()
        url_names = [u.name for u in urls if hasattr(u, "name")]
        assert "live_translations_translationentry_export" in url_names
        assert "live_translations_translationentry_import" in url_names


# ---------------------------------------------------------------------------
# Admin export view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExportView:
    def test_get_returns_template_response(self, settings: "SettingsWrapper") -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["cs", "en"], "LOCALE_DIR": "/tmp"}
        conf.get_settings.cache_clear()
        ma = _get_admin_instance()
        request = _make_admin_request()
        response = ma.export_view(request)
        assert response.status_code == 200
        assert isinstance(response, django.template.response.TemplateResponse)
        assert response.template_name == "admin/live_translations/export_form.html"
        assert response.context_data is not None
        assert response.context_data["languages"] == ["cs", "en"]

    def test_post_csv_overrides(self, settings: "SettingsWrapper") -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["cs", "en"], "LOCALE_DIR": "/tmp"}
        conf.get_settings.cache_clear()
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)

        ma = _get_admin_instance()
        request = _make_admin_request("post", data={"format": "csv", "scope": "overrides", "language": ""})
        response = ma.export_view(request)
        assert response["Content-Type"] == "text/csv"

    def test_post_po_single_language(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        locale_dir = _setup_po_files(tmp_path, {"cs": {}})
        _configure_db_backend(settings, locale_dir, ["cs", "en"])
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)

        ma = _get_admin_instance()
        request = _make_admin_request("post", data={"format": "po", "scope": "overrides", "language": "cs"})
        response = ma.export_view(request)
        assert response["Content-Type"] == "text/x-gettext-translation"
        assert 'filename="cs.po"' in response["Content-Disposition"]

    def test_post_po_all_languages_returns_zip(self, settings: "SettingsWrapper") -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["cs", "en"], "LOCALE_DIR": "/tmp"}
        conf.get_settings.cache_clear()
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)

        ma = _get_admin_instance()
        request = _make_admin_request("post", data={"format": "po", "scope": "overrides", "language": ""})
        response = ma.export_view(request)
        assert response["Content-Type"] == "application/zip"


# ---------------------------------------------------------------------------
# Admin import view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportView:
    def test_get_returns_template_response(self, settings: "SettingsWrapper") -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["cs", "en"], "LOCALE_DIR": "/tmp"}
        conf.get_settings.cache_clear()
        ma = _get_admin_instance()
        request = _make_admin_request()
        response = ma.import_view(request)
        assert response.status_code == 200
        assert isinstance(response, django.template.response.TemplateResponse)
        assert response.template_name == "admin/live_translations/import_form.html"
        assert response.context_data is not None
        assert response.context_data["languages"] == ["cs", "en"]
        assert response.context_data["result"] is None

    @unittest.mock.patch("live_translations.importexport.conf.get_backend_instance")
    def test_post_csv_import(self, mock_backend: unittest.mock.MagicMock, settings: "SettingsWrapper") -> None:
        mock_backend.return_value.bump_catalog_version = unittest.mock.MagicMock()
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["cs", "en"], "LOCALE_DIR": "/tmp"}
        conf.get_settings.cache_clear()

        csv_content = "language,msgid,context,msgstr,is_active\ncs,hello,,Ahoj,true\n"
        factory = django.test.RequestFactory()
        request = factory.post(
            "/admin/live_translations/translationentry/import/",
            data={"file": io.BytesIO(csv_content.encode("utf-8"))},
            format="multipart",
        )
        request.FILES["file"].name = "test.csv"  # type: ignore[union-attr]
        request.user = django.contrib.auth.get_user_model()(username="admin", is_superuser=True, is_staff=True)

        ma = _get_admin_instance()
        response = ma.import_view(request)
        assert response.status_code == 200
        assert isinstance(response, django.template.response.TemplateResponse)
        assert response.context_data is not None
        result = response.context_data["result"]
        assert result["created"] == 1
        assert result["errors"] == []

    def test_post_no_file(self, settings: "SettingsWrapper") -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["cs", "en"], "LOCALE_DIR": "/tmp"}
        conf.get_settings.cache_clear()

        ma = _get_admin_instance()
        request = _make_admin_request("post", data={})
        response = ma.import_view(request)
        assert response.status_code == 200
        assert isinstance(response, django.template.response.TemplateResponse)
        assert response.context_data is not None
        result = response.context_data["result"]
        assert "No file uploaded" in result["errors"][0]

    def test_post_unsupported_format(self, settings: "SettingsWrapper") -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["cs", "en"], "LOCALE_DIR": "/tmp"}
        conf.get_settings.cache_clear()

        factory = django.test.RequestFactory()
        request = factory.post(
            "/admin/live_translations/translationentry/import/",
            data={"file": io.BytesIO(b"data")},
            format="multipart",
        )
        request.FILES["file"].name = "test.json"  # type: ignore[union-attr]
        request.user = django.contrib.auth.get_user_model()(username="admin", is_superuser=True, is_staff=True)

        ma = _get_admin_instance()
        response = ma.import_view(request)
        assert response.status_code == 200
        assert isinstance(response, django.template.response.TemplateResponse)
        assert response.context_data is not None
        result = response.context_data["result"]
        assert "Unsupported file type" in result["errors"][0]


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDryRun:
    def _make_csv(self, rows: list[dict[str, str]]) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["language", "msgid", "context", "msgstr", "is_active"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buf.getvalue()

    def test_csv_dry_run_creates(self) -> None:
        content = self._make_csv(
            [{"language": "cs", "msgid": "hello", "context": "", "msgstr": "Ahoj", "is_active": "true"}]
        )
        result = importexport.import_csv(content, dry_run=True)
        assert result["dry_run"] is True
        assert result["created"] == 1
        assert result["updated"] == 0
        assert result["unchanged"] == 0
        assert len(result["preview"]) == 1  # type: ignore[arg-type]

        preview = result["preview"][0]  # type: ignore[index]
        assert preview.action == "create"
        assert preview.language == "cs"
        assert preview.msgid == "hello"
        assert preview.msgstr == "Ahoj"
        assert preview.old_msgstr == ""
        assert preview.old_is_active is None

        # No DB write
        assert models.TranslationEntry.objects.qs.count() == 0

    def test_csv_dry_run_updates(self) -> None:
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        content = self._make_csv(
            [{"language": "cs", "msgid": "hello", "context": "", "msgstr": "Cau", "is_active": "false"}]
        )
        result = importexport.import_csv(content, dry_run=True)
        assert result["dry_run"] is True
        assert result["created"] == 0
        assert result["updated"] == 1
        assert result["unchanged"] == 0
        assert len(result["preview"]) == 1  # type: ignore[arg-type]

        preview = result["preview"][0]  # type: ignore[index]
        assert preview.action == "update"
        assert preview.msgstr == "Cau"
        assert preview.old_msgstr == "Ahoj"
        assert preview.is_active is False
        assert preview.old_is_active is True

        # DB unchanged
        entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert entry.msgstr == "Ahoj"

    def test_csv_dry_run_unchanged(self) -> None:
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        content = self._make_csv(
            [{"language": "cs", "msgid": "hello", "context": "", "msgstr": "Ahoj", "is_active": "true"}]
        )
        result = importexport.import_csv(content, dry_run=True)
        assert result["created"] == 0
        assert result["updated"] == 1
        assert result["unchanged"] == 1
        assert len(result["preview"]) == 0  # type: ignore[arg-type]

    def test_csv_dry_run_mixed(self) -> None:
        models.TranslationEntry.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=True)
        content = self._make_csv(
            [
                {"language": "cs", "msgid": "hello", "context": "", "msgstr": "Cau", "is_active": "true"},
                {"language": "cs", "msgid": "bye", "context": "", "msgstr": "Nashle", "is_active": "true"},
            ]
        )
        result = importexport.import_csv(content, dry_run=True)
        assert result["created"] == 1
        assert result["updated"] == 1
        assert result["unchanged"] == 0
        assert len(result["preview"]) == 2  # type: ignore[arg-type]

        actions = {p.action for p in result["preview"]}  # type: ignore[union-attr]
        assert actions == {"create", "update"}

    def test_po_dry_run(self) -> None:
        po = polib.POFile()
        po.metadata = {"Language": "cs"}
        po.append(polib.POEntry(msgid="hello", msgstr="Ahoj"))
        result = importexport.import_po(str(po), language="cs", dry_run=True)
        assert result["dry_run"] is True
        assert result["created"] == 1
        assert models.TranslationEntry.objects.qs.count() == 0

    def test_po_zip_dry_run(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            po = polib.POFile()
            po.metadata = {"Language": "cs"}
            po.append(polib.POEntry(msgid="hello", msgstr="Ahoj"))
            zf.writestr("cs.po", str(po))
        result = importexport.import_po_zip(buf.getvalue(), dry_run=True)
        assert result["dry_run"] is True
        assert result["created"] == 1
        assert result.get("preview") is not None
        assert len(result["preview"]) == 1  # type: ignore[arg-type]
        assert models.TranslationEntry.objects.qs.count() == 0

    def test_dry_run_error_includes_flag(self) -> None:
        result = importexport.import_csv("", dry_run=True)
        assert result["dry_run"] is True
        assert result["errors"] == ["Empty or invalid CSV file"]

    def test_admin_import_view_dry_run(self, settings: "SettingsWrapper") -> None:
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["cs", "en"], "LOCALE_DIR": "/tmp"}
        conf.get_settings.cache_clear()

        csv_content = "language,msgid,context,msgstr,is_active\ncs,hello,,Ahoj,true\n"
        factory = django.test.RequestFactory()
        request = factory.post(
            "/admin/live_translations/translationentry/import/",
            data={"file": io.BytesIO(csv_content.encode("utf-8")), "dry_run": "1"},
            format="multipart",
        )
        request.FILES["file"].name = "test.csv"  # type: ignore[union-attr]
        request.user = django.contrib.auth.get_user_model()(username="admin", is_superuser=True, is_staff=True)

        ma = _get_admin_instance()
        response = ma.import_view(request)
        assert response.status_code == 200
        assert isinstance(response, django.template.response.TemplateResponse)
        assert response.context_data is not None
        result = response.context_data["result"]
        assert result["dry_run"] is True
        assert result["created"] == 1
        assert models.TranslationEntry.objects.qs.count() == 0


# ---------------------------------------------------------------------------
# Changelist template
# ---------------------------------------------------------------------------


class TestChangeListTemplate:
    def test_change_list_template_set(self) -> None:
        ma = _get_admin_instance()
        assert ma.change_list_template == "admin/live_translations/change_list.html"
