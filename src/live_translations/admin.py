"""Admin interface for translation overrides."""

import typing as t

from django.contrib import admin
from django.http import HttpRequest  # noqa: TC002
from django.utils.html import format_html

from .models import TranslationEntry

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc, assignment]


def _get_po_default(obj: TranslationEntry) -> str:
    """Get the .po file translation for this entry's msgid/context/language."""
    from .conf import get_conf

    conf = get_conf()

    from .backends.po import POFileBackend

    po_backend = POFileBackend(locale_dir=conf.locale_dir, domain=conf.domain)
    try:
        entries = po_backend.get_translations(
            msgid=obj.msgid,
            languages=[obj.language],
            context=obj.context,
        )
        entry = entries.get(obj.language)
        return entry.msgstr if entry else ""
    except FileNotFoundError:
        return ""


@admin.register(TranslationEntry)
class TranslationEntryAdmin(BaseModelAdmin):  # type: ignore[misc]
    list_display = ["msgid_short", "language", "msgstr_short", "context", "updated_at"]
    list_filter = ["language", "context"]
    search_fields = ["msgid", "msgstr", "context"]
    readonly_fields = ["po_default_display"]
    ordering = ["msgid", "language"]

    fieldsets = [
        (
            "Translation",
            {
                "fields": ["po_default_display", "msgstr"],
            },
        ),
        (
            "Identification",
            {
                "fields": ["language", "msgid", "context"],
            },
        ),
    ]

    @admin.display(description="Message ID")
    def msgid_short(self, obj: TranslationEntry) -> str:
        value = obj.msgid
        if len(value) > 60:
            return value[:57] + "..."
        return value

    @admin.display(description="Translation")
    def msgstr_short(self, obj: TranslationEntry) -> str:
        value = obj.msgstr
        if len(value) > 80:
            return value[:77] + "..."
        return value

    @admin.display(description="Default (read-only)")
    def po_default_display(self, obj: TranslationEntry) -> str:
        if not obj.pk:
            return "-"
        po_default = _get_po_default(obj)
        if not po_default:
            return format_html('<span style="color: #999;">No .po translation found</span>')
        return format_html(
            '<div style="padding: 8px 12px; background: #f5f5f5; border: 1px solid #e0e0e0; '
            "border-radius: 6px; font-family: monospace; font-size: 13px; color: #666; "
            'white-space: pre-wrap;">{}</div>',
            po_default,
        )

    def save_model(self, request: HttpRequest, obj: TranslationEntry, form: t.Any, change: bool) -> None:
        po_default = _get_po_default(obj)
        if obj.msgstr == po_default:
            # Matches .po default — no need to store an override
            if obj.pk:
                obj.delete()
            return
        super().save_model(request, obj, form, change)
        from .conf import get_backend_instance

        backend = get_backend_instance()
        backend.invalidate_cache([obj.language])
        backend.reload()

    def delete_model(self, request: HttpRequest, obj: TranslationEntry) -> None:
        language = obj.language
        super().delete_model(request, obj)
        from .conf import get_backend_instance

        backend = get_backend_instance()
        backend.invalidate_cache([language])
        backend.reload()
