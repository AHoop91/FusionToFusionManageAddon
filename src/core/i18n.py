"""The add-in's own wording, in the language the user chose.

A language is one JSON file named after its code (``en.json``, ``de.json``, ``pt-BR.json``) in one of three folders: ``resources/languages``
(shipped with the add-in), the active hub's folder of the languages its Hub Admin shared in the Configuration File, and ``languages`` in the
user's settings folder (made by the user, for a language nothing else has, or to change one that is). The user's file wins over the hub's,
and the hub's over a shipped one of the same code. A file looks like::

    {"language": "Deutsch", "strings": {"settings.save": "Speichern", ...}}

Only the add-in's own wording is looked up here. What Fusion Manage and Fusion return (names, field values, picklists, the text of a
server's error) is shown as it came.

English is always loaded under the chosen language, so a key a file does not have, or has wrong, is shown in English instead of as a key.
The active language is English until ``set_language`` is called (the add-in does that at start-up), so nothing that does not ask for
another language depends on what is in the user's folder.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from .atomic import write_atomically
from .logging_setup import get_logger
from .paths import DataDirError, data_dir

log = get_logger("i18n")

DEFAULT_LANGUAGE = "en"
FILE_EXTENSION = ".json"
CODE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")   # en, de, pt-BR, zh-Hans: a code is never a path
PLACEHOLDER = re.compile(r"\{(\w+)\}")
SOURCE_SHIPPED = "shipped"
SOURCE_HUB = "hub"   # shared by the hub's Hub Admin
SOURCE_USER = "user"


@dataclass(frozen=True)
class Language:
    code: str
    name: str      # in the language itself, as its file gives it
    source: str    # SOURCE_SHIPPED | SOURCE_HUB | SOURCE_USER
    path: str

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "name": self.name, "source": self.source}


def shipped_dir() -> str:
    """The folder of the languages that come with the add-in."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "resources", "languages")


def user_dir() -> Optional[str]:
    """The folder of the user's own language files, or None when the user's settings folder is not known."""
    try:
        return os.path.join(data_dir(roaming=True), "languages")
    except DataDirError:
        return None


def _read(path: str) -> Optional[Dict[str, object]]:
    """The file's content as an object, or None (logged) when it cannot be read as one."""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        log.warning("The language file %s cannot be read: %s", path, exc)
        return None
    if not isinstance(data, dict):
        log.warning("The language file %s is not a JSON object", path)
        return None
    return data


def _strings(data: Dict[str, object], path: str) -> Dict[str, str]:
    """The text of a file: the entries that are text. The others are left out, and logged."""
    raw = data.get("strings")
    if not isinstance(raw, dict):
        log.warning("The language file %s has no \"strings\" object", path)
        return {}
    kept = {str(key): value for key, value in raw.items() if isinstance(value, str)}
    if len(kept) != len(raw):
        log.warning("The language file %s has %d entries that are not text; they are left out", path, len(raw) - len(kept))
    return kept


_hub_dir: Optional[str] = None   # the active hub's folder of shared languages (None: no hub, or a hub that shares none)


def set_hub_dir(folder: Optional[str]) -> None:
    """Say which folder holds the languages the active hub shares (None when there is none)."""
    global _hub_dir
    _hub_dir = folder or None


def hub_dir() -> Optional[str]:
    """The folder of the languages the active hub shares, or None."""
    return _hub_dir


def _folders(shipped: Optional[str], user: Optional[str], hub: Optional[str]) -> List[tuple]:
    return [(shipped, SOURCE_SHIPPED), (hub if hub is not None else _hub_dir, SOURCE_HUB), (user, SOURCE_USER)]


def available(shipped: Optional[str] = None, user: Optional[str] = None, hub: Optional[str] = None) -> List[Language]:
    """Every language found, English first and then by name. The folders are the add-in's own unless given (tests give theirs; ``hub`` ""
    is no hub's folder)."""
    shipped = shipped if shipped is not None else shipped_dir()
    user = user if user is not None else user_dir()
    found: Dict[str, Language] = {}
    for folder, source in _folders(shipped, user, hub):   # later folders come last, so their file replaces one of the same code before
        if not folder or not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            code, extension = os.path.splitext(name)
            path = os.path.join(folder, name)
            if extension.lower() != FILE_EXTENSION or not CODE_PATTERN.match(code) or not os.path.isfile(path):
                continue
            data = _read(path)
            if data is None:
                continue
            title = data.get("language")
            found[code.lower()] = Language(code, title.strip() if isinstance(title, str) and title.strip() else code, source, path)
    return sorted(found.values(), key=lambda language: (language.code.lower() != DEFAULT_LANGUAGE, language.name.lower()))


def find(code: str, shipped: Optional[str] = None, user: Optional[str] = None, hub: Optional[str] = None) -> Optional[Language]:
    """The language with this code, or None. The code is looked for in what was found, never used as a path."""
    wanted = str(code or "").strip().lower()
    return next((language for language in available(shipped, user, hub) if language.code.lower() == wanted), None)


