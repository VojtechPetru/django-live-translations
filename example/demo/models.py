import django.db.models
from django.utils.translation import gettext_lazy as _


class Feedback(django.db.models.Model):
    """Simple model whose verbose_name / help_text are translated via gettext_lazy."""

    name = django.db.models.CharField(
        max_length=100,
        verbose_name=_("form.name.label"),
        help_text=_("form.name.help"),
    )
    email = django.db.models.EmailField(
        verbose_name=_("form.email.label"),
        help_text=_("form.email.help"),
    )
    message = django.db.models.TextField(
        verbose_name=_("form.message.label"),
        help_text=_("form.message.help"),
    )

    class Meta:
        verbose_name = _("form.feedback.verbose_name")
        verbose_name_plural = _("form.feedback.verbose_name_plural")

    def __str__(self) -> str:
        return f"{self.name} ({self.email})"
