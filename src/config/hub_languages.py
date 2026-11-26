"""The languages a hub shares: the language files a Hub Admin made travel in the hub's Configuration File, and each member who reads the
file keeps them in a folder of that hub, where the add-in finds them (``core.i18n``).

In the file they are a section of their own beside the settings::

    {"format": "MfgToFm.config", ..., "config": {...}, "languages": {"de": {"language": "Deutsch", "strings": {...}}}}

A file without the section (older add-ins write none) shares no languages. What is read from a file is checked, never trusted: codes must
look like language codes, English is never replaced, and only text is kept.
"""

import json
import os
import re
import shutil
from typing import Any, Callable, Dict, List, Optional

from ..core.atomic import write_atomically
from ..core.i18n import CODE_PATTERN, DEFAULT_LANGUAGE, FILE_EXTENSION, SOURCE_USER, available, set_hub_dir, set_language
from ..core.logging_setup import get_logger
from ..core.paths import DataDirError, data_dir
from .language_setting import read_language

log = get_logger("hub_languages")

MAX_SHARED = 30   # languages a file may carry
HUBS_FOLDER = "hub-languages"           # the languages received from each hub: one folder per hub


def shareable(code: str) -> bool:
    """Can a language with this code be shared? A code that is a code, and not English (English is the add-in's own)."""
    return bool(CODE_PATTERN.match(code)) and code.lower() != DEFAULT_LANGUAGE


def clean(languages: Any) -> Dict[str, Dict[str, Any]]:
    """The languages of a file's ``languages`` section that can be used: ``{code: {"language": name, "strings": {key: text}}}``."""
    if not isinstance(languages, dict):
        return {}
    kept: Dict[str, Dict[str, Any]] = {}
    seen = set()
    for code, data in languages.items():
        if len(kept) >= MAX_SHARED:
            log.warning("A Configuration File shares more than %d languages; the rest are left out", MAX_SHARED)
            break
        if not isinstance(code, str) or not shareable(code) or code.lower() in seen:
            continue
        language = _clean_language(code, data)
        if language is not None:
            kept[code] = language
            seen.add(code.lower())
    return kept


def _clean_language(code: str, data: Any) -> Optional[Dict[str, Any]]:
    """One language of a file's ``languages`` section as ``{"language": name, "strings": {key: text}}``, or None when it has no usable text."""
    strings = data.get("strings") if isinstance(data, dict) else None
    if not isinstance(strings, dict):
        return None
    text = {str(key): value for key, value in strings.items() if isinstance(value, str)}
    if not text:
        return None
    name = data.get("language")
    return {"language": name.strip() if isinstance(name, str) and name.strip() else code, "strings": text}


class HubLanguages:
    """The languages a Hub Admin puts in the file, and the languages received from a hub (for everyone). ``base`` is the settings
    folder, and ``activate`` what uses the user's language again once a hub's languages are known; a test gives its own."""

    def __init__(self, base: Optional[str] = None, activate: Optional[Callable[[], None]] = None) -> None:
        self._base = base
        self._activate = activate if activate is not None else lambda: set_language(read_language())

    def _folder(self) -> str:
        return self._base if self._base is not None else data_dir(roaming=True)

    def folder(self, hub_id: str) -> Optional[str]:
        """Where the languages received from this hub are kept, or None when there is no hub or the settings folder is not known."""
        if not hub_id:
            return None
        try:
            return os.path.join(self._folder(), HUBS_FOLDER, re.sub(r"[^A-Za-z0-9_.-]", "_", hub_id))
        except DataDirError:
            return None

    # ---- what a Hub Admin shares

    def collect(self, shipped: Optional[str] = None, user: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """The languages to put in the hub's Configuration File: every language of the user's own that can be used (files the add-in
        cannot read, and codes that cannot be shared, are left out)."""
        files = [language for language in available(shipped, user, "") if language.source == SOURCE_USER and shareable(language.code)]
        found: Dict[str, Dict[str, Any]] = {}
        for language in files:
            try:
                with open(language.path, "r", encoding="utf-8-sig") as handle:
                    data = json.load(handle)
            except (OSError, ValueError):
                log.warning("The language %s is not shared: its file cannot be read", language.code)
                continue
            found.update(clean({language.code: data}))
        return found

    # ---- what a member receives

    def receive(self, hub_id: str, languages: Any) -> List[str]:
        """Keep the languages of a Configuration File as this hub's, replacing the ones kept from it before (a language the Hub Admin took
        out goes too), and use them from now on. Answers the codes kept."""
        folder = self.folder(hub_id)
        if not folder:
            return []
        kept = clean(languages)
        try:
            if kept:
                os.makedirs(folder, exist_ok=True)
                for code, data in kept.items():
                    write_atomically(os.path.join(folder, code + FILE_EXTENSION), json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
            self._remove_stale(folder, kept)
        except OSError:
            log.exception("The languages of the hub could not be kept")
            return []
        self.use(hub_id)
        return list(kept)

    @staticmethod
    def _remove_stale(folder: str, kept: Dict[str, Any]) -> None:
        """Delete the language files in ``folder`` that are not in ``kept``, and the folder itself when nothing is kept."""
        if not os.path.isdir(folder):
            return
        for name in os.listdir(folder):
            code, extension = os.path.splitext(name)
            if extension.lower() == FILE_EXTENSION and code not in kept:
                os.remove(os.path.join(folder, name))
        if not kept:
            shutil.rmtree(folder, ignore_errors=True)

    def use(self, hub_id: str) -> None:
        """This hub is the active one: find its languages from now on, and use the user's language again (it may be one of them)."""
        folder = self.folder(hub_id)
        set_hub_dir(folder if folder and os.path.isdir(folder) else None)
        self._activate()
