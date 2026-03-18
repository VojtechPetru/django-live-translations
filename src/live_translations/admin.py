"""Admin interface for translation overrides."""

import typing as t

import django.contrib.admin
import django.contrib.auth
import django.db.models
import django.http
import django.utils.html

from live_translations import models, services

__all__ = ["ModifiedByFilter", "TranslationEntryAdmin", "TranslationHistoryAdmin"]

_MSGID_MAX_LEN = 60
_MSGSTR_MAX_LEN = 80


def _truncate(value: str, max_len: int) -> str:
    if len(value) > max_len:
        return value[: max_len - 3] + "..."
    return value


try:
    import unfold.admin  # type: ignore[missing-import]

    BaseModelAdmin = unfold.admin.ModelAdmin  # type: ignore[misc]
except ImportError:
    BaseModelAdmin = django.contrib.admin.ModelAdmin  # type: ignore[misc, assignment]


class ModifiedByFilter(django.contrib.admin.SimpleListFilter):
    """Filter TranslationEntry by the user who modified it (via TranslationHistory)."""

    title = "modified by"
    parameter_name = "modified_by"

    def lookups(
        self,
        request: django.http.HttpRequest,
        model_admin: t.Any,
    ) -> list[tuple[str, str]]:
        user_ids = (
            models.TranslationHistory.objects.filter(user__isnull=False).values_list("user", flat=True).distinct()
        )
        user_model = django.contrib.auth.get_user_model()
        users = user_model.objects.filter(pk__in=user_ids).order_by("pk")
        return [(str(u.pk), str(u)) for u in users]

    def queryset(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> django.db.models.QuerySet[models.TranslationEntry] | None:
        if self.value():
            return queryset.filter(
                django.db.models.Exists(
                    models.TranslationHistory.objects.filter(
                        user_id=self.value(),
                        msgid=django.db.models.OuterRef("msgid"),
                        context=django.db.models.OuterRef("context"),
                        language=django.db.models.OuterRef("language"),
                    )
                )
            )
        return None


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
    list_filter = ["language", "context", "is_active", ModifiedByFilter]
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
    def msgid_short(self, obj: models.TranslationEntry) -> str:
        return _truncate(obj.msgid, _MSGID_MAX_LEN)

    @django.contrib.admin.display(description="Translation")
    def msgstr_short(self, obj: models.TranslationEntry) -> str:
        return _truncate(obj.msgstr, _MSGSTR_MAX_LEN)

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


@django.contrib.admin.register(models.TranslationHistory)
class TranslationHistoryAdmin(BaseModelAdmin):  # type: ignore[misc]
    list_display = [
        "created_at",
        "action",
        "language",
        "msgid_short",
        "context",
        "user",
    ]
    list_filter = ["action", "language", "user"]
    search_fields = ["msgid", "context"]
    readonly_fields = [
        "language",
        "msgid",
        "context",
        "action",
        "old_value",
        "new_value",
        "user",
        "created_at",
    ]
    ordering = ["-created_at"]

    @django.contrib.admin.display(description="Message ID")
    def msgid_short(self, obj: models.TranslationHistory) -> str:
        return _truncate(obj.msgid, _MSGID_MAX_LEN)

    def has_add_permission(
        self,
        request: django.http.HttpRequest,
    ) -> bool:
        return False

    def has_change_permission(
        self,
        request: django.http.HttpRequest,
        obj: models.TranslationHistory | None = None,
    ) -> bool:
        return False

    def has_delete_permission(
        self,
        request: django.http.HttpRequest,
        obj: models.TranslationHistory | None = None,
    ) -> bool:
        return False
