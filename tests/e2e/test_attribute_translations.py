"""E2E tests for attribute translations — data-lt-attrs, modal labels, and save behavior."""

import json

from helpers import activate_edit_mode, api_restore_po_default, check_active_toggle, open_modal, wait_for_fields_loaded
from playwright.sync_api import Page, expect


class TestAttributeTranslations:
    def test_attr_elements_have_data_lt_attrs(self, page_as_superuser: Page) -> None:
        attr_els = page_as_superuser.locator("[data-lt-attrs]")
        assert attr_els.count() >= 1
        raw = attr_els.first.get_attribute("data-lt-attrs")
        assert raw is not None
        parsed = json.loads(raw)
        assert isinstance(parsed, list)
        assert len(parsed) >= 1
        entry = parsed[0]
        assert "a" in entry  # attribute name
        assert "m" in entry  # msgid
        assert "c" in entry  # context

    def test_clicking_attr_element_opens_modal_with_attr_label(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "attrs.tooltip_trans", attr=True)
        wait_for_fields_loaded(page_as_superuser)
        label = page_as_superuser.locator(".lt-dialog__msgid-label")
        expect(label).to_contain_text("msgid")
        expect(label).to_contain_text("title")

    def test_attr_translation_save_updates_attribute(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "attrs.tooltip_trans", attr=True)
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Updated tooltip via test")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        attr_el = page_as_superuser.locator('[data-lt-attrs*="attrs.tooltip_trans"]').first
        expect(attr_el).to_have_attribute("title", "Updated tooltip via test")
        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, "attrs.tooltip_trans", ["en"])

    def test_attr_element_highlighted_with_solid_outline(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        attr_el = page_as_superuser.locator("[data-lt-attrs]").first
        outline = page_as_superuser.evaluate("el => getComputedStyle(el).outlineStyle", attr_el.element_handle())
        assert outline == "solid"

    def test_trans_tag_in_attribute_produces_marker(self, page_as_superuser: Page) -> None:
        # The <p title="{% trans 'attrs.tooltip_trans' %}"> element should have data-lt-attrs
        attr_el = page_as_superuser.locator('[data-lt-attrs*="attrs.tooltip_trans"]')
        assert attr_el.count() >= 1
        raw = attr_el.first.get_attribute("data-lt-attrs")
        assert raw is not None
        parsed = json.loads(raw)
        msgids = [e["m"] for e in parsed]
        assert "attrs.tooltip_trans" in msgids
        attrs = [e["a"] for e in parsed if e["m"] == "attrs.tooltip_trans"]
        assert "title" in attrs

    def test_gettext_in_attribute_produces_marker(self, page_as_superuser: Page) -> None:
        # The <p title="{{ tooltip_text }}"> element (from gettext()) should have data-lt-attrs
        attr_el = page_as_superuser.locator('[data-lt-attrs*="attrs.tooltip_gettext"]')
        assert attr_el.count() >= 1
        raw = attr_el.first.get_attribute("data-lt-attrs")
        assert raw is not None
        parsed = json.loads(raw)
        msgids = [e["m"] for e in parsed]
        assert "attrs.tooltip_gettext" in msgids
        attrs = [e["a"] for e in parsed if e["m"] == "attrs.tooltip_gettext"]
        assert "title" in attrs
