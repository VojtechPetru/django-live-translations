import csv
import io
import json
import logging
import typing as t
import zipfile

import django.db.transaction
import django.utils.timezone
import polib

from live_translations import conf, history, models
from live_translations.backends.po import _get_pending, _set_pending
from live_translations.types import DbOverride, LanguageCode, MsgKey, PluralForms, plural_forms_from_json

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

_CSV_COLUMNS = ["language", "msgid", "context", "msgid_plural", "msgstr_forms", "is_active"]


class ExportRow(t.NamedTuple):
    language: LanguageCode
    msgid: str
    context: str
    msgid_plural: str
    msgstr_forms: str  # JSON-encoded PluralForms
    is_active: bool


class ImportResult(t.TypedDict):
    created: int
    updated: int
    errors: list[str]
    dry_run: t.NotRequired[bool]
    unchanged: t.NotRequired[int]
    preview: t.NotRequired[list["PreviewEntry"]]


class PreviewEntry(t.NamedTuple):
    action: t.Literal["create", "update"]
    language: LanguageCode
    msgid: str
    context: str
    msgid_plural: str
    msgstr_forms: str  # JSON-encoded PluralForms
    is_active: bool
    old_msgstr_forms: str
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
            msgid_plural=e.msgid_plural,
            msgstr_forms=json.dumps(e.msgstr_forms, ensure_ascii=False),
            is_active=e.is_active,
        )
        for e in qs.order_by("language", "msgid", "context")
    ]


