"""Database model for storing translation overrides."""

import typing as t

import django.db.models


class TranslationEntryQuerySet(django.db.models.QuerySet["TranslationEntry"]):
    def for_language(
        self,
        language: str,
    ) -> t.Self:
        return self.filter(language=language)

    def for_msgid(
        self,
        msgid: str,
        context: str = "",
    ) -> t.Self:
        return self.filter(msgid=msgid, context=context)


class TranslationEntryManager(django.db.models.Manager["TranslationEntry"]):
    @t.override
    def get_queryset(self) -> TranslationEntryQuerySet:
        return TranslationEntryQuerySet(self.model, using=self._db)

    @property
    def qs(self) -> TranslationEntryQuerySet:
        return self.get_queryset()

    def for_language(
        self,
        language: str,
    ) -> TranslationEntryQuerySet:
        return self.qs.for_language(language)

    def for_msgid(
        self,
        msgid: str,
        context: str = "",
    ) -> TranslationEntryQuerySet:
        return self.qs.for_msgid(msgid, context=context)


class TranslationEntry(django.db.models.Model):
    """A single translation override stored in the database.

    Overrides the .po file translation for a given (msgid, context, language) triple.
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
    msgstr = django.db.models.TextField(
        "Translation",
        blank=True,
        help_text="The translated text that overrides the .po file default. "
        "If set to the same value as the .po default, this record will be removed automatically.",
    )
    updated_at = django.db.models.DateTimeField("Updated at", auto_now=True)

    objects: t.ClassVar[TranslationEntryManager] = TranslationEntryManager()  # type: ignore[assignment]

    class Meta:
        db_table = "live_translations_entry"
        unique_together = [("language", "msgid", "context")]
        ordering = ["language", "msgid"]
        verbose_name = "Translation override"
        verbose_name_plural = "Translation overrides"

    def __str__(self) -> str:
        ctx = f" [{self.context}]" if self.context else ""
        return f"{self.language}: {self.msgid}{ctx}"
