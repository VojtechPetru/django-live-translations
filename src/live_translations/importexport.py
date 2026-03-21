"""Import/export logic for translation overrides."""

import csv
import io
import logging
import typing as t
import zipfile

import django.db.models
import django.db.transaction
import django.utils.timezone
import polib

from live_translations import conf, history, models
from live_translations.backends.po import _get_pending, _set_pending
from live_translations.types import DbOverride, LanguageCode, MsgKey

__all__ = [
    "ExportRow",
    "ImportResult",
    "PreviewEntry",
    "export_csv",
    "export_po",
    "export_po_zip",
    "import_csv",
    "import_po",
    "import_po_zip",
]

logger = logging.getLogger(__name__)

_CSV_COLUMNS = ["language", "msgid", "context", "msgstr", "is_active"]


class ExportRow(t.NamedTuple):
    language: LanguageCode
    msgid: str
    context: str
    msgstr: str
    is_active: bool


class ImportResult(t.TypedDict):
    created: int
    updated: int
    errors: list[str]
    dry_run: t.NotRequired[bool]
    unchanged: t.NotRequired[int]
    preview: t.NotRequired[list["PreviewEntry"]]


class PreviewEntry(t.NamedTuple):
    action: str  # "create" or "update"
    language: LanguageCode
    msgid: str
    context: str
    msgstr: str
    is_active: bool
    old_msgstr: str
    old_is_active: bool | None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _rows_from_queryset(
    queryset: models.TranslationEntryQuerySet,
    *,
    languages: list[LanguageCode] | None,
) -> list[ExportRow]:
    qs = queryset
    if languages:
        qs = qs.for_languages(languages)
    return [
        ExportRow(
            language=e.language,
            msgid=e.msgid,
            context=e.context,
            msgstr=e.msgstr,
            is_active=e.is_active,
        )
        for e in qs.order_by("language", "msgid", "context")
    ]


def _collect_all_translations(languages: list[LanguageCode]) -> list[ExportRow]:
    """Merge PO defaults with DB overrides. DB wins when both exist."""
    settings = conf.get_settings()
    rows_by_key: dict[tuple[LanguageCode, str, str], ExportRow] = {}

    # 1. Read PO files
    for lang in languages:
        po_path = settings.locale_dir / lang / "LC_MESSAGES" / f"{settings.gettext_domain}.po"
        try:
            po = polib.pofile(str(po_path))
        except (OSError, ValueError):
            continue
        for entry in po:
            if not entry.msgid:
                continue  # skip metadata entry
            ctx = entry.msgctxt or ""
            rows_by_key[(lang, entry.msgid, ctx)] = ExportRow(
                language=lang,
                msgid=entry.msgid,
                context=ctx,
                msgstr=entry.msgstr,
                is_active=True,
            )

    # 2. Overlay DB overrides
    db_entries = models.TranslationEntry.objects.qs.for_languages(languages).order_by("language", "msgid", "context")
    for e in db_entries:
        rows_by_key[(e.language, e.msgid, e.context)] = ExportRow(
            language=e.language,
            msgid=e.msgid,
            context=e.context,
            msgstr=e.msgstr,
            is_active=e.is_active,
        )

    return sorted(rows_by_key.values())


def export_csv(
    queryset: models.TranslationEntryQuerySet,
    *,
    include_defaults: bool,
    languages: list[LanguageCode] | None,
) -> str:
    if include_defaults:
        langs = languages or conf.get_settings().languages
        rows = _collect_all_translations(langs)
    else:
        rows = _rows_from_queryset(queryset, languages=languages)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_COLUMNS)
    for row in rows:
        writer.writerow([row.language, row.msgid, row.context, row.msgstr, str(row.is_active).lower()])
    return buf.getvalue()


def _read_po_defaults(language: LanguageCode) -> dict[MsgKey, str]:
    """Read PO file defaults for a language. Returns {MsgKey: msgstr}."""
    settings = conf.get_settings()
    defaults: dict[MsgKey, str] = {}
    po_path = settings.locale_dir / language / "LC_MESSAGES" / f"{settings.gettext_domain}.po"
    try:
        po = polib.pofile(str(po_path))
    except (OSError, ValueError):
        return defaults
    for entry in po:
        if not entry.msgid:
            continue
        defaults[MsgKey(entry.msgid, entry.msgctxt or "")] = entry.msgstr
    return defaults


