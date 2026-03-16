import django.forms
from django.utils.translation import gettext_lazy as _

from demo.models import Feedback


class FeedbackForm(django.forms.ModelForm):
    """Demo form mixing model-derived fields with form-only fields.

    - ``name``, ``email``, ``message`` come from the model via ``fields``;
      their labels and help texts are the model's verbose_name / help_text.
    - ``subject`` and ``newsletter`` are declared directly on the form with
      explicit ``label`` and ``help_text``.
    """

    subject = django.forms.CharField(
        max_length=200,
        label=_("form.subject.label"),
        help_text=_("form.subject.help"),
    )
    newsletter = django.forms.BooleanField(
        required=False,
        label=_("form.newsletter.label"),
        help_text=_("form.newsletter.help"),
    )

    class Meta:
        model = Feedback
        fields = ["name", "email", "message"]
