"""Comprehensive tests for MarkerResolver.

Tests cover: basic text, attribute contexts, rawtext elements, comments,
HTML edge cases, malformed HTML (xfail), and performance.
"""

import json
import re

import pytest

from live_translations import resolver as resolver_mod, strings


# ── Fixtures ───────────────────────────────────────────────────


def _html_escape(s: str) -> str:
    """Minimal HTML escape matching django.utils.html.escape behavior."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


@pytest.fixture()
def resolver() -> resolver_mod.MarkerResolver:
    return resolver_mod.MarkerResolver(
        marker_re=strings.MARKER_RE,
        marker_start=strings.MARKER_START,
        b64_decode=strings._b64d,
        html_escape=_html_escape,
    )


def _marker(
    content: str,
    msgid: str,
    context: str = "",
    *,
    escaped: bool = False,
) -> str:
    """Build a raw marker string (without Django's mark_safe)."""
    flag = "e" if escaped else "r"
    return (
        strings.MARKER_START
        + strings._b64e(msgid)
        + "\x01"
        + strings._b64e(context)
        + "\x01"
        + strings._b64e(content)
        + "\x01"
        + flag
        + "\x03"
    )


def _span(
    content: str,
    msgid: str,
    context: str = "",
) -> str:
    """Build the expected <span> output for a text-content marker."""
    return (
        f'<span class="lt-translatable" data-lt-msgid="{_html_escape(msgid)}"'
        f' data-lt-context="{_html_escape(context)}">{content}</span>'
    )


# ── No markers ─────────────────────────────────────────────────


class TestResolverNoMarkers:
    def test_plain_text(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        assert resolver.resolve("Hello world") == "Hello world"

    def test_html_without_markers(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = '<div class="foo"><p>Hello</p></div>'
        assert resolver.resolve(html) == html

    def test_empty_string(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        assert resolver.resolve("") == ""

    def test_whitespace_only(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        assert resolver.resolve("   \n\t  ") == "   \n\t  "

    def test_stray_marker_start_char(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """A lone \\x02 that isn't followed by valid marker data should pass through unchanged."""
        html = "<p>before \x02 after</p>"
        assert resolver.resolve(html) == html

    def test_partial_marker_format(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """\\x02 followed by some separators but not a valid full marker."""
        html = "<p>\x02notbase64\x01also\x01bad\x01x\x03</p>"
        assert resolver.resolve(html) == html

    def test_marker_start_in_attribute(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """A stray \\x02 inside an attribute value should pass through."""
        html = '<p title="some \x02 value">text</p>'
        assert resolver.resolve(html) == html

    def test_multiple_stray_marker_chars(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Multiple \\x02 chars that aren't markers should all pass through."""
        html = "<p>\x02 and \x02 and \x02</p>"
        assert resolver.resolve(html) == html


# ── Text content markers ──────────────────────────────────────


class TestResolverTextContent:
    def test_single_marker_in_text(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<p>{_marker('Hello', 'Hello')}</p>"
        expected = f"<p>{_span('Hello', 'Hello')}</p>"
        assert resolver.resolve(html) == expected

    def test_raw_flag_escapes_html(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Flag 'r' means raw content that needs HTML escaping."""
        html = f"<p>{_marker('<b>bold</b>', 'bold_msg')}</p>"
        expected = f"<p>{_span('&lt;b&gt;bold&lt;/b&gt;', 'bold_msg')}</p>"
        assert resolver.resolve(html) == expected

    def test_escaped_flag_no_double_escape(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Flag 'e' means content is already escaped — emit as-is."""
        html = f"<p>{_marker('&lt;b&gt;bold&lt;/b&gt;', 'bold_msg', escaped=True)}</p>"
        expected = f"<p>{_span('&lt;b&gt;bold&lt;/b&gt;', 'bold_msg')}</p>"
        assert resolver.resolve(html) == expected

    def test_marker_with_context(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<p>{_marker('Greeting', 'Hello', 'welcome_page')}</p>"
        expected = f"<p>{_span('Greeting', 'Hello', 'welcome_page')}</p>"
        assert resolver.resolve(html) == expected

    def test_multiple_markers_in_text(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        m1 = _marker("Hello", "Hello")
        m2 = _marker("World", "World")
        html = f"<p>{m1} {m2}</p>"
        expected = f"<p>{_span('Hello', 'Hello')} {_span('World', 'World')}</p>"
        assert resolver.resolve(html) == expected

    def test_marker_between_elements(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<div>{_marker('Hi', 'Hi')}</div><span>other</span>"
        expected = f"<div>{_span('Hi', 'Hi')}</div><span>other</span>"
        assert resolver.resolve(html) == expected

    def test_unicode_content(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<p>{_marker('Ahoj', 'Hello')}</p>"
        expected = f"<p>{_span('Ahoj', 'Hello')}</p>"
        assert resolver.resolve(html) == expected

    def test_cjk_content(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<p>{_marker('\u4f60\u597d', 'Hello')}</p>"
        expected = f"<p>{_span('\u4f60\u597d', 'Hello')}</p>"
        assert resolver.resolve(html) == expected

    def test_emoji_content(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<p>{_marker('Hello \U0001f44b', 'wave')}</p>"
        expected = f"<p>{_span('Hello \U0001f44b', 'wave')}</p>"
        assert resolver.resolve(html) == expected

    def test_marker_at_top_level(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Marker not inside any tag — still text content."""
        html = _marker("bare", "bare")
        expected = _span("bare", "bare")
        assert resolver.resolve(html) == expected

    def test_special_chars_in_msgid_escaped(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """msgid with <, >, " must be escaped in data-lt-msgid attribute."""
        html = f"<p>{_marker('translated', 'say "hello" <world>')}</p>"
        expected = f"<p>{_span('translated', 'say "hello" <world>')}</p>"
        assert resolver.resolve(html) == expected


# ── Attribute markers ──────────────────────────────────────────


class TestResolverAttributes:
    def test_marker_in_double_quoted_attr(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f'<p title="{_marker("Tooltip", "Tooltip")}">text</p>'
        result = resolver.resolve(html)
        # Should contain plain text in the attr, not a span
        assert "<span" not in result.split(">")[0]  # no span inside the <p ...> tag
        assert "Tooltip" in result
        assert "data-lt-attrs=" in result

    def test_marker_in_single_quoted_attr(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<p title='{_marker('Tooltip', 'Tooltip')}'>text</p>"
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result
        assert "Tooltip" in result

    def test_data_lt_attrs_json_structure(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f'<p title="{_marker("Tip", "Tip")}">text</p>'
        result = resolver.resolve(html)
        # Extract data-lt-attrs value
        match = re.search(r"data-lt-attrs='([^']*)'", result)
        assert match is not None
        attrs_json = match.group(1)
        parsed = json.loads(attrs_json)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["a"] == "title"
        assert parsed[0]["m"] == "Tip"
        assert parsed[0]["c"] == ""

    def test_multiple_attrs_same_element(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f'<img alt="{_marker("Alt text", "alt_msg")}" title="{_marker("Title text", "title_msg")}"/>'
        result = resolver.resolve(html)
        match = re.search(r"data-lt-attrs='([^']*)'", result)
        assert match is not None
        parsed = json.loads(match.group(1))
        assert len(parsed) == 2
        attr_names = {entry["a"] for entry in parsed}
        assert attr_names == {"alt", "title"}

    def test_marker_in_placeholder(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f'<input placeholder="{_marker("Enter name", "placeholder_msg")}"/>'
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result
        assert "Enter name" in result

    def test_marker_in_value(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f'<input value="{_marker("Submit", "submit_btn")}"/>'
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result

    def test_special_chars_in_msgid_attr_context(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Single quote in msgid must be escaped in data-lt-attrs (which uses single-quote delimiters)."""
        html = f'<p title="{_marker("It works", "it's a test")}">text</p>'
        result = resolver.resolve(html)
        # The data-lt-attrs value must not break
        match = re.search(r"data-lt-attrs='([^']*(?:&#39;[^']*)*)'", result)
        assert match is not None
        # Replace &#39; back to ' for JSON parsing
        raw_json = match.group(1).replace("&#39;", "'")
        parsed = json.loads(raw_json)
        assert parsed[0]["m"] == "it's a test"

    def test_mixed_text_and_attr_markers_same_element(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """An element with both text content marker and attribute marker."""
        html = f'<p title="{_marker("Tip", "Tip")}">{_marker("Hello", "Hello")}</p>'
        result = resolver.resolve(html)
        # Should have both a span (for text) and data-lt-attrs (for attribute)
        assert '<span class="lt-translatable"' in result
        assert "data-lt-attrs=" in result

    def test_data_lt_attrs_injected_before_closing_angle(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """data-lt-attrs should appear within the opening tag, before >."""
        html = f'<p title="{_marker("Tip", "Tip")}">text</p>'
        result = resolver.resolve(html)
        # Find the first > — data-lt-attrs should be before it
        first_gt = result.index(">")
        assert "data-lt-attrs=" in result[:first_gt]


# ── Rawtext elements ───────────────────────────────────────────


class TestResolverRawtext:
    def test_marker_in_script(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<script>{_marker('alert', 'alert')}</script>"
        result = resolver.resolve(html)
        assert "<span" not in result
        assert "data-lt-attrs" not in result
        assert "alert" in result

    def test_marker_in_style(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<style>{_marker('color:red', 'style_msg')}</style>"
        result = resolver.resolve(html)
        assert "<span" not in result

    def test_marker_in_textarea(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<textarea>{_marker('Default text', 'textarea_msg')}</textarea>"
        result = resolver.resolve(html)
        assert "<span" not in result

    def test_marker_in_title_element(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """<title> is a rawtext element — marker should emit plain text only."""
        html = f"<title>{_marker('My Page', 'page_title')}</title>"
        result = resolver.resolve(html)
        assert "<span" not in result
        assert "My Page" in result

    def test_marker_after_script_resumes_normal(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """After closing </script>, markers should be resolved normally."""
        html = f"<script>var x=1;</script><p>{_marker('Hello', 'Hello')}</p>"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result


# ── Comments ───────────────────────────────────────────────────


class TestResolverComments:
    def test_marker_in_comment(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<!-- {_marker('Hidden', 'Hidden')} -->"
        result = resolver.resolve(html)
        assert "<span" not in result
        assert "data-lt-attrs" not in result

    def test_marker_after_comment_resumes(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<!-- comment --><p>{_marker('Visible', 'Visible')}</p>"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result


# ── Edge cases (valid HTML) ────────────────────────────────────


class TestResolverEdgeCases:
    def test_self_closing_br(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<br/>{_marker('After break', 'after_br')}"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_self_closing_img(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f'<img src="x.png" />{_marker("Caption", "caption")}'
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_doctype_before_marker(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<!DOCTYPE html><html><body>{_marker('Hello', 'Hello')}</body></html>"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result
        assert "<!DOCTYPE html>" in result

    def test_boolean_attribute(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<input disabled>{_marker('After input', 'after_input')}"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_boolean_attribute_before_quoted_attr(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = (
            f'<input disabled type="text" placeholder="{_marker("Name", "name_ph")}"/>'
        )
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result

    def test_empty_marker_content(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<p>{_marker('', 'empty_msg')}</p>"
        result = resolver.resolve(html)
        assert 'data-lt-msgid="empty_msg"' in result

    def test_consecutive_markers(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        m1 = _marker("A", "A")
        m2 = _marker("B", "B")
        html = f"<p>{m1}{m2}</p>"
        result = resolver.resolve(html)
        assert result.count('<span class="lt-translatable"') == 2

    def test_marker_immediately_after_tag_close(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<div></div>{_marker('After', 'After')}"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_deeply_nested_elements(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f"<div><ul><li><a href='#'>{_marker('Link', 'link_text')}</a></li></ul></div>"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_marker_in_attr_of_self_closing_tag(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f'<img alt="{_marker("Photo", "photo_alt")}" />'
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result

    def test_tag_with_many_attributes(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = (
            f'<a href="/page" class="link" id="main-link" '
            f'data-value="42" title="{_marker("Go", "go_title")}">click</a>'
        )
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result

    def test_multiline_tag(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        html = f'<p\n  class="intro"\n  title="{_marker("Intro", "intro_title")}"\n>text</p>'
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result

    def test_marker_in_closing_tag_area(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Marker after a closing tag is in text context."""
        html = f"</div>{_marker('After close', 'After close')}"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result


# ── Malformed HTML (expected failures) ─────────────────────────


class TestResolverMalformedHTML:
    def test_unquoted_attribute_value(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Marker in an unquoted attribute value should still produce data-lt-attrs."""
        html = f"<div title={_marker('Tip', 'Tip')}>text</div>"
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result

    def test_missing_closing_quote(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Missing closing double-quote should not corrupt subsequent markers."""
        html = f'<div title="unclosed><p>{_marker("Hello", "Hello")}</p>'
        result = resolver.resolve(html)
        # The marker after the malformed tag should still be resolved as text
        assert '<span class="lt-translatable"' in result

    def test_quote_type_mismatch(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Opening with " but closing with ' should not corrupt the parser."""
        html = f"<div title=\"foo'><p>{_marker('Hello', 'Hello')}</p>"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_unclosed_tag(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Unclosed tag — parser recovers at the next '<'."""
        html = f"<div><p{_marker('Hello', 'Hello')}<span>text</span></div>"
        # The marker is inside an unclosed <p tag, so it's in TAG_ATTRS context.
        # It won't be wrapped in a span. The important thing is no crash.
        result = resolver.resolve(html)
        assert isinstance(result, str)

    def test_nested_quotes_in_attr(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Single quotes inside double-quoted attribute — should work fine."""
        html = f"""<div title="he said 'hi'">{_marker("Hello", "Hello")}</div>"""
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_angle_bracket_in_double_quoted_attr(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """< and > inside a double-quoted attribute value — parser should stay in _S_ATTR_DQ."""
        html = f'<div title="a > b < c">{_marker("Hello", "Hello")}</div>'
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_no_whitespace_between_attrs(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Attributes jammed together without whitespace — e.g. class="a"title="b"."""
        html = f'<div class="a"title="{_marker("Tip", "Tip")}">text</div>'
        result = resolver.resolve(html)
        assert "data-lt-attrs=" in result

    def test_broken_comment_syntax(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """<!- not a real comment --> should not enter comment state."""
        html = f"<!- not a comment --><p>{_marker('Hello', 'Hello')}</p>"
        result = resolver.resolve(html)
        # The parser sees '<!' and enters TAG_ATTRS, then sees '>' somewhere.
        # After that, the marker should be in text context.
        assert isinstance(result, str)

    def test_extra_gt_in_text(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """A bare > in text content should be harmless."""
        html = f"<p>2 > 1 and {_marker('Hello', 'Hello')}</p>"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_lt_in_text(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """A bare < in text that doesn't start a valid tag."""
        html = f"<p>1 < 2 and {_marker('Hello', 'Hello')}</p>"
        result = resolver.resolve(html)
        # The < triggers _S_TAG_OPEN, but '2' doesn't start a valid tag name
        # (it's a digit, not alpha or /). The parser will handle this.
        assert isinstance(result, str)

    def test_script_with_angle_brackets(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Script content with HTML-like content should not confuse rawtext detection."""
        html = f"<script>if (a < b && c > d) {{}}</script><p>{_marker('Hello', 'Hello')}</p>"
        result = resolver.resolve(html)
        assert '<span class="lt-translatable"' in result

    def test_cdata_section(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """CDATA section — not common in HTML5 but shouldn't crash."""
        html = (
            f"<![CDATA[ {_marker('data', 'data')} ]]><p>{_marker('Hello', 'Hello')}</p>"
        )
        result = resolver.resolve(html)
        assert isinstance(result, str)


# ── Performance ────────────────────────────────────────────────


class TestResolverPerformance:
    def test_large_html_many_markers(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Resolver handles large HTML with many markers without error."""
        markers = [_marker(f"Item {i}", f"item_{i}") for i in range(100)]
        items = "".join(f"<li>{m}</li>" for m in markers)
        html = f"<ul>{items}</ul>"
        result = resolver.resolve(html)
        assert result.count('<span class="lt-translatable"') == 100

    def test_large_html_no_markers(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Large HTML with no markers passes through correctly."""
        html = "<div>" + "<p>Hello world</p>" * 1000 + "</div>"
        result = resolver.resolve(html)
        assert result == html

    def test_consecutive_markers_no_separation(
        self,
        resolver: resolver_mod.MarkerResolver,
    ) -> None:
        """Many markers in a row with zero characters between them."""
        markers = "".join(_marker(f"m{i}", f"m{i}") for i in range(50))
        html = f"<p>{markers}</p>"
        result = resolver.resolve(html)
        assert result.count('<span class="lt-translatable"') == 50


# ── _attrs_json unit tests ─────────────────────────────────────


class TestAttrsJson:
    def test_single_entry(self) -> None:
        result = resolver_mod.MarkerResolver._attrs_json(
            [{"a": "title", "m": "Hello", "c": ""}]
        )
        assert result.startswith(" data-lt-attrs='")
        assert result.endswith("'")
        inner = result[len(" data-lt-attrs='") : -1]
        parsed = json.loads(inner)
        assert parsed == [{"a": "title", "m": "Hello", "c": ""}]

    def test_multiple_entries(self) -> None:
        entries = [
            {"a": "title", "m": "T", "c": ""},
            {"a": "alt", "m": "A", "c": "ctx"},
        ]
        result = resolver_mod.MarkerResolver._attrs_json(entries)
        inner = result[len(" data-lt-attrs='") : -1]
        parsed = json.loads(inner)
        assert len(parsed) == 2

    def test_single_quote_in_value_escaped(self) -> None:
        result = resolver_mod.MarkerResolver._attrs_json(
            [{"a": "title", "m": "it's", "c": ""}]
        )
        # Must not contain unescaped single quote inside the attr value
        inner = result[len(" data-lt-attrs='") : -1]
        assert "'" not in inner  # all real quotes are escaped
        # But should parse correctly if we unescape
        raw = inner.replace("&#39;", "'")
        parsed = json.loads(raw)
        assert parsed[0]["m"] == "it's"

    def test_empty_list(self) -> None:
        result = resolver_mod.MarkerResolver._attrs_json([])
        inner = result[len(" data-lt-attrs='") : -1]
        assert json.loads(inner) == []
