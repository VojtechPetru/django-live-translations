"""Unit tests for the admin module."""

import unittest.mock

import django.contrib.admin
import django.utils.html

from live_translations import admin, models, services
from live_translations.types import MsgKey

# ---------------------------------------------------------------------------
# _truncate helper
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_string_returned_as_is(self) -> None:
        assert admin._truncate("hello", 10) == "hello"

    def test_exact_length_returned_as_is(self) -> None:
        assert admin._truncate("abcde", 5) == "abcde"

    def test_long_string_truncated_with_ellipsis(self) -> None:
        result = admin._truncate("abcdefghij", 7)
        assert result == "abcd..."
        assert len(result) == 7

    def test_empty_string(self) -> None:
        assert admin._truncate("", 10) == ""

    def test_max_len_of_three_produces_only_ellipsis(self) -> None:
        assert admin._truncate("abcdef", 3) == "..."

    def test_max_len_of_four_keeps_one_char(self) -> None:
        assert admin._truncate("abcdef", 4) == "a..."


# ---------------------------------------------------------------------------
# TranslationEntryAdmin
# ---------------------------------------------------------------------------


def _get_admin_instance() -> admin.TranslationEntryAdmin:
    return django.contrib.admin.site._registry[models.TranslationEntry]  # type: ignore[return-value]


def _make_entry(
    *,
    pk: int | None = None,
    msgid: str = "hello",
    msgstr: str = "Ahoj",
    language: str = "cs",
    context: str = "",
    is_active: bool = True,
) -> models.TranslationEntry:
    return models.TranslationEntry(
        pk=pk,
        msgid=msgid,
        msgstr=msgstr,
        language=language,
        context=context,
        is_active=is_active,
    )


class TestTranslationEntryAdminRegistration:
    def test_admin_is_registered(self) -> None:
        assert models.TranslationEntry in django.contrib.admin.site._registry

    def test_list_display(self) -> None:
        ma = _get_admin_instance()
        assert "msgid_short" in ma.list_display
        assert "msgstr_short" in ma.list_display
        assert "language" in ma.list_display
        assert "is_active" in ma.list_display

    def test_actions_registered(self) -> None:
        ma = _get_admin_instance()
        assert "activate_translations" in ma.actions
        assert "deactivate_translations" in ma.actions


class TestMsgidShort:
    def test_short_msgid(self) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(msgid="short")
        assert ma.msgid_short(obj) == "short"

    def test_long_msgid_truncated(self) -> None:
        ma = _get_admin_instance()
        long_msgid = "a" * 100
        obj = _make_entry(msgid=long_msgid)
        result = ma.msgid_short(obj)
        assert len(result) == admin._MSGID_MAX_LEN
        assert result.endswith("...")

    def test_exact_boundary_msgid(self) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(msgid="a" * admin._MSGID_MAX_LEN)
        assert ma.msgid_short(obj) == "a" * admin._MSGID_MAX_LEN


class TestMsgstrShort:
    def test_short_msgstr(self) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(msgstr="short")
        assert ma.msgstr_short(obj) == "short"

    def test_long_msgstr_truncated(self) -> None:
        ma = _get_admin_instance()
        long_msgstr = "b" * 120
        obj = _make_entry(msgstr=long_msgstr)
        result = ma.msgstr_short(obj)
        assert len(result) == admin._MSGSTR_MAX_LEN
        assert result.endswith("...")

    def test_exact_boundary_msgstr(self) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(msgstr="b" * admin._MSGSTR_MAX_LEN)
        assert ma.msgstr_short(obj) == "b" * admin._MSGSTR_MAX_LEN


