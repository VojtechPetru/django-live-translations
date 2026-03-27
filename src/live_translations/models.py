"""Database models for storing translation overrides and edit history."""

import typing as t

import django.conf
import django.db.models

from live_translations.types import LanguageCode, MsgKey

__all__ = [
    "TranslationEntry",
    "TranslationEntryManager",
    "TranslationEntryQuerySet",
    "TranslationHistory",
]


class TranslationEntryQuerySet(django.db.models.QuerySet["TranslationEntry"]):
    def for_language(
        self,
        language: "LanguageCode",
        /,
    ) -> t.Self:
        return self.filter(language=language)

    def for_languages(
        self,
        languages: list["LanguageCode"],
    ) -> t.Self:
        return self.filter(language__in=languages)

    def for_key(
        self,
        key: MsgKey,
        /,
    ) -> t.Self:
        return self.filter(msgid=key.msgid, context=key.context, msgid_plural=key.msgid_plural)

    def active(self, *, active: bool = True) -> t.Self:
        return self.filter(is_active=active)


class TranslationEntryManager(django.db.models.Manager["TranslationEntry"]):
    @t.override
    def get_queryset(self) -> TranslationEntryQuerySet:
        return TranslationEntryQuerySet(self.model, using=self._db)

    @property
    def qs(self) -> TranslationEntryQuerySet:
        return self.get_queryset()


class TranslationEntry(django.db.models.Model):
    """A single translation override stored in the database.

    Overrides the .po file translation for a given (msgid, context, msgid_plural, language) tuple.
    """

    language = django.db.models.CharField(
        "Language",
        max_length=10,
        db_index=True,
        help_text="Language code this translation applies to (e.g. cs, en, de, pl).",
    )
    msgid = django.db.models.TextField(
        "Message ID",
        help_text="The original translation key as it appears in the source code (e.g. 'hero-title').",
    )
    context = django.db.models.CharField(
        "Context",
        max_length=255,
        default="",
        blank=True,
        db_index=True,
        help_text="Optional gettext context (msgctxt). Used to disambiguate identical message IDs "
        "with different meanings. Leave blank for standard translations.",
    )
    msgid_plural = django.db.models.TextField(
        "Plural Message ID",
        default="",
        blank=True,
        help_text="The plural form of the message ID (from ngettext/npgettext). Empty for singular-only translations.",
    )
    msgstr_forms = django.db.models.JSONField(
        "Translation forms",
        default=dict,
        blank=True,
        help_text='JSON dict mapping form index to translated text, e.g. {"0": "apple", "1": "apples"}. '
        'Singular translations use {"0": "text"}.',
    )
    is_active = django.db.models.BooleanField(
        "Active",
        default=False,
        db_index=True,
        help_text="Only active translations override the .po file default. "
        "Inactive translations are stored but have no effect until activated.",
    )
    updated_at = django.db.models.DateTimeField("Updated at", auto_now=True)

    objects: t.ClassVar[TranslationEntryManager] = TranslationEntryManager()  # type: ignore[assignment]

    class Meta:
        db_table = "live_translations_entry"
        unique_together = [("language", "msgid", "context", "msgid_plural")]
        ordering = ["language", "msgid"]
        verbose_name = "Translation override"
        verbose_name_plural = "Translation overrides"

    def __str__(self) -> str:
        ctx = f" [{self.context}]" if self.context else ""
        plural = f" (plural: {self.msgid_plural[:30]})" if self.msgid_plural else ""
        return f"{self.language}: {self.msgid}{ctx}{plural}"

    @property
    def key(self) -> MsgKey:
        return MsgKey(self.msgid, self.context, self.msgid_plural)


class TranslationHistory(django.db.models.Model):
    """Audit log entry for a translation change."""

    class Action(django.db.models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"
        ACTIVATE = "activate", "Activated"
        DEACTIVATE = "deactivate", "Deactivated"

    language = django.db.models.CharField(max_length=10, db_index=True)
    msgid = django.db.models.TextField()
    context = django.db.models.CharField(max_length=255, default="", blank=True)
    msgid_plural = django.db.models.TextField(default="", blank=True)
    action = django.db.models.CharField(max_length=10, choices=Action)
    old_value = django.db.models.TextField(blank=True, default="")
    new_value = django.db.models.TextField(blank=True, default="")
    form_index = django.db.models.IntegerField(default=0)
    user = django.db.models.ForeignKey(
        django.conf.settings.AUTH_USER_MODEL,
        on_delete=django.db.models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = django.db.models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "live_translations_history"
        ordering = ["-created_at"]
        indexes = [
            django.db.models.Index(
                fields=["msgid", "context", "msgid_plural", "language", "-created_at"],
                name="lt_history_lookup_v2",
            ),
        ]
        verbose_name = "Translation history entry"
        verbose_name_plural = "Translation history entries"

    def __str__(self) -> str:
        ctx = f" [{self.context}]" if self.context else ""
        form = f" [form {self.form_index}]" if self.form_index > 0 else ""
        return f"{self.action} {self.language}: {self.msgid}{ctx}{form}"
