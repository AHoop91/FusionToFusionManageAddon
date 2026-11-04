"""Palette actions for the language of the panels."""

import json
import os
import subprocess
import sys
from typing import Any, Callable, Dict, Optional

from ...config.hub_languages import clean, shareable
from ...config.language_setting import read_language, write_language
from ...core import i18n, language_check
from ...core.i18n import t
from ..message_bridge import MessageBridge

LANGUAGE_CHANGED = "language_changed"   # pushed to every open panel, which loads itself again in the new language


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _in_hub(language: i18n.Language) -> str:
    """Is a language of the user's own in the hub, as far as this computer knows (the Hub Admin's last publish, or the last file read from
    it)? ``"none"``, ``"same"`` (the hub has this file's content) or ``"different"`` (the hub has an older version)."""
    folder = i18n.hub_dir()
    path = os.path.join(folder, language.code + ".json") if folder else ""
    if not path or not os.path.isfile(path):
        return "none"
    mine, kept = clean({language.code: _read_json(language.path)}).get(language.code), _read_json(path)   # as it would be put in the file
    same = mine is not None and kept is not None and mine == {"language": kept.get("language"), "strings": kept.get("strings")}
    return "same" if same else "different"


def _sharing(language: i18n.Language, shipped: Optional[str], user: Optional[str]) -> Dict[str, Any]:
    """Where a language of the user's own is: ``included`` (it goes in the hub's Configuration File when published, ``reason`` says why not),
    and ``hub`` (whether the hub has it already: see ``_in_hub``)."""
    hub = _in_hub(language)
    if not shareable(language.code):
        return {"included": False, "reason": t("language.share_reason_code"), "hub": hub}
    errors = language_check.check_language(language.code, shipped, user, "")["errors"]
    return {"included": not errors, "reason": errors[0] if errors else "", "hub": hub}


def language_payload(shipped: Optional[str] = None, user: Optional[str] = None) -> Dict[str, Any]:
    """The language in use with its strings, the languages to choose from (the user's own say whether the hub gets them), and the folder to
    make a new one in."""
    folder = user if user is not None else i18n.user_dir()
    languages = []
    for language in i18n.available(shipped, user):
        entry = language.to_dict()
        if language.source == i18n.SOURCE_USER:
            entry["sharing"] = _sharing(language, shipped, user)
        languages.append(entry)
    return {
        "code": i18n.active_code(),
        "strings": i18n.active_strings(),
        "languages": languages,
        "invalid": language_check.invalid_files(user),   # files in the user's and the hub's folders that cannot be used, and why
        "restart": i18n.restart_needed(),   # the ribbon's text was built in another language: it follows after Fusion is restarted
        "user_dir": folder or "",
        "shipped_dir": shipped if shipped is not None else i18n.shipped_dir(),
    }


def set_language(payload: Dict[str, Any], folder: Optional[str] = None, shipped: Optional[str] = None, user: Optional[str] = None) -> Dict[str, Any]:
    """Use the language in ``payload["code"]`` and keep it as the user's choice. Raises ``ValueError`` for a code that is not available."""
    code = str(payload.get("code") or "").strip()
    language = i18n.find(code, shipped, user)
    if language is None:
        raise ValueError(t("language.not_available", code=code))
    errors = language_check.check_language(language.code, shipped, user)["errors"] if language.source != i18n.SOURCE_SHIPPED else []
    if errors:
        raise ValueError(t("language.cannot_use", name=language.name, reason=errors[0]))
    write_language(language.code, folder)
    i18n.set_language(language.code, shipped, user)
    return language_payload(shipped, user)


def check_language(payload: Dict[str, Any], shipped: Optional[str] = None, user: Optional[str] = None) -> Dict[str, Any]:
    """The report on the language in ``payload["code"]``: does its file map onto English's? (See ``core.language_check``.)"""
    return language_check.check_language(str(payload.get("code") or ""), shipped, user)


def new_language(payload: Dict[str, Any], shipped: Optional[str] = None, user: Optional[str] = None) -> Dict[str, Any]:
    """Make a language file for the user to translate (see ``i18n.create``); answers the languages as now found, and the file made."""
    path = i18n.create(str(payload.get("code") or ""), str(payload.get("name") or ""), shipped, user)
    return dict(language_payload(shipped, user), created=path)


def _open_in_system(folder: str) -> None:
    """Show ``folder`` in the system's file browser."""
    if sys.platform == "win32":
        os.startfile(folder)   # noqa: S606 - the folder is the add-in's own, never taken from a request
    else:
        subprocess.run(["open", folder], check=False)