class TestPoDefaultDisplay:
    def test_no_pk_returns_dash(self) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(pk=None)
        assert ma.po_default_display(obj) == "-"

    @unittest.mock.patch.object(services, "get_default", return_value="")
    def test_no_default_returns_styled_message(self, mock_get_default: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(pk=1)
        result = ma.po_default_display(obj)
        assert "No .po translation found" in str(result)
        assert "color: #999" in str(result)
        mock_get_default.assert_called_once_with(key=MsgKey("hello", ""), language="cs")

    @unittest.mock.patch.object(services, "get_default", return_value="Default translation")
    def test_with_default_returns_styled_div(self, mock_get_default: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(pk=1)
        result = ma.po_default_display(obj)
        assert "Default translation" in str(result)
        assert "monospace" in str(result)
        assert "background: #f5f5f5" in str(result)
        mock_get_default.assert_called_once_with(key=MsgKey("hello", ""), language="cs")

    @unittest.mock.patch.object(services, "get_default", return_value="<script>alert('xss')</script>")
    def test_html_is_escaped(self, mock_get_default: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(pk=1)
        result = str(ma.po_default_display(obj))
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


class TestSaveModel:
    @unittest.mock.patch.object(services, "save_translations")
    def test_save_existing_entry(self, mock_save: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(pk=42, msgid="hello", msgstr="Ahoj", language="cs", is_active=True)
        request = unittest.mock.MagicMock()
        form = unittest.mock.MagicMock()

        ma.save_model(request, obj, form, change=True)

        mock_save.assert_called_once_with(
            key=MsgKey("hello", ""),
            translations={"cs": "Ahoj"},
            active_flags={"cs": True},
        )

    @unittest.mock.patch.object(services, "save_translations")
    def test_save_new_entry_refreshes_pk(self, mock_save: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(pk=None, msgid="hello", msgstr="Ahoj", language="cs", context="ctx", is_active=False)
        request = unittest.mock.MagicMock()
        form = unittest.mock.MagicMock()

        fake_saved = unittest.mock.MagicMock(pk=99)
        with unittest.mock.patch.object(models.TranslationEntry.objects, "get", return_value=fake_saved) as mock_get:
            ma.save_model(request, obj, form, change=False)

        mock_save.assert_called_once_with(
            key=MsgKey("hello", "ctx"),
            translations={"cs": "Ahoj"},
            active_flags={"cs": False},
        )
        mock_get.assert_called_once_with(language="cs", msgid="hello", context="ctx")
        assert obj.pk == 99

    @unittest.mock.patch.object(services, "save_translations")
    def test_save_existing_entry_does_not_refresh_pk(self, mock_save: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(pk=42)
        request = unittest.mock.MagicMock()
        form = unittest.mock.MagicMock()

        with unittest.mock.patch.object(models.TranslationEntry.objects, "get") as mock_get:
            ma.save_model(request, obj, form, change=True)

        mock_get.assert_not_called()
        assert obj.pk == 42


class TestDeleteModel:
    @unittest.mock.patch.object(services, "delete_translations")
    def test_calls_service(self, mock_delete: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        obj = _make_entry(pk=1, msgid="hello", language="cs", context="ctx")
        request = unittest.mock.MagicMock()

        ma.delete_model(request, obj)

        mock_delete.assert_called_once_with(key=MsgKey("hello", "ctx"), languages=["cs"])


class TestDeleteQueryset:
    @unittest.mock.patch.object(services, "delete_entries")
    def test_calls_service(self, mock_delete: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        request = unittest.mock.MagicMock()
        queryset = unittest.mock.MagicMock()

        ma.delete_queryset(request, queryset)

        mock_delete.assert_called_once_with(queryset=queryset)


class TestActivateTranslations:
    @unittest.mock.patch.object(services, "activate_entries", return_value=3)
    def test_calls_service_and_messages_user(self, mock_activate: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        request = unittest.mock.MagicMock()
        queryset = unittest.mock.MagicMock()

        with unittest.mock.patch.object(ma, "message_user") as mock_msg:
            ma.activate_translations(request, queryset)

        mock_activate.assert_called_once_with(queryset=queryset)
        mock_msg.assert_called_once_with(request, "3 translation(s) activated.")

    @unittest.mock.patch.object(services, "activate_entries", return_value=0)
    def test_zero_updated(self, mock_activate: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        request = unittest.mock.MagicMock()
        queryset = unittest.mock.MagicMock()

        with unittest.mock.patch.object(ma, "message_user") as mock_msg:
            ma.activate_translations(request, queryset)

        mock_msg.assert_called_once_with(request, "0 translation(s) activated.")


class TestDeactivateTranslations:
    @unittest.mock.patch.object(services, "deactivate_entries", return_value=5)
    def test_calls_service_and_messages_user(self, mock_deactivate: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        request = unittest.mock.MagicMock()
        queryset = unittest.mock.MagicMock()

        with unittest.mock.patch.object(ma, "message_user") as mock_msg:
            ma.deactivate_translations(request, queryset)

        mock_deactivate.assert_called_once_with(queryset=queryset)
        mock_msg.assert_called_once_with(request, "5 translation(s) deactivated.")

    @unittest.mock.patch.object(services, "deactivate_entries", return_value=0)
    def test_zero_updated(self, mock_deactivate: unittest.mock.MagicMock) -> None:
        ma = _get_admin_instance()
        request = unittest.mock.MagicMock()
        queryset = unittest.mock.MagicMock()

        with unittest.mock.patch.object(ma, "message_user") as mock_msg:
            ma.deactivate_translations(request, queryset)

        mock_msg.assert_called_once_with(request, "0 translation(s) deactivated.")