def export_po(
    queryset: models.TranslationEntryQuerySet,
    *,
    language: LanguageCode,
) -> str:
    """Export translations as a PO file (always includes .po defaults).

    Active DB overrides replace the PO default in msgstr.
    Inactive DB overrides use the PO default as msgstr and store the
    override in an ``ltpending:`` comment + ``fuzzy`` flag, making the
    file usable for both DB import (fuzzy → inactive) and PO backend
    migration (ltpending preserves exact state).
    """
    po_defaults = _read_po_defaults(language)

    db_overrides: dict[MsgKey, DbOverride] = {}
    for e in models.TranslationEntry.objects.qs.for_language(language).order_by("msgid", "context"):
        db_overrides[MsgKey(e.msgid, e.context)] = DbOverride(e.msgstr, e.is_active)

    all_keys: list[MsgKey] = sorted(set(po_defaults.keys()) | set(db_overrides.keys()))

    po = polib.POFile()
    po.metadata = {
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Language": language,
    }

    for key in all_keys:
        po_default = po_defaults.get(key, "")
        db = db_overrides.get(key)

        if db is not None:
            if db.is_active:
                entry = polib.POEntry(msgid=key.msgid, msgstr=db.msgstr, msgctxt=key.context or None)
            else:
                # Inactive: msgstr = PO default, ltpending = DB override, fuzzy flag
                entry = polib.POEntry(msgid=key.msgid, msgstr=po_default, msgctxt=key.context or None)
                entry.flags.append("fuzzy")
                _set_pending(entry, db.msgstr)
        else:
            entry = polib.POEntry(msgid=key.msgid, msgstr=po_default, msgctxt=key.context or None)

        po.append(entry)

    return str(po)


