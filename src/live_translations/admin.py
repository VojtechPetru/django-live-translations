"""Admin interface for translation overrides."""

import typing as t

import django.contrib.admin
import django.contrib.auth
import django.db.models
import django.http
import django.template.response
import django.urls
import django.utils.html

from live_translations import conf, importexport, models, services
from live_translations.types import PluralForms, plural_forms_from_json

if t.TYPE_CHECKING:
    from live_translations.types import LanguageCode

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
    change_list_template = "admin/live_translations/change_list.html"

    list_display = [
        "msgid_short",
        "language",
        "msgstr_short",
        "context",
        "is_active",
        "updated_at",
    ]
    list_filter = ["language", "context", "is_active", ModifiedByFilter]
    search_fields = ["msgid", "context"]
    readonly_fields = ["po_default_display"]
    ordering = ["msgid", "language"]

    fieldsets = [
        (
            "Translation",
            {
                "fields": ["po_default_display", "msgstr_forms", "is_active"],
            },
        ),
        (
            "Identification",
            {
                "fields": ["language", "msgid", "context", "msgid_plural"],
            },
        ),
    ]

    @django.contrib.admin.display(description="Message ID")
    def msgid_short(self, obj: models.TranslationEntry) -> str:
        return _truncate(obj.msgid, _MSGID_MAX_LEN)

    @django.contrib.admin.display(description="Translation")
    def msgstr_short(self, obj: models.TranslationEntry) -> str:
        forms = obj.msgstr_forms or {}
        # Show form 0 as the short representation
        text = forms.get("0", "")
        return _truncate(text, _MSGSTR_MAX_LEN)

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

        # Display all forms
        parts: list[str] = []
        for form_idx in sorted(po_default.keys()):
            label = f"Form {form_idx}: " if len(po_default) > 1 else ""
            parts.append(f"{label}{po_default[form_idx]}")

        display_text = "\n".join(parts)
        return django.utils.html.format_html(
            '<div style="padding: 8px 12px; background: #f5f5f5; border: 1px solid #e0e0e0; '
            "border-radius: 6px; font-family: monospace; font-size: 13px; color: #666; "
            'white-space: pre-wrap;">{}</div>',
            display_text,
        )

    def save_model(
        self,
        request: django.http.HttpRequest,
        obj: models.TranslationEntry,
        form: t.Any,
        change: bool,  # noqa: FBT001
    ) -> None:
        # Convert JSONField data to PluralForms
        raw_forms = obj.msgstr_forms or {}
        forms: PluralForms = plural_forms_from_json(raw_forms) if isinstance(raw_forms, dict) else {0: ""}

        services.save_translations(
            key=obj.key,
            translations={obj.language: forms},
            active_flags={obj.language: obj.is_active},
        )
        # Refresh obj so admin has the correct pk for redirects
        if not obj.pk:
            saved = models.TranslationEntry.objects.qs.for_key(obj.key).get(language=obj.language)
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

    @django.contrib.admin.action(description="Export selected as CSV")
    def export_selected_csv(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> django.http.HttpResponse:
        qs = models.TranslationEntry.objects.qs.filter(pk__in=queryset)
        csv_content = importexport.export_csv(qs, include_defaults=False, languages=None)
        response = django.http.HttpResponse(csv_content, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="translations.csv"'
        return response

    @django.contrib.admin.action(description="Export selected as PO (zip)")
    def export_selected_po_zip(
        self,
        request: django.http.HttpRequest,
        queryset: django.db.models.QuerySet[models.TranslationEntry],
    ) -> django.http.HttpResponse:
        zip_content = importexport.export_po_zip(languages=None)
        response = django.http.HttpResponse(zip_content, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="translations.zip"'
        return response

    actions = [
        "activate_translations",
        "deactivate_translations",
        "export_selected_csv",
        "export_selected_po_zip",
    ]

    def get_urls(self) -> list[django.urls.URLPattern]:
        custom_urls = [
            django.urls.path(
                "export/",
                self.admin_site.admin_view(self.export_view),
                name="live_translations_translationentry_export",
            ),
            django.urls.path(
                "import/",
                self.admin_site.admin_view(self.import_view),
                name="live_translations_translationentry_import",
            ),
        ]
        return custom_urls + super().get_urls()

    def export_view(
        self,
        request: django.http.HttpRequest,
    ) -> django.http.HttpResponse:
        settings = conf.get_settings()
        if request.method == "POST":
            fmt: t.Literal["csv", "po"] = request.POST.get("format", "csv")  # type: ignore[assignment]
            scope: t.Literal["overrides", "all"] = request.POST.get("scope", "overrides")  # type: ignore[assignment]
            language: LanguageCode = request.POST.get("language", "")
            if language and language not in settings.languages:
                return django.http.HttpResponseBadRequest("Invalid language")
            include_defaults = scope == "all"
            languages: list[LanguageCode] | None = [language] if language else None
            queryset = models.TranslationEntry.objects.qs.all()

            if fmt == "po":
                if language:
                    po_content = importexport.export_po(language=language)
                    response = django.http.HttpResponse(po_content, content_type="text/x-gettext-translation")
                    response["Content-Disposition"] = f'attachment; filename="{language}.po"'
                    return response
                zip_content = importexport.export_po_zip(languages=None)
                response = django.http.HttpResponse(zip_content, content_type="application/zip")
                response["Content-Disposition"] = 'attachment; filename="translations.zip"'
                return response

            csv_content = importexport.export_csv(queryset, include_defaults=include_defaults, languages=languages)
            response = django.http.HttpResponse(csv_content, content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="translations.csv"'
            return response

        context = {
            "title": "Export Translations",
            "languages": settings.languages,
            "has_permission": True,
            "site_header": self.admin_site.site_header,
            "site_title": self.admin_site.site_title,
        }
        return django.template.response.TemplateResponse(
            request,
            "admin/live_translations/export_form.html",
            context,
        )

    def import_view(
        self,
        request: django.http.HttpRequest,
    ) -> django.http.HttpResponse:
        settings = conf.get_settings()
        result: importexport.ImportResult | None = None

        if request.method == "POST":
            uploaded = request.FILES.get("file")
            dry_run = bool(request.POST.get("dry_run"))
            if uploaded:
                name = (uploaded.name or "").lower()
                if name.endswith(".csv"):
                    content = uploaded.read().decode("utf-8")
                    result = importexport.import_csv(content, dry_run=dry_run)
                elif name.endswith(".zip"):
                    data: bytes = uploaded.read()
                    result = importexport.import_po_zip(data, dry_run=dry_run)
                elif name.endswith(".po"):
                    content = uploaded.read().decode("utf-8")
                    language: LanguageCode = request.POST.get("language", "")
                    result = importexport.import_po(content, language=language, dry_run=dry_run)
                else:
                    result = importexport.ImportResult(
                        created=0,
                        updated=0,
                        errors=["Unsupported file type. Use .csv, .po, or .zip."],
                        dry_run=dry_run,
                    )
            else:
                result = importexport.ImportResult(created=0, updated=0, errors=["No file uploaded."], dry_run=dry_run)

        context = {
            "title": "Import Translations",
            "languages": settings.languages,
            "result": result,
            "has_permission": True,
            "site_header": self.admin_site.site_header,
            "site_title": self.admin_site.site_title,
        }
        return django.template.response.TemplateResponse(
            request,
            "admin/live_translations/import_form.html",
            context,
        )


@django.contrib.admin.register(models.TranslationHistory)
class TranslationHistoryAdmin(BaseModelAdmin):  # type: ignore[misc]
    list_display = [
        "created_at",
        "action",
        "language",
        "msgid_short",
        "context",
        "form_index",
        "user",
    ]
    list_filter = ["action", "language", "user"]
    search_fields = ["msgid", "context"]
    readonly_fields = [
        "language",
        "msgid",
        "context",
        "msgid_plural",
        "action",
        "old_value",
        "new_value",
        "form_index",
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