def _collect_all_translations(languages: list[LanguageCode]) -> list[ExportRow]:
    """Merge PO defaults with DB overrides. DB wins when both exist."""
    rows_by_key: dict[tuple[LanguageCode, str, str, str], ExportRow] = {}

    # 1. Read PO files
    for lang in languages:
        for key, forms in _read_po_defaults(lang).items():
            forms_json = json.dumps(forms, ensure_ascii=False)
            rows_by_key[(lang, key.msgid, key.context, key.msgid_plural)] = ExportRow(
                language=lang,
                msgid=key.msgid,
                context=key.context,
                msgid_plural=key.msgid_plural,
                msgstr_forms=forms_json,
                is_active=True,
            )

    # 2. Overlay DB overrides
    db_entries = models.TranslationEntry.objects.qs.for_languages(languages).order_by("language", "msgid", "context")
    for e in db_entries:
        rows_by_key[(e.language, e.msgid, e.context, e.msgid_plural)] = ExportRow(
            language=e.language,
            msgid=e.msgid,
            context=e.context,
            msgid_plural=e.msgid_plural,
            msgstr_forms=json.dumps(e.msgstr_forms, ensure_ascii=False),
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
        writer.writerow(
            [
                row.language,
                row.msgid,
                row.context,
                row.msgid_plural,
                row.msgstr_forms,
                str(row.is_active).lower(),
            ]
        )
    return buf.getvalue()


def _read_po_defaults(language: LanguageCode) -> dict[MsgKey, PluralForms]:
    """Read PO file defaults for a language. Returns {MsgKey: PluralForms}."""
    settings = conf.get_settings()
    defaults: dict[MsgKey, PluralForms] = {}
    po_path = settings.locale_dir / language / "LC_MESSAGES" / f"{settings.gettext_domain}.po"
    try:
        po = polib.pofile(str(po_path))
    except (OSError, ValueError):
        return defaults
    for entry in po:
        if not entry.msgid:
            continue
        key = MsgKey(entry.msgid, entry.msgctxt or "", entry.msgid_plural or "")
        if entry.msgid_plural:
            defaults[key] = dict(entry.msgstr_plural)
        else:
            defaults[key] = {0: entry.msgstr}
    return defaults


def export_po(
    *,
    language: LanguageCode,
) -> str:
    """Export translations as a PO file (always includes .po defaults).

    Active DB overrides replace the PO default in msgstr.
    Inactive DB overrides use the PO default as msgstr and store the
    override in an ``ltpending:`` comment + ``fuzzy`` flag.
    """
    po_defaults = _read_po_defaults(language)

    db_overrides: dict[MsgKey, DbOverride] = {}
    for e in models.TranslationEntry.objects.qs.for_language(language).order_by("msgid", "context"):
        forms = plural_forms_from_json(e.msgstr_forms) if e.msgstr_forms else {0: ""}
        db_overrides[MsgKey(e.msgid, e.context, e.msgid_plural)] = DbOverride(forms, e.is_active)

    all_keys: list[MsgKey] = sorted(set(po_defaults.keys()) | set(db_overrides.keys()))

    po = polib.POFile()
    po.metadata = {
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Language": language,
    }

    for key in all_keys:
        po_default = po_defaults.get(key, {0: ""})
        db = db_overrides.get(key)

        if key.msgid_plural:
            # Plural entry
            if db is not None and db.is_active:
                entry = polib.POEntry(
                    msgid=key.msgid, msgstr="", msgctxt=key.context or None, msgid_plural=key.msgid_plural
                )
                entry.msgstr_plural = dict(db.msgstr_forms)
            elif db is not None:
                entry = polib.POEntry(
                    msgid=key.msgid, msgstr="", msgctxt=key.context or None, msgid_plural=key.msgid_plural
                )
                entry.msgstr_plural = dict(po_default)
                entry.flags.append("fuzzy")
                _set_pending(entry, db.msgstr_forms)
            else:
                entry = polib.POEntry(
                    msgid=key.msgid, msgstr="", msgctxt=key.context or None, msgid_plural=key.msgid_plural
                )
                entry.msgstr_plural = dict(po_default)
        elif db is not None and db.is_active:
            entry = polib.POEntry(msgid=key.msgid, msgstr=db.msgstr_forms.get(0, ""), msgctxt=key.context or None)
        elif db is not None:
            entry = polib.POEntry(msgid=key.msgid, msgstr=po_default.get(0, ""), msgctxt=key.context or None)
            entry.flags.append("fuzzy")
            _set_pending(entry, db.msgstr_forms)
        else:
            entry = polib.POEntry(msgid=key.msgid, msgstr=po_default.get(0, ""), msgctxt=key.context or None)

        po.append(entry)

    return str(po)


def export_po_zip(
    *,
    languages: list[LanguageCode] | None,
) -> bytes:
    langs = languages or conf.get_settings().languages

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for lang in langs:
            po_content = export_po(language=lang)
            zf.writestr(f"{lang}.po", po_content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _snapshot_existing(
    valid_rows: list[ExportRow],
) -> dict[tuple[LanguageCode, str, str, str], tuple[str, bool]]:
    """Snapshot existing DB entries for the given rows."""
    lookup = {(r.language, r.msgid, r.context, r.msgid_plural) for r in valid_rows}
    languages = list({r.language for r in valid_rows})

    existing: dict[tuple[LanguageCode, str, str, str], tuple[str, bool]] = {}
    for lang, mid, ctx, mid_plural, forms, is_active in models.TranslationEntry.objects.qs.for_languages(
        languages
    ).values_list("language", "msgid", "context", "msgid_plural", "msgstr_forms", "is_active"):
        key = (lang, mid, ctx, mid_plural)
        if key in lookup:
            existing[key] = (json.dumps(forms, ensure_ascii=False) if forms else '{"0": ""}', is_active)
    return existing


def _build_preview(
    valid_rows: list[ExportRow],
    existing: dict[tuple[LanguageCode, str, str, str], tuple[str, bool]],
) -> tuple[int, int, int, list[PreviewEntry]]:
    """Classify rows as create/update/unchanged and build preview entries."""
    preview: list[PreviewEntry] = []
    created = 0
    updated = 0
    unchanged = 0
    for row in valid_rows:
        key = (row.language, row.msgid, row.context, row.msgid_plural)
        old = existing.get(key)
        if old is None:
            created += 1
            preview.append(
                PreviewEntry(
                    "create",
                    row.language,
                    row.msgid,
                    row.context,
                    row.msgid_plural,
                    row.msgstr_forms,
                    row.is_active,
                    "",
                    None,
                )
            )
        elif old == (row.msgstr_forms, row.is_active):
            unchanged += 1
        else:
            updated += 1
            preview.append(
                PreviewEntry(
                    "update",
                    row.language,
                    row.msgid,
                    row.context,
                    row.msgid_plural,
                    row.msgstr_forms,
                    row.is_active,
                    old[0],
                    old[1],
                )
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

    # Only upsert rows that actually changed (skip unchanged)
    changed_keys = {(p.language, p.msgid, p.context, p.msgid_plural) for p in preview}
    changed_rows = [r for r in valid_rows if (r.language, r.msgid, r.context, r.msgid_plural) in changed_keys]

    if not changed_rows:
        return ImportResult(created=created, updated=updated, errors=errors)

    now = django.utils.timezone.now()
    entries_to_upsert = [
        models.TranslationEntry(
            language=row.language,
            msgid=row.msgid,
            context=row.context,
            msgid_plural=row.msgid_plural,
            msgstr_forms=json.loads(row.msgstr_forms),
            is_active=row.is_active,
            updated_at=now,
        )
        for row in changed_rows
    ]

    with django.db.transaction.atomic():
        models.TranslationEntry.objects.bulk_create(
            entries_to_upsert,
            update_conflicts=True,
            update_fields=["msgstr_forms", "is_active", "updated_at"],
            unique_fields=["language", "msgid", "context", "msgid_plural"],
        )

        history_entries = [(row.language, MsgKey(row.msgid, row.context, row.msgid_plural)) for row in changed_rows]

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

        # Support both old format (msgstr column) and new format (msgstr_forms column)
        has_new_format = "msgstr_forms" in reader.fieldnames
        has_old_format = "msgstr" in reader.fieldnames and not has_new_format

        if not has_new_format and not has_old_format:
            missing = {"language", "msgid"} - set(reader.fieldnames)
            if missing:
                msg = f"Missing required columns: {', '.join(sorted(missing))}"
                return ImportResult(created=0, updated=0, errors=[msg], dry_run=dry_run)

        rows: list[ExportRow] = []
        for line in reader:
            is_active_raw = line.get("is_active", "true").strip().lower()
            is_active = is_active_raw not in ("false", "0", "no")

            if has_old_format:
                # Legacy CSV: single msgstr column -> wrap as {"0": value}
                msgstr_forms = json.dumps({"0": line.get("msgstr", "")})
            else:
                msgstr_forms = line.get("msgstr_forms", '{"0": ""}')

            rows.append(
                ExportRow(
                    language=line.get("language", "").strip(),
                    msgid=line.get("msgid", ""),
                    context=line.get("context", "").strip(),
                    msgid_plural=line.get("msgid_plural", "").strip(),
                    msgstr_forms=msgstr_forms,
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

        pending = _get_pending(entry)
        if pending is not None:
            forms = pending
            is_active = False
        elif entry.msgid_plural:
            forms = dict(entry.msgstr_plural)
            is_active = "fuzzy" not in entry.flags
        else:
            forms = {0: entry.msgstr}
            is_active = "fuzzy" not in entry.flags

        rows.append(
            ExportRow(
                language=lang,
                msgid=entry.msgid,
                context=entry.msgctxt or "",
                msgid_plural=entry.msgid_plural or "",
                msgstr_forms=json.dumps(forms, ensure_ascii=False),
                is_active=is_active,
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
