"""What Fusion Manage says when it refuses a write, read for the form to show: a message for the whole form, and one for each field it names.

A refusal is ``{"message": ..., "errors": [{"message": ...}, ...]}``: every ``message`` in it is read. A message belongs to a field when the
entry it is in names one (any of its values is a field id, or the link of one), or else when the message itself names one as a word. A message
that names no field is for the whole form. What is not understood is shown as it was said.

``refusal_text`` is the same refusal in plain words, for a log or a message that is not tied to a form.
"""

import json
import re
from typing import Any, Dict, Iterator, List, Set

from ..core.shapes import as_dict
from .client import FmApiError, last_segment

MAX_DEPTH = 6   # how deep into the answer a message is looked for


class FmRefused(FmApiError):
    """A refusal read for the form: ``fields`` is ``{field id: what is wrong with it}``, and the message (``str``) is for the form as a whole."""

    def __init__(self, message: str, status: int, fields: Dict[str, str]) -> None:
        super().__init__(message, status)
        self.fields = fields


def _field_named(node: Dict[str, Any], known: Set[str]) -> str:
    """The field an entry of the refusal names ("" when none): one of its values is a field id, or a link ending in ``/fields/<id>``."""
    for value in node.values():
        if not isinstance(value, str):
            continue
        if value in known:
            return value
        tail = last_segment(value)
        if "/fields/" in value and tail in known:
            return tail
    return ""


def _field_in(message: str, known: Set[str]) -> str:
    """A field id the text names as a word ("" when none): the longest, so ``PLANNED_DATE_10`` is not taken for ``PLANNED_DATE_1``."""
    for field in sorted(known, key=len, reverse=True):
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(field) + r"(?![A-Za-z0-9_])", message):
            return field
    return ""


def _entries(node: Any, depth: int = 0) -> Iterator[Dict[str, Any]]:
    """Every entry of the refusal that has a message, however deep (down to ``MAX_DEPTH``)."""
    if depth > MAX_DEPTH:
        return
    if isinstance(node, list):
        for item in node:
            yield from _entries(item, depth + 1)
    elif isinstance(node, dict):
        message = node.get("message")
        if isinstance(message, str) and message.strip():
            yield node
        for value in node.values():
            if isinstance(value, (list, dict)):
                yield from _entries(value, depth + 1)


def _messages_of(exc: FmApiError) -> List[Dict[str, Any]]:
    """The entries with a message in the body of a refusal; none when it has no body or the body is not JSON."""
    try:
        return list(_entries(json.loads(exc.body)))
    except ValueError:
        return []


def read_refusal(exc: FmApiError, known: Set[str], general: str) -> FmApiError:
    """The refusal ``exc`` as an ``FmRefused`` for the form, or ``exc`` itself when it has nothing to read (no body, or one with no messages).

    ``known`` is the ids of the fields of the form; ``general`` is what to say for the whole form when the refusal names fields only."""
    fields: Dict[str, str] = {}
    whole: List[str] = []
    for entry in _messages_of(exc):
        message = entry["message"].strip()
        field = _field_named(entry, known) or _field_in(message, known)
        if field:
            fields.setdefault(field, message)
        elif message not in whole:
            whole.append(message)
    if not fields and not whole:
        return exc
    return FmRefused(" ".join(whole) if whole else general, exc.status, fields)


def _line(entry: Dict[str, Any]) -> str:
    """One message of the refusal in words: the field it names by title first, and its ``arguments`` put in place of ``{0}``, ``{1}``..."""
    message = entry["message"].strip()
    arguments = entry.get("arguments")
    for number, argument in enumerate(arguments if isinstance(arguments, list) else []):
        message = message.replace("{%d}" % number, str(argument))
    title = as_dict(entry.get("field")).get("title")
    return f"{title}: {message}" if title else message


def refusal_text(exc: Exception) -> str:
    """What Fusion Manage said in a refusal, in words and all of it (every message, not the start of the raw answer); the error's own text
    when it said nothing that can be read, or is not a refusal."""
    if not isinstance(exc, FmApiError):
        return str(exc)
    return " ".join(dict.fromkeys(_line(e) for e in _messages_of(exc))) or str(exc)
