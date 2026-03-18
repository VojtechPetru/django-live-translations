"""E2E test settings for PO file backend.

Inherits from the base example settings. The LOCALE_DIR and DATABASE
are overridden at runtime by conftest fixtures so each test gets isolation.
"""

import os
import typing as t
from pathlib import Path

from config.settings import *  # noqa: F403

if t.TYPE_CHECKING:
    from live_translations.conf import LiveTranslationsSettings

# Override locale dir from env (set by conftest fixture)
_locale_override = os.environ.get("LT_E2E_LOCALE_DIR")
if _locale_override:
    LOCALE_PATHS = [Path(_locale_override)]

# Override database from env (set by conftest fixture)
_db_override = os.environ.get("LT_E2E_DB_PATH")
if _db_override:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _db_override,
        }
    }

LIVE_TRANSLATIONS: "LiveTranslationsSettings" = {
    "BACKEND": "live_translations.backends.po.POFileBackend",
    "LANGUAGES": ["en", "cs", "es"],
    **({"LOCALE_DIR": _locale_override} if _locale_override else {}),
}