def load(code: str, shipped: Optional[str] = None, user: Optional[str] = None, hub: Optional[str] = None) -> Dict[str, str]:
    """The strings of ``code`` over English's: every key English has, in the language when its file has a usable text for it.
    An unknown code gives English. A key only the language has is kept (a newer file than the add-in)."""
    shipped = shipped if shipped is not None else shipped_dir()
    user = user if user is not None else user_dir()
    strings: Dict[str, str] = {}
    english = find(DEFAULT_LANGUAGE, shipped, user, hub)
    if english is not None:
        data = _read(english.path)
        strings.update(_strings(data, english.path) if data is not None else {})
    wanted = find(code, shipped, user, hub)
    if wanted is None:
        if str(code or "").strip().lower() != DEFAULT_LANGUAGE:
            log.warning("The language '%s' is not available; English is used", code)
        return strings
    if wanted.code.lower() == DEFAULT_LANGUAGE:
        return strings
    data = _read(wanted.path)
    if data is None:
        return strings
    for key, text in _strings(data, wanted.path).items():
        if key in strings and placeholders(text) != placeholders(strings[key]):
            log.warning("The language file %s: '%s' does not have the same {placeholders} as English; English is used", wanted.path, key)
            continue
        strings[key] = text
    return strings


def placeholders(text: str) -> frozenset:
    """The names in the ``{name}`` places of a text."""
    return frozenset(PLACEHOLDER.findall(text))


def fill(text: str, params: Dict[str, object]) -> str:
    """``text`` with each ``{name}`` replaced by its value in ``params``; one without a value is left as it is."""
    return PLACEHOLDER.sub(lambda match: str(params[match.group(1)]) if match.group(1) in params else match.group(0), text)


def create(code: str, name: str, shipped: Optional[str] = None, user: Optional[str] = None, hub: Optional[str] = None) -> str:
    """Make a new language file in the user's folder, holding English's text for the user to translate. Answers its path.

    Raises ``ValueError`` for a code that is not a language code, or one that is taken (a language is never replaced), and ``OSError``
    when the file cannot be written (the user's folder is not known, or not writable).
    """
    code = str(code or "").strip().upper()   # a code is always kept in capitals: DE.json, PT-BR.json
    name = str(name or "").strip()
    name = re.sub(r"(?<!\S)\S", lambda letter: letter.group().upper(), name)   # each word starts with a capital: German Test
    if not CODE_PATTERN.match(code):
        raise ValueError("Language code: enter a code such as DE, FR or PT-BR.")
    if not name:
        raise ValueError("Language name: enter the name of the language, in that language, such as Deutsch.")
    shipped = shipped if shipped is not None else shipped_dir()
    folder = user if user is not None else user_dir()
    if not folder:
        raise DataDirError("The settings folder is not known, so a language cannot be made.")
    if find(code, shipped, folder, hub) is not None:
        raise ValueError(f"The language '{code}' exists already.")
    english = find(DEFAULT_LANGUAGE, shipped, folder, hub)
    data = _read(english.path) if english is not None else None
    if data is None:
        raise ValueError("The English language file cannot be read, so there is nothing to start the new language from.")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, code + FILE_EXTENSION)
    write_atomically(path, json.dumps({"language": name, "strings": _strings(data, english.path)}, indent=2, ensure_ascii=False).encode("utf-8"))
    return path


# ---- The language in use ----------------------------------------------------

_active_code = DEFAULT_LANGUAGE
_active: Dict[str, str] = {}
_english: Optional[Dict[str, str]] = None


def _english_strings() -> Dict[str, str]:
    global _english
    if _english is None:
        _english = load(DEFAULT_LANGUAGE, user="", hub="")   # the shipped English only: nothing in a user's or a hub's folder changes what the add-in falls back to
    return _english


def set_language(code: str, shipped: Optional[str] = None, user: Optional[str] = None, hub: Optional[str] = None) -> str:
    """Use ``code`` from now on; answers the code in use (English when ``code`` is not available)."""
    global _active_code, _active
    strings = load(code, shipped, user, hub)
    found = find(code, shipped, user, hub)
    _active_code = found.code if found is not None else DEFAULT_LANGUAGE
    _active = strings
    return _active_code


def active_code() -> str:
    return _active_code


_ribbon_code: Optional[str] = None   # the language the ribbon and palette titles were built in (Fusion fixes them once built)


def mark_ribbon() -> None:
    """The ribbon and the palette titles are built now, in the language in use."""
    global _ribbon_code
    _ribbon_code = _active_code


def restart_needed() -> bool:
    """Is the language in use not the one the ribbon was built in? Then Fusion has to be restarted for the ribbon to follow."""
    return _ribbon_code is not None and _ribbon_code != _active_code


def active_strings() -> Dict[str, str]:
    """All the strings of the language in use, for a panel to show."""
    return dict(_active) if _active else dict(_english_strings())


def t(key: str, **params: object) -> str:
    """The text called ``key`` in the language in use. A key nothing has is answered as itself, so a missing text shows."""
    text = (_active or _english_strings()).get(key)
    if text is None:
        text = _english_strings().get(key, key)
    return fill(text, params)
