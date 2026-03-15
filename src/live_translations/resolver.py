"""MarkerResolver — single-pass HTML state machine for resolving translation markers.

Extracts the marker resolution logic from the middleware into a testable class.
The resolver scans rendered HTML and transforms embedded markers based on their
context (text content, attribute value, raw-text element, or comment).
"""

import json
import re
import typing as t

__all__ = ["MarkerResolver"]


class MarkerResolver:
    """Replace text-safe markers with <span> (text) or plain text + data-lt-attrs (attributes).

    Uses a single-pass state machine to determine whether each marker
    is in text content, an attribute value, or a raw-text element.
    """

    # ── State constants ────────────────────────────────────────
    _S_TEXT = 0
    _S_TAG_OPEN = 1
    _S_TAG_NAME = 2
    _S_TAG_ATTRS = 3
    _S_ATTR_NAME = 4
    _S_ATTR_EQ = 5  # Saw '=', expecting value
    _S_ATTR_DQ = 6  # Inside double-quoted attribute value
    _S_ATTR_SQ = 7  # Inside single-quoted attribute value
    _S_RAWTEXT = 8  # Inside <script>, <style>, <textarea>, <title>
    _S_COMMENT = 9
    _S_ATTR_UQ = 10  # Inside unquoted attribute value

    _RAWTEXT_TAGS: t.ClassVar[frozenset[str]] = frozenset(
        {"script", "style", "textarea", "title"}
    )

    def __init__(
        self,
        marker_re: re.Pattern[str],
        marker_start: str,
        b64_decode: t.Callable[[str], str],
        html_escape: t.Callable[[str], str],
    ) -> None:
        self._marker_re = marker_re
        self._marker_start = marker_start
        self._b64_decode = b64_decode
        self._html_escape = html_escape

    @staticmethod
    def _attrs_json(pending: list[dict[str, str]]) -> str:
        """Serialize pending attribute metadata as a single-quoted HTML attribute.

        Uses single quotes for the attribute delimiter so the inner JSON
        double quotes don't need HTML entity escaping.  Any single quotes
        in msgid/context values are escaped to &#39; to keep the attribute valid.
        """
        raw = json.dumps(pending, separators=(",", ":"))
        # Escape any literal ' in the JSON so it can't break the single-quoted attr
        safe = raw.replace("'", "&#39;")
        return f" data-lt-attrs='{safe}'"

    def resolve(
        self,
        html: str,
        /,
    ) -> str:
        """Scan *html* and replace markers based on their HTML context."""
        result: list[str] = []
        i = 0
        n = len(html)
        state = self._S_TEXT

        # Tag tracking
        tag_name_buf: list[str] = []
        tag_name = ""
        rawtext_close = ""  # e.g. "</script>"

        # Attribute tracking
        attr_name_buf: list[str] = []
        cur_attr_name = ""

        # Pending attribute translations for the current element.
        # Flushed when we reach the tag's closing '>'.
        pending_attrs: list[dict[str, str]] = []

        while i < n:
            ch = html[i]

            # ── Marker detection (any state) ───────────────────
            if ch == self._marker_start:
                m = self._marker_re.match(html, i)
                if m:
                    msgid = self._b64_decode(m.group(1))
                    ctx = self._b64_decode(m.group(2))
                    content = self._b64_decode(m.group(3))
                    flag = m.group(4)

                    escaped_content = (
                        self._html_escape(content) if flag == "r" else content
                    )

                    if state == self._S_TEXT:
                        # Text content -> <span> wrapper
                        result.append(
                            f'<span class="lt-translatable" data-lt-msgid="{self._html_escape(msgid)}"'
                            f' data-lt-context="{self._html_escape(ctx)}">{escaped_content}</span>'
                        )
                    elif state in (
                        self._S_ATTR_DQ,
                        self._S_ATTR_SQ,
                        self._S_ATTR_EQ,
                        self._S_ATTR_UQ,
                    ):
                        # Inside an attribute value -> plain text, record metadata
                        result.append(escaped_content)
                        pending_attrs.append({"a": cur_attr_name, "m": msgid, "c": ctx})
                        if state == self._S_ATTR_EQ:
                            state = self._S_ATTR_UQ
                    else:
                        # RAWTEXT, COMMENT, or unexpected -> plain text only
                        result.append(escaped_content)

                    i = m.end()
                    continue

            # ── State transitions ──────────────────────────────
            if state == self._S_TEXT:
                if ch == "<":
                    # Check for comment
                    if html[i : i + 4] == "<!--":
                        state = self._S_COMMENT
                        result.append("<!--")
                        i += 4
                        continue
                    state = self._S_TAG_OPEN
                    tag_name_buf = []
                    tag_name = ""
                    pending_attrs = []

            elif state == self._S_TAG_OPEN:
                if ch.isalpha() or ch == "/":
                    state = self._S_TAG_NAME
                    tag_name_buf = []
                    if ch != "/":
                        tag_name_buf.append(ch.lower())
                elif ch == ">":
                    state = self._S_TEXT
                elif ch == "!":
                    # Could be <!DOCTYPE ...> — treat interior as tag attrs
                    state = self._S_TAG_ATTRS

            elif state == self._S_TAG_NAME:
                if ch.isalnum() or ch == "-":
                    tag_name_buf.append(ch.lower())
                elif ch in (" ", "\t", "\n", "\r", "\f"):
                    tag_name = "".join(tag_name_buf)
                    state = self._S_TAG_ATTRS
                elif ch == ">":
                    tag_name = "".join(tag_name_buf)
                    # Flush pending attribute metadata before '>'
                    if pending_attrs:
                        result.append(self._attrs_json(pending_attrs))
                        pending_attrs = []
                    if tag_name in self._RAWTEXT_TAGS:
                        state = self._S_RAWTEXT
                        rawtext_close = f"</{tag_name}>"
                    else:
                        state = self._S_TEXT
                elif ch == "/":
                    tag_name = "".join(tag_name_buf)
                    # Self-closing: stay in TAG_NAME, '>' comes next

            elif state == self._S_TAG_ATTRS:
                if ch == ">":
                    # Flush pending attribute metadata before '>'
                    if pending_attrs:
                        result.append(self._attrs_json(pending_attrs))
                        pending_attrs = []
                    if tag_name in self._RAWTEXT_TAGS:
                        state = self._S_RAWTEXT
                        rawtext_close = f"</{tag_name}>"
                    else:
                        state = self._S_TEXT
                elif ch == '"':
                    state = self._S_ATTR_DQ
                elif ch == "'":
                    state = self._S_ATTR_SQ
                elif ch == "=":
                    cur_attr_name = "".join(attr_name_buf).lower()
                    state = self._S_ATTR_EQ
                elif ch in (" ", "\t", "\n", "\r", "\f"):
                    pass  # whitespace between attributes
                elif ch == "/":
                    pass  # self-closing slash
                else:
                    # Start of attribute name
                    attr_name_buf = [ch.lower()]
                    state = self._S_ATTR_NAME

            elif state == self._S_ATTR_NAME:
                if ch == "=":
                    cur_attr_name = "".join(attr_name_buf).lower()
                    state = self._S_ATTR_EQ
                elif ch in (" ", "\t", "\n", "\r", "\f"):
                    # Boolean attribute (no value), back to attrs
                    state = self._S_TAG_ATTRS
                elif ch == ">":
                    # Boolean attribute at end of tag
                    if pending_attrs:
                        result.append(self._attrs_json(pending_attrs))
                        pending_attrs = []
                    if tag_name in self._RAWTEXT_TAGS:
                        state = self._S_RAWTEXT
                        rawtext_close = f"</{tag_name}>"
                    else:
                        state = self._S_TEXT
                else:
                    attr_name_buf.append(ch.lower())

            elif state == self._S_ATTR_EQ:
                if ch == '"':
                    state = self._S_ATTR_DQ
                elif ch == "'":
                    state = self._S_ATTR_SQ
                elif ch in (" ", "\t", "\n", "\r", "\f"):
                    pass  # whitespace after =
                elif ch == ">":
                    # '=' immediately before '>' is malformed — close the tag
                    if pending_attrs:
                        result.append(self._attrs_json(pending_attrs))
                        pending_attrs = []
                    if tag_name in self._RAWTEXT_TAGS:
                        state = self._S_RAWTEXT
                        rawtext_close = f"</{tag_name}>"
                    else:
                        state = self._S_TEXT
                else:
                    # Unquoted attribute value — consume until whitespace or >
                    state = self._S_ATTR_UQ

            elif state == self._S_ATTR_DQ:
                if ch == '"':
                    state = self._S_TAG_ATTRS
                elif ch == ">":
                    # Recovery heuristic for unclosed double-quoted attribute:
                    # if no closing " exists before the next tag-like <, assume
                    # the quote was never closed and treat > as tag close.
                    recover = True
                    for j in range(i + 1, n):
                        if html[j] == '"':
                            recover = False
                            break
                        if (
                            html[j] == "<"
                            and j + 1 < n
                            and (html[j + 1].isalpha() or html[j + 1] == "/")
                        ):
                            break
                    if recover:
                        if pending_attrs:
                            result.append(self._attrs_json(pending_attrs))
                            pending_attrs = []
                        if tag_name in self._RAWTEXT_TAGS:
                            state = self._S_RAWTEXT
                            rawtext_close = f"</{tag_name}>"
                        else:
                            state = self._S_TEXT

            elif state == self._S_ATTR_SQ:
                if ch == "'":
                    state = self._S_TAG_ATTRS
                elif ch == ">":
                    # Same recovery heuristic for unclosed single-quoted attribute.
                    recover = True
                    for j in range(i + 1, n):
                        if html[j] == "'":
                            recover = False
                            break
                        if (
                            html[j] == "<"
                            and j + 1 < n
                            and (html[j + 1].isalpha() or html[j + 1] == "/")
                        ):
                            break
                    if recover:
                        if pending_attrs:
                            result.append(self._attrs_json(pending_attrs))
                            pending_attrs = []
                        if tag_name in self._RAWTEXT_TAGS:
                            state = self._S_RAWTEXT
                            rawtext_close = f"</{tag_name}>"
                        else:
                            state = self._S_TEXT

            elif state == self._S_ATTR_UQ:
                if ch in (" ", "\t", "\n", "\r", "\f"):
                    state = self._S_TAG_ATTRS
                elif ch == ">":
                    if pending_attrs:
                        result.append(self._attrs_json(pending_attrs))
                        pending_attrs = []
                    if tag_name in self._RAWTEXT_TAGS:
                        state = self._S_RAWTEXT
                        rawtext_close = f"</{tag_name}>"
                    else:
                        state = self._S_TEXT

            elif state == self._S_RAWTEXT:
                close_len = len(rawtext_close)
                if html[i : i + close_len].lower() == rawtext_close:
                    result.append(html[i : i + close_len])
                    i += close_len
                    state = self._S_TEXT
                    continue

            elif state == self._S_COMMENT:
                if html[i : i + 3] == "-->":
                    result.append("-->")
                    i += 3
                    state = self._S_TEXT
                    continue

            result.append(ch)
            i += 1

        return "".join(result)
