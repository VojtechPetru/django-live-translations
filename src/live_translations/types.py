"""Shared domain types for live_translations."""

import typing as t

__all__ = [
    "DbOverride",
    "DiffSegment",
    "LanguageCode",
    "MsgKey",
    "OverrideMap",
]

LanguageCode: t.TypeAlias = str


class MsgKey(t.NamedTuple):
    msgid: str
    context: str


OverrideMap: t.TypeAlias = dict[MsgKey, str]


class DbOverride(t.NamedTuple):
    msgstr: str
    is_active: bool


class DiffSegment(t.TypedDict):
    type: str
    text: str