def export_po_zip(
    queryset: models.TranslationEntryQuerySet,
    *,
    languages: list[LanguageCode] | None,
) -> bytes:
    langs = languages or conf.get_settings().languages

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for lang in langs:
            po_content = export_po(queryset, language=lang)
            zf.writestr(f"{lang}.po", po_content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _snapshot_existing(
    valid_rows: list[ExportRow],
) -> dict[tuple[LanguageCode, str, str], tuple[str, bool]]:
    """Snapshot existing DB entries for the given rows."""
    lookup_q = django.db.models.Q()
    for row in valid_rows:
        lookup_q |= django.db.models.Q(language=row.language, msgid=row.msgid, context=row.context)

    existing: dict[tuple[LanguageCode, str, str], tuple[str, bool]] = {}
    for lang, mid, ctx, msgstr, is_active in models.TranslationEntry.objects.qs.filter(lookup_q).values_list(
        "language", "msgid", "context", "msgstr", "is_active"
    ):
        existing[(lang, mid, ctx)] = (msgstr, is_active)
    return existing


def _build_preview(
    valid_rows: list[ExportRow],
    existing: dict[tuple[LanguageCode, str, str], tuple[str, bool]],
) -> tuple[int, int, int, list[PreviewEntry]]:
    """Classify rows as create/update/unchanged and build preview entries."""
    preview: list[PreviewEntry] = []
    created = 0
    updated = 0
    unchanged = 0
    for row in valid_rows:
        key = (row.language, row.msgid, row.context)
        old = existing.get(key)
        if old is None:
            created += 1
            preview.append(
                PreviewEntry("create", row.language, row.msgid, row.context, row.msgstr, row.is_active, "", None)
            )
        elif old == (row.msgstr, row.is_active):
            updated += 1
            unchanged += 1
        else:
            updated += 1
            preview.append(
                PreviewEntry("update", row.language, row.msgid, row.context, row.msgstr, row.is_active, old[0], old[1])
            )
    return created, updated, unchanged, preview


def _validate_rows(rows: list[ExportRow]) -> tuple[list[ExportRow], list[str]]:
    """Validate import rows, returning valid rows and errors."""
    errors: list[str] = []
    valid_rows: list[ExportRow] = []
    for i, row in enumerate(rows, 1):
        if not row.msgid:
            errors.append(f"Row {i}: empty msgid")
            continue
        if not row.language:
            errors.append(f"Row {i}: empty language")
            continue
        valid_rows.append(row)
    return valid_rows, errors


def _bulk_import(rows: list[ExportRow], *, dry_run: bool = False) -> ImportResult:
    """Core import logic: upsert TranslationEntry rows from ExportRow list."""
    valid_rows, errors = _validate_rows(rows)

    if not valid_rows:
        return ImportResult(created=0, updated=0, errors=errors, dry_run=dry_run, unchanged=0, preview=[])

    existing = _snapshot_existing(valid_rows)
    created, updated, unchanged, preview = _build_preview(valid_rows, existing)

    if dry_run:
        return ImportResult(
            created=created, updated=updated, errors=errors, dry_run=True, unchanged=unchanged, preview=preview
        )

    now = django.utils.timezone.now()
    entries_to_create = [
        models.TranslationEntry(
            language=row.language,
            msgid=row.msgid,
            context=row.context,
            msgstr=row.msgstr,
            is_active=row.is_active,
            updated_at=now,
        )
        for row in valid_rows
    ]

    with django.db.transaction.atomic():
        models.TranslationEntry.objects.bulk_create(
            entries_to_create,
            update_conflicts=True,
            update_fields=["msgstr", "is_active", "updated_at"],
            unique_fields=["language", "msgid", "context"],
        )

        history_entries = [(row.language, MsgKey(row.msgid, row.context)) for row in valid_rows]

        if history_entries:
            history.record_bulk_action(
                entries=history_entries,
                action=models.TranslationHistory.Action.UPDATE,
                old_value="(import)",
                new_value="(import)",
            )

        conf.get_backend_instance().bump_catalog_version()

    return ImportResult(created=created, updated=updated, errors=errors)


def import_csv(content: str, *, dry_run: bool = False) -> ImportResult:
    try:
        reader = csv.DictReader(io.StringIO(content))
        if reader.fieldnames is None:
            return ImportResult(created=0, updated=0, errors=["Empty or invalid CSV file"], dry_run=dry_run)

        missing = {"language", "msgid", "msgstr"} - set(reader.fieldnames)
        if missing:
            msg = f"Missing required columns: {', '.join(sorted(missing))}"
            return ImportResult(created=0, updated=0, errors=[msg], dry_run=dry_run)

        rows: list[ExportRow] = []
        for _i, line in enumerate(reader, 2):  # row 2 = first data row after header
            is_active_raw = line.get("is_active", "true").strip().lower()
            is_active = is_active_raw not in ("false", "0", "no")
            rows.append(
                ExportRow(
                    language=line.get("language", "").strip(),
                    msgid=line.get("msgid", ""),
                    context=line.get("context", "").strip(),
                    msgstr=line.get("msgstr", ""),
                    is_active=is_active,
                )
            )
    except csv.Error as e:
        return ImportResult(created=0, updated=0, errors=[f"CSV parse error: {e}"], dry_run=dry_run)

    return _bulk_import(rows, dry_run=dry_run)


def import_po(content: str, language: LanguageCode, *, dry_run: bool = False) -> ImportResult:
    try:
        po = polib.pofile(content)
    except Exception as e:  # noqa: BLE001
        return ImportResult(created=0, updated=0, errors=[f"PO parse error: {e}"], dry_run=dry_run)

    # If language not given, try PO metadata
    lang = language
    if not lang:
        lang = po.metadata.get("Language", "")
    if not lang:
        return ImportResult(
            created=0,
            updated=0,
            errors=["Language not specified and not found in PO metadata"],
            dry_run=dry_run,
        )

    rows: list[ExportRow] = []
    for entry in po:
        if not entry.msgid:
            continue

        # Check ltpending first (preserves exact DB state from our exports),
        # then fall back to fuzzy flag (standard PO convention).
        pending = _get_pending(entry)
        if pending is not None:
            rows.append(
                ExportRow(
                    language=lang,
                    msgid=entry.msgid,
                    context=entry.msgctxt or "",
                    msgstr=pending,
                    is_active=False,
                )
            )
        else:
            rows.append(
                ExportRow(
                    language=lang,
                    msgid=entry.msgid,
                    context=entry.msgctxt or "",
                    msgstr=entry.msgstr,
                    is_active="fuzzy" not in entry.flags,
                )
            )

    return _bulk_import(rows, dry_run=dry_run)


def import_po_zip(data: bytes, *, dry_run: bool = False) -> ImportResult:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ImportResult(created=0, updated=0, errors=["Invalid zip file"], dry_run=dry_run)

    total_created = 0
    total_updated = 0
    total_unchanged = 0
    all_errors: list[str] = []
    all_preview: list[PreviewEntry] = []

    for name in sorted(zf.namelist()):
        if not name.endswith(".po"):
            continue
        lang = name.rsplit("/", 1)[-1].removesuffix(".po")
        content = zf.read(name).decode("utf-8")
        result = import_po(content, language=lang, dry_run=dry_run)
        total_created += result["created"]
        total_updated += result["updated"]
        all_errors.extend(result["errors"])
        if dry_run:
            all_preview.extend(result.get("preview", []))
            total_unchanged += result.get("unchanged", 0)

    if dry_run:
        return ImportResult(
            created=total_created,
            updated=total_updated,
            errors=all_errors,
            dry_run=True,
            unchanged=total_unchanged,
            preview=all_preview,
        )
    return ImportResult(created=total_created, updated=total_updated, errors=all_errors)
