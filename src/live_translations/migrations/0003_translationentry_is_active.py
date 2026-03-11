"""Add is_active field to TranslationEntry.

Existing rows are set to is_active=True to preserve current behavior.
New rows default to is_active=False (require explicit activation).
"""

from django.db import migrations, models


def activate_existing(apps, schema_editor):
    """Set all existing translation overrides to active so they keep working after upgrade."""
    TranslationEntry = apps.get_model("live_translations", "TranslationEntry")
    TranslationEntry.objects.all().update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [
        ("live_translations", "0002_alter_translationentry_context_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="translationentry",
            name="is_active",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Only active translations override the .po file default. "
                "Inactive translations are stored but have no effect until activated.",
                verbose_name="Active",
            ),
        ),
        migrations.RunPython(activate_existing, migrations.RunPython.noop),
    ]
