"""Admin interface for translation overrides."""

import typing as t

import django.contrib.admin
import django.db.models
import django.http
import django.utils.html

from live_translations import conf, history, models
from live_translations.backends import po
from live_translations.history import _get_user

__all__ = ["TranslationEntryAdmin"]

try:
    import unfold.admin

    BaseModelAdmin = unfold.admin.ModelAdmin  # type: ignore[misc]
except ImportError:
    BaseModelAdmin = django.contrib.admin.ModelAdmin  # type: ignore[misc, assignment]


def _get_po_default(obj: models.TranslationEntry) -> str:
    """Get the .po file translation for this entry's msgid/context/language."""
    settings = conf.get_settings()
    po_backend = po.POFileBackend(
        locale_dir=settings.locale_dir, domain=settings.domain
    )
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
        if len(value) > 60:
            return value[:57] + "..."
        return value

    @django.contrib.admin.display(description="Translation")
    def msgstr_short(
        self,
        obj: models.TranslationEntry,
    ) -> str:
        value = obj.msgstr
        if len(value) > 80:
            return value[:77] + "..."
        return value

    @django.contrib.admin.display(description="Default (read-only)")
    def po_default_display(
        self,
        obj: models.TranslationEntry,
    ) -> str:
        if not obj.pk:
            return "-"
        po_default = _get_po_default(obj)
        if not po_default:
            return django.utils.html.format_html(
                '<span style="color: #999;">No .po translation found</span>'
            )
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
        change: bool,
    ) -> None:
        # Capture old value before save for history tracking
        old_msgstr = ""
        if change and obj.pk:
            try:
                old_msgstr = models.TranslationEntry.objects.get(pk=obj.pk).msgstr
            except models.TranslationEntry.DoesNotExist:
                pass

        po_default = _get_po_default(obj)
        if obj.msgstr == po_default:
            # Matches .po default — no need to store an override
            if obj.pk:
                history.record_change(
                    language=obj.language,
                    msgid=obj.msgid,
                    context=obj.context,
                    action=models.TranslationHistory.Action.DELETE,
                    old_value=old_msgstr,
                    new_value=po_default,
                )
                obj.delete()
            return

        super().save_model(request, obj, form, change)

        if not change:
            history.record_change(
                language=obj.language,
                msgid=obj.msgid,
                context=obj.context,
                action=models.TranslationHistory.Action.CREATE,
                old_value=po_default,
                new_value=obj.msgstr,
            )
        elif old_msgstr != obj.msgstr:
            history.record_change(
                language=obj.language,
                msgid=obj.msgid,
                context=obj.context,
                action=models.TranslationHistory.Action.UPDATE,
                old_value=old_msgstr,
                new_value=obj.msgstr,
            )

        backend = conf.get_backend_instance()
        backend.bump_catalog_version()

    def delete_model(
        self,
        request: django.http.HttpRequest,
        obj: models.TranslationEntry,
    ) -> None:
        po_default = _get_po_default(obj)
        history.record_change(
            language=obj.language,
            msgid=obj.msgid,
            context=obj.context,
            action=models.TranslationHistory.Action.DELETE,
            old_value=obj.msgstr,
            new_value=po_default,
        )
        super().delete_model(request, obj)

        backend = conf.get_backend_instance()
        backend.bump_catalog_version()

    def delete_queryset(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> None:
        settings = conf.get_settings()
        po_backend = po.POFileBackend(
            locale_dir=settings.locale_dir, domain=settings.domain
        )

        # Materialize before deletion so we can record per-entry old values + .po defaults
        affected: list[tuple[str, str, str, str, str]] = []
        for lang, mid, ctx, msgstr in queryset.values_list(
            "language", "msgid", "context", "msgstr"
        ):
            try:
                po_entries = po_backend.get_translations(
                    msgid=mid, languages=[lang], context=ctx
                )
                po_entry = po_entries.get(lang)
                po_default = po_entry.msgstr if po_entry else ""
            except FileNotFoundError:
                po_default = ""
            affected.append((lang, mid, ctx, msgstr, po_default))

        super().delete_queryset(request, queryset)

        user = _get_user()
        models.TranslationHistory.objects.bulk_create(
            [
                models.TranslationHistory(
                    language=lang,
                    msgid=mid,
                    context=ctx,
                    action=models.TranslationHistory.Action.DELETE,
                    old_value=msgstr,
                    new_value=po_default,
                    user=user,
                )
                for lang, mid, ctx, msgstr, po_default in affected
            ]
        )

        backend = conf.get_backend_instance()
        backend.bump_catalog_version()

    @django.contrib.admin.action(description="Activate selected translations")
    def activate_translations(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> None:
        to_activate = queryset.filter(is_active=False)
        affected = list(to_activate.values_list("language", "msgid", "context"))
        updated = to_activate.update(is_active=True)
        if updated:
            history.record_bulk_action(
                entries=affected,
                action=models.TranslationHistory.Action.ACTIVATE,
                old_value="inactive",
                new_value="active",
            )
            backend = conf.get_backend_instance()
            backend.bump_catalog_version()
        self.message_user(request, f"{updated} translation(s) activated.")

    @django.contrib.admin.action(description="Deactivate selected translations")
    def deactivate_translations(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> None:
        to_deactivate = queryset.filter(is_active=True)
        affected = list(to_deactivate.values_list("language", "msgid", "context"))
        updated = to_deactivate.update(is_active=False)
        if updated:
            history.record_bulk_action(
                entries=affected,
                action=models.TranslationHistory.Action.DEACTIVATE,
                old_value="active",
                new_value="inactive",
            )
            backend = conf.get_backend_instance()
            backend.bump_catalog_version()
        self.message_user(request, f"{updated} translation(s) deactivated.")

    actions = ["activate_translations", "deactivate_translations"]
