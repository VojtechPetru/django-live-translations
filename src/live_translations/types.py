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
    "PluralForms",
    "SaveResult",
    "StringId",
    "StringTable",
    "TranslationInfo",
    "TranslationsResult",
    "is_plural_key",
    "plural_forms_from_json",
    "plural_forms_to_json",
]

type LanguageCode = str

type PermissionResult = bool | set[LanguageCode]

type PermissionCheck = t.Callable[["django.http.HttpRequest"], PermissionResult]

type PluralForms = dict[int, str]
"""Maps plural form index to translated string. Singular entries use ``{0: text}``."""


class MsgKey(t.NamedTuple):
    msgid: str
    context: str
    msgid_plural: str = ""


def is_plural_key(key: MsgKey) -> t.TypeGuard[MsgKey]:
    """True when key represents a plural translation (has non-empty msgid_plural)."""
    return key.msgid_plural != ""


type OverrideMap = dict[MsgKey, PluralForms]

type StringId = int
"""Index into the per-request string registry (0-65535)."""


class _StringTableEntryRequired(t.TypedDict):
    m: str
    c: str


class StringTableEntry(_StringTableEntryRequired, total=False):
    """Single entry in the JSON string table injected as ``window.__LT_STRINGS__``."""

    p: str  # msgid_plural, only present for plural entries


type StringTable = dict[int, StringTableEntry]
"""Maps StringId to {m, c[, p]}. Serialized to JSON for the frontend."""


class DbOverride(t.NamedTuple):
    msgstr_forms: PluralForms
    is_active: bool


class DiffSegment(t.TypedDict):
    type: t.Literal["equal", "insert", "delete"]
    text: str


class TranslationInfo(t.TypedDict):
    msgstr_forms: PluralForms
    fuzzy: bool
    is_active: bool
    has_override: bool


class DisplayResult(t.TypedDict):
    text: str
    is_preview_entry: bool
    reload_required: bool


class TranslationsResult(t.TypedDict):
    msgid: str
    context: str
    msgid_plural: str
    translations: dict[LanguageCode, TranslationInfo]
    defaults: dict[LanguageCode, PluralForms]
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
    form_index: int
    diff: t.NotRequired[list[DiffSegment]]


class HistoryResult(t.TypedDict):
    history: list[HistoryItem]


class BulkActivateResult(t.TypedDict):
    ok: bool
    activated: int


# ---------------------------------------------------------------------------
# JSON boundary conversion helpers
# ---------------------------------------------------------------------------


def plural_forms_to_json(forms: PluralForms) -> dict[str, str]:
    """Convert int-keyed PluralForms to string-keyed dict for JSON serialization."""
    return {str(k): v for k, v in forms.items()}


def plural_forms_from_json(data: dict[str, str]) -> PluralForms:
    """Convert string-keyed JSON dict to int-keyed PluralForms."""
    return {int(k): v for k, v in data.items()}
