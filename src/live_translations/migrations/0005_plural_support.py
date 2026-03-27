"""Add plural form support: msgid_plural, msgstr_forms (JSONField), form_index.

Migrates existing msgstr TextField data into msgstr_forms JSONField as {"0": old_value}.
"""

from django.db import migrations, models


def migrate_msgstr_to_forms(apps, schema_editor):  # type: ignore[no-untyped-def]  # noqa: ANN001
    """Convert existing msgstr values to msgstr_forms JSON format."""
    TranslationEntry = apps.get_model("live_translations", "TranslationEntry")
    for entry in TranslationEntry.objects.all().iterator():
        entry.msgstr_forms = {"0": entry.msgstr}
        entry.save(update_fields=["msgstr_forms"])


def migrate_forms_to_msgstr(apps, schema_editor):  # type: ignore[no-untyped-def]  # noqa: ANN001
    """Reverse: extract form 0 back to msgstr."""
    TranslationEntry = apps.get_model("live_translations", "TranslationEntry")
    for entry in TranslationEntry.objects.all().iterator():
        forms = entry.msgstr_forms or {}
        entry.msgstr = forms.get("0", "")
        entry.save(update_fields=["msgstr"])


class Migration(migrations.Migration):
    dependencies = [
        ("live_translations", "0004_translationhistory"),
    ]

    operations = [
        # -- TranslationEntry: add new fields --
        migrations.AddField(
            model_name="translationentry",
            name="msgid_plural",
            field=models.TextField(
                blank=True,
                default="",
                help_text="The plural form of the message ID (from ngettext/npgettext). "
                "Empty for singular-only translations.",
                verbose_name="Plural Message ID",
            ),
        ),
        migrations.AddField(
            model_name="translationentry",
            name="msgstr_forms",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='JSON dict mapping form index to translated text, e.g. {"0": "apple", "1": "apples"}. '
                'Singular translations use {"0": "text"}.',
                verbose_name="Translation forms",
            ),
        ),
        # -- Data migration: msgstr -> msgstr_forms --
        migrations.RunPython(migrate_msgstr_to_forms, migrate_forms_to_msgstr),
        # -- Remove old msgstr field --
        migrations.RemoveField(
            model_name="translationentry",
            name="msgstr",
        ),
        # -- Update unique constraint to include msgid_plural --
        migrations.AlterUniqueTogether(
            name="translationentry",
            unique_together={("language", "msgid", "context", "msgid_plural")},
        ),
        # -- TranslationHistory: add new fields --
        migrations.AddField(
            model_name="translationhistory",
            name="msgid_plural",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="translationhistory",
            name="form_index",
            field=models.IntegerField(default=0),
        ),
        # -- Update history index to include msgid_plural --
        migrations.RemoveIndex(
            model_name="translationhistory",
            name="lt_history_lookup",
        ),
        migrations.AddIndex(
            model_name="translationhistory",
            index=models.Index(
                fields=["msgid", "context", "msgid_plural", "language", "-created_at"],
                name="lt_history_lookup_v2",
            ),
        ),
    ]
