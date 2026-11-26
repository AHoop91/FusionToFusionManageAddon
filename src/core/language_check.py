"""Checking a language file against the add-in's own: is it the shape the add-in reads, and does every text map onto English's?

English is the reference. A file is an object with a ``language`` name and a ``strings`` object of text, keyed by the names English has. What
the add-in does with what it finds, so the report can say it:

- a text whose name English does not have is ignored (the file may be for a newer add-in);
- a name English has and the file lacks shows in English;
- a text with other ``{placeholders}`` than English's shows in English, because a panel would put the wrong values in it, or none;
- an entry that is not text is ignored.

A file that cannot be read at all, or has no ``strings`` object, is an error: the language cannot be used.
"""

import json
import os
from typing import Any, Dict, List, Optional

from . import i18n
from .i18n import CODE_PATTERN, DEFAULT_LANGUAGE, FILE_EXTENSION, SOURCE_HUB, SOURCE_USER, placeholders, t

LISTED = 25   # how many names a report lists of each kind (it counts them all)


def _listed(names: List[Any]) -> List[Any]:
    return names[:LISTED]


def _read_shape(path: str):
    """What is in the file at ``path`` as far as its shape goes: ``(strings or None, errors, warnings)``."""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except OSError as exc:
        return None, [t("language.reason_unreadable", reason=exc.strerror or str(exc))], []
    except ValueError as exc:   # includes bytes that are not UTF-8
        return None, [t("language.reason_json", reason=exc)], []
    if not isinstance(data, dict):
        return None, [t("language.reason_not_object")], []
    warnings = []
    name = data.get("language")
    if not isinstance(name, str) or not name.strip():
        warnings.append(t("language.reason_no_name"))
    strings = data.get("strings")
    if not isinstance(strings, dict):
        return None, [t("language.reason_no_strings")], warnings
    return strings, [], warnings


def _classify(key: str, text: Any, english: Dict[str, str]) -> str:
    """Which group a text of a language file belongs to: ``not_text``, ``unknown`` (English has no such key), ``placeholders`` (not
    the same {placeholders} as English's) or ``ok``."""
    if not isinstance(text, str):
        return "not_text"
    if key not in english:
        return "unknown"
    return "ok" if placeholders(text) == placeholders(english[key]) else "placeholders"


def _tally(report: Dict[str, Any], key: str, text: Any, english: Dict[str, str], groups: Dict[str, list]) -> None:
    """Count one text of a language file in ``report``, or file its key under its group in ``groups``.
    Five parameters because it updates both the report and the groups."""
    group = _classify(key, text, english)
    if group == "ok":
        report["translated"] += 1
        if text == english[key]:
            report["same_as_english"] += 1
    elif group == "placeholders":
        groups[group].append({"key": key, "expected": sorted(placeholders(english[key])), "found": sorted(placeholders(text))})
    else:
        groups[group].append(key)


def check_file(path: str, english: Dict[str, str]) -> Dict[str, Any]:
    """The report on the file at ``path``: ``errors`` (why it cannot be used), ``warnings``, the counts, and the names that need a look.
    ``english`` is the reference (the shipped English's texts)."""
    strings, errors, warnings = _read_shape(path)
    report: Dict[str, Any] = {"errors": errors, "warnings": warnings, "total": len(english), "translated": 0, "same_as_english": 0,
                              "missing_count": 0, "missing": [], "placeholder_count": 0, "placeholders": [],
                              "not_text_count": 0, "not_text": [], "unknown_count": 0, "unknown": []}
    if strings is None:
        return report
    groups: Dict[str, list] = {"not_text": [], "unknown": [], "placeholders": []}
    for key, text in strings.items():
        _tally(report, key, text, english, groups)
    mismatched, not_text, unknown = groups["placeholders"], groups["not_text"], groups["unknown"]
    missing = [key for key in english if key not in strings]
    if not report["translated"]:
        report["errors"].append(t("language.reason_no_texts"))
    report.update(missing_count=len(missing), missing=_listed(missing), placeholder_count=len(mismatched), placeholders=_listed(mismatched),
                  not_text_count=len(not_text), not_text=_listed(not_text), unknown_count=len(unknown), unknown=_listed(unknown))
    return report


def check_language(code: str, shipped: Optional[str] = None, user: Optional[str] = None, hub: Optional[str] = None) -> Dict[str, Any]:
    """The report on the language called ``code``. Raises ``ValueError`` when there is none."""
    language = i18n.find(code, shipped, user, hub)
    if language is None:
        raise ValueError(t("language.not_available", code=str(code)))
    english = i18n.load(DEFAULT_LANGUAGE, shipped, "", "")
    return dict(check_file(language.path, english), code=language.code, name=language.name, source=language.source)


def invalid_files(user: Optional[str] = None, hub: Optional[str] = None) -> List[Dict[str, str]]:
    """The files in the user's and the hub's folders that look like language files but cannot be used, with why: the list of languages
    leaves them out, and without this the user would not know. ``[{"file", "source", "reason"}]``."""
    user = user if user is not None else i18n.user_dir()
    hub = hub if hub is not None else i18n.hub_dir()
    found: List[Dict[str, str]] = []
    for folder, source in ((hub, SOURCE_HUB), (user, SOURCE_USER)):
        names = sorted(os.listdir(folder)) if folder and os.path.isdir(folder) else []
        reasons = [(name, _invalid_reason(folder, name)) for name in names]
        found += [{"file": name, "source": source, "reason": reason} for name, reason in reasons if reason]
    return found


def _invalid_reason(folder: str, name: str) -> str:
    """Why the file ``name`` in ``folder`` is not a usable language file, or "" when it is one (or is not a language file at all)."""
    code, extension = os.path.splitext(name)
    path = os.path.join(folder, name)
    if extension.lower() != FILE_EXTENSION or not os.path.isfile(path):
        return ""
    if not CODE_PATTERN.match(code):
        return t("language.reason_file_name")
    errors = _read_shape(path)[1]   # the shape only: whether it can be read as a language at all
    return errors[0] if errors else ""
