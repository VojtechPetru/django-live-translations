"""Shared domain types for live_translations."""

import typing as t

if t.TYPE_CHECKING:
    import django.http

__all__ = [
    "BulkActivateResult",
    "DbOverride",
    "DeleteResult",
    "DiffSegment",
    "DisplayResult",
    "HistoryItem",
    "HistoryResult",
    "LanguageCode",
    "MsgKey",
    "OverrideMap",
    "PermissionCheck",
    "PermissionResult",
    "SaveResult",
    "StringId",
    "StringTable",
    "TranslationInfo",
    "TranslationsResult",
]

type LanguageCode = str

type PermissionResult = bool | set[LanguageCode]

type PermissionCheck = t.Callable[["django.http.HttpRequest"], PermissionResult]


class MsgKey(t.NamedTuple):
    msgid: str
    context: str


type OverrideMap = dict[MsgKey, str]

type StringId = int
"""Index into the per-request string registry (0-65535)."""


class StringTableEntry(t.TypedDict):
    """Single entry in the JSON string table injected as ``window.__LT_STRINGS__``."""

    m: str
    c: str


type StringTable = dict[int, StringTableEntry]
"""Maps StringId to {m, c}. Serialized to JSON for the frontend."""


class DbOverride(t.NamedTuple):
    msgstr: str
    is_active: bool


class DiffSegment(t.TypedDict):
    type: t.Literal["equal", "insert", "delete"]
    text: str


class TranslationInfo(t.TypedDict):
    msgstr: str
    fuzzy: bool
    is_active: bool
    has_override: bool


class DisplayResult(t.TypedDict):
    text: str
    is_preview_entry: bool


class TranslationsResult(t.TypedDict):
    msgid: str
    context: str
    translations: dict[LanguageCode, TranslationInfo]
    defaults: dict[LanguageCode, str]
    hint: str


class SaveResult(t.TypedDict):
    ok: bool
    display: DisplayResult


class DeleteResult(t.TypedDict):
    ok: bool
    deleted: int
    display: DisplayResult


class HistoryItem(t.TypedDict):
    id: int
    language: str
    action: str
    old_value: str
    new_value: str
    user: str
    created_at: str
    diff: t.NotRequired[list[DiffSegment]]


class HistoryResult(t.TypedDict):
    history: list[HistoryItem]


class BulkActivateResult(t.TypedDict):
    ok: bool
    activated: int