def open_language_folder(user: Optional[str] = None, opener: Callable[[str], None] = _open_in_system) -> Dict[str, Any]:
    """Open the folder of the user's language files (made when it is not there yet). Nothing in a request says which folder."""
    folder = user if user is not None else i18n.user_dir()
    if not folder:
        raise ValueError("The settings folder is not known, so the languages folder cannot be opened.")
    os.makedirs(folder, exist_ok=True)
    opener(folder)
    return {}


def _edit_in_system(path: str) -> None:
    """Open the file in the editor the user has chosen: the program Windows has for editing a .json file (its "edit" action, then its "open"
    one), and Notepad when there is none. Elsewhere, the system's text editor."""
    if sys.platform == "win32":
        for verb in ("edit", "open"):
            try:
                os.startfile(path, verb)   # noqa: S606 - the path is that of a language file the add-in found, never taken from a request
                return
            except OSError:   # no program is set for this action
                continue
        subprocess.Popen(["notepad.exe", path])   # noqa: S603
    else:
        subprocess.run(["open", "-t", path], check=False)


def _own(code: str, shipped: Optional[str], user: Optional[str]) -> i18n.Language:
    """The language of the user's own with this code: the only kind that can be edited or deleted. Raises ``ValueError`` for any other."""
    language = i18n.find(str(code or "").strip(), shipped, user, "")
    if language is None or language.source != i18n.SOURCE_USER:
        raise ValueError(t("language.not_own", code=str(code)))
    return language


def edit_language(payload: Dict[str, Any], shipped: Optional[str] = None, user: Optional[str] = None,
                  opener: Callable[[str], None] = _edit_in_system) -> Dict[str, Any]:
    """Open the file of a language of the user's own in a text editor. The file is the one the add-in found, never a path from the request."""
    language = _own(payload.get("code"), shipped, user)
    opener(language.path)
    return {"code": language.code, "name": language.name}


def delete_language(payload: Dict[str, Any], folder: Optional[str] = None, shipped: Optional[str] = None,
                    user: Optional[str] = None) -> Dict[str, Any]:
    """Delete the file of a language of the user's own. When it is the language in use (or the one kept as the user's choice), English is
    used instead. Answers the languages as now found."""
    language = _own(payload.get("code"), shipped, user)
    os.remove(language.path)
    if read_language(folder).lower() == language.code.lower():
        write_language(i18n.DEFAULT_LANGUAGE, folder)
    if i18n.active_code().lower() == language.code.lower():
        i18n.set_language(i18n.DEFAULT_LANGUAGE, shipped, user)
    return language_payload(shipped, user)


def register_language_actions(bridge: MessageBridge, push: Callable[[str, str], None] = None, rebuild: Callable[[], None] = None) -> None:
    """Register the language actions, for anyone: the languages are the user's own, on their computer. (Only publishing them to the hub is a
    Hub Admin's, and that is the Save & Publish of the hub's Configuration File.) A change of language is pushed to the open panels when
    ``push`` is given. ``rebuild`` (given by the add-in) makes the ribbon and the panel titles again in the language in use, which Fusion fixes
    once built: it is the Restart button of the notice, not done by itself."""
    def announce() -> None:
        if push:
            push(LANGUAGE_CHANGED, "{}")

    def change(payload: Dict[str, Any]) -> Dict[str, Any]:
        result = set_language(payload)   # also when the code is the one in use: its file may have been edited
        announce()
        return result

    bridge.register("get_language", lambda _payload: language_payload())
    bridge.register("set_language", change)
    bridge.register("check_language", lambda payload: check_language(payload))
    bridge.register("new_language", lambda payload: new_language(payload))
    bridge.register("open_language_folder", lambda _payload: open_language_folder())
    bridge.register("edit_language", lambda payload: edit_language(payload))
    bridge.register("restart_addin", lambda _payload: restart_addin(rebuild))

    def delete(payload: Dict[str, Any]) -> Dict[str, Any]:
        before = i18n.active_code()
        result = delete_language(payload)
        if result["code"] != before:   # the language in use was the one deleted: English is used again
            announce()
        return result

    bridge.register("delete_language", delete)


def restart_addin(rebuild: Optional[Callable[[], None]]) -> Dict[str, Any]:
    """Ask the add-in to start again, so what Fusion fixes when it is built (the ribbon, the palette titles) follows the language in use."""
    if rebuild is None:
        raise ValueError(t("language.restart_unavailable"))
    rebuild()
    return {}


def start_language() -> str:
    """Use the user's choice, at start-up. Answers the code in use."""
    code = i18n.set_language(read_language())
    i18n.mark_ribbon()   # what is built from here on (the ribbon, the palette titles) is in this language
    return code
