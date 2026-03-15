"""Admin interface for translation overrides."""

import typing as t

import django.contrib.admin
import django.db.models
import django.http
import django.utils.html

from live_translations import models, services

__all__ = ["TranslationEntryAdmin"]

_MSGID_MAX_LEN = 60
_MSGSTR_MAX_LEN = 80

try:
    import unfold.admin  # type: ignore[missing-import]

    BaseModelAdmin = unfold.admin.ModelAdmin  # type: ignore[misc]
except ImportError:
    BaseModelAdmin = django.contrib.admin.ModelAdmin  # type: ignore[misc, assignment]


@django.contrib.admin.register(models.TranslationEntry)
class TranslationEntryAdmin(BaseModelAdmin):  # type: ignore[misc]
    list_display = [
        "msgid_short",
        "language",
        "msgstr_short",
        "context",
        "is_active",
        "updated_at",
    ]
    list_filter = ["language", "context", "is_active"]
    search_fields = ["msgid", "msgstr", "context"]
    readonly_fields = ["po_default_display"]
    ordering = ["msgid", "language"]

    fieldsets = [
        (
            "Translation",
            {
                "fields": ["po_default_display", "msgstr", "is_active"],
            },
        ),
        (
            "Identification",
            {
                "fields": ["language", "msgid", "context"],
            },
        ),
    ]

    @django.contrib.admin.display(description="Message ID")
    def msgid_short(
        self,
        obj: models.TranslationEntry,
    ) -> str:
        value = obj.msgid
        if len(value) > _MSGID_MAX_LEN:
            return value[: _MSGID_MAX_LEN - 3] + "..."
        return value

    @django.contrib.admin.display(description="Translation")
    def msgstr_short(
        self,
        obj: models.TranslationEntry,
    ) -> str:
        value = obj.msgstr
        if len(value) > _MSGSTR_MAX_LEN:
            return value[: _MSGSTR_MAX_LEN - 3] + "..."
        return value

    @django.contrib.admin.display(description="Default (read-only)")
    def po_default_display(
        self,
        obj: models.TranslationEntry,
    ) -> str:
        if not obj.pk:
            return "-"
        po_default = services.get_default(key=obj.key, language=obj.language)
        if not po_default:
            return django.utils.html.format_html('<span style="color: #999;">{}</span>', "No .po translation found")
        return django.utils.html.format_html(
            '<div style="padding: 8px 12px; background: #f5f5f5; border: 1px solid #e0e0e0; '
            "border-radius: 6px; font-family: monospace; font-size: 13px; color: #666; "
            'white-space: pre-wrap;">{}</div>',
            po_default,
        )

    def save_model(
        self,
        request: django.http.HttpRequest,
        obj: models.TranslationEntry,
        form: t.Any,
        change: bool,  # noqa: FBT001
    ) -> None:
        services.save_translations(
            key=obj.key,
            translations={obj.language: obj.msgstr},
            active_flags={obj.language: obj.is_active},
        )
        # Refresh obj so admin has the correct pk for redirects
        if not obj.pk:
            saved = models.TranslationEntry.objects.get(language=obj.language, msgid=obj.msgid, context=obj.context)
            obj.pk = saved.pk

    def delete_model(
        self,
        request: django.http.HttpRequest,
        obj: models.TranslationEntry,
    ) -> None:
        services.delete_translations(key=obj.key, languages=[obj.language])

    def delete_queryset(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> None:
        services.delete_entries(queryset=queryset)

    @django.contrib.admin.action(description="Activate selected translations")
    def activate_translations(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> None:
        updated = services.activate_entries(queryset=queryset)
        self.message_user(request, f"{updated} translation(s) activated.")

    @django.contrib.admin.action(description="Deactivate selected translations")
    def deactivate_translations(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> None:
        updated = services.deactivate_entries(queryset=queryset)
        self.message_user(request, f"{updated} translation(s) deactivated.")

    actions = ["activate_translations", "deactivate_translations"]
