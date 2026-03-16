"""E2E tests for Django form field translatability.

The demo form has two kinds of fields:
- Model-derived (name, email, message): labels/help_text from model verbose_name/help_text
- Form-only (subject, newsletter): labels/help_text set directly on the form class

Both kinds must render as translatable elements (<lt-t>) when a superuser
views the page with edit mode active.  Model-derived fields are the harder case
because their gettext_lazy strings are created before AppConfig.ready() patches
the translation system.
"""

from helpers import activate_edit_mode
from playwright.sync_api import Page, expect


class TestFormFieldLabelsTranslatable:
    """Form field labels should be wrapped in <lt-t> elements."""

    def test_model_field_label_is_translatable(self, page_as_superuser: Page) -> None:
        """Label from model verbose_name (via fields = [...]) is translatable."""
        activate_edit_mode(page_as_superuser)
        label = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.name.label"]')
        expect(label).to_have_count(1, timeout=3000)
        expect(label).to_contain_text("Full name")

    def test_model_field_email_label_is_translatable(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        label = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.email.label"]')
        expect(label).to_have_count(1, timeout=3000)
        expect(label).to_contain_text("Email address")

    def test_model_field_message_label_is_translatable(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        label = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.message.label"]')
        expect(label).to_have_count(1, timeout=3000)
        expect(label).to_contain_text("Message")

    def test_form_field_label_is_translatable(self, page_as_superuser: Page) -> None:
        """Label set directly on the form class is translatable."""
        activate_edit_mode(page_as_superuser)
        label = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.subject.label"]')
        expect(label).to_have_count(1, timeout=3000)
        expect(label).to_contain_text("Subject")

    def test_form_field_newsletter_label_is_translatable(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        label = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.newsletter.label"]')
        expect(label).to_have_count(1, timeout=3000)
        expect(label).to_contain_text("Subscribe to newsletter")


class TestFormFieldHelpTextsTranslatable:
    """Form field help texts should be wrapped in <lt-t> elements."""

    def test_model_field_help_text_is_translatable(self, page_as_superuser: Page) -> None:
        """help_text from model field (via fields = [...]) is translatable."""
        activate_edit_mode(page_as_superuser)
        help_span = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.name.help"]')
        expect(help_span).to_have_count(1, timeout=3000)
        expect(help_span).to_contain_text("Your first and last name")

    def test_model_field_email_help_text_is_translatable(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        help_span = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.email.help"]')
        expect(help_span).to_have_count(1, timeout=3000)
        expect(help_span).to_contain_text("We will never share your email")

    def test_model_field_message_help_text_is_translatable(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        help_span = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.message.help"]')
        expect(help_span).to_have_count(1, timeout=3000)
        expect(help_span).to_contain_text("Tell us what you think")

    def test_form_field_help_text_is_translatable(self, page_as_superuser: Page) -> None:
        """help_text set directly on the form class is translatable."""
        activate_edit_mode(page_as_superuser)
        help_span = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.subject.help"]')
        expect(help_span).to_have_count(1, timeout=3000)
        expect(help_span).to_contain_text("A short summary of your message")

    def test_form_field_newsletter_help_text_is_translatable(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        help_span = page_as_superuser.locator('#tab-manual lt-t[data-lt-msgid="form.newsletter.help"]')
        expect(help_span).to_have_count(1, timeout=3000)
        expect(help_span).to_contain_text("Receive occasional updates by email")
