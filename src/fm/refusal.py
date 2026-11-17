"""What Fusion Manage says when it refuses a write, read for the form to show: a message for the whole form, and one for each field it names.

A refusal is ``{"message": ..., "errors": [{"message": ...}, ...]}``: every ``message`` in it is read. A message belongs to a field when the
entry it is in names one (any of its values is a field id, or the link of one), or else when the message itself names one as a word. A message
that names no field is for the whole form. What is not understood is shown as it was said.
"""

import json
import re
from typing import Any, Dict, List, Set, Tuple

from .client import FmApiError

MAX_DEPTH = 6   # how deep into the answer a message is looked for


class FmRefused(FmApiError):
    """A refusal read for the form: ``fields`` is ``{field id: what is wrong with it}``, and the message (``str``) is for the form as a whole."""

    def __init__(self, message: str, status: int, fields: Dict[str, str]) -> None:
        super().__init__(message, status)
        self.fields = fields


def _field_named(node: Dict[str, Any], known: Set[str]) -> str:
    """The field an entry of the refusal names ("" when none): one of its values is a field id, or a link ending in ``/fields/<id>``."""
    for value in node.values():
        if isinstance(value, str):
            if value in known:
                return value
            tail = value.rstrip("/").rsplit("/", 1)[-1]
            if "/fields/" in value and tail in known:
                return tail
    return ""


def _field_in(message: str, known: Set[str]) -> str:
    """A field id the text names as a word ("" when none): the longest, so ``PLANNED_DATE_10`` is not taken for ``PLANNED_DATE_1``."""
    for field in sorted(known, key=len, reverse=True):
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(field) + r"(?![A-Za-z0-9_])", message):
            return field
    return ""


def _walk(node: Any, known: Set[str], found: List[Tuple[str, str]], depth: int = 0) -> None:
    """Collect ``(field id or "", message)`` from every entry of the refusal that has a message."""
    if depth > MAX_DEPTH:
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, known, found, depth + 1)
        return
    if not isinstance(node, dict):
        return
    message = node.get("message")
    if isinstance(message, str) and message.strip():
        message = message.strip()
        found.append((_field_named(node, known) or _field_in(message, known), message))
    for value in node.values():
        if isinstance(value, (list, dict)):
            _walk(value, known, found, depth + 1)


def read_refusal(exc: FmApiError, known: Set[str], general: str) -> FmApiError:
    """The refusal ``exc`` as an ``FmRefused`` for the form, or ``exc`` itself when it has nothing to read (no body, or one with no messages).

    ``known`` is the ids of the fields of the form; ``general`` is what to say for the whole form when the refusal names fields only."""
    body = exc.body
    if not body:
        return exc
    try:
        found: List[Tuple[str, str]] = []
        _walk(json.loads(body), known, found)
    except ValueError:
        return exc
    fields: Dict[str, str] = {}
    whole: List[str] = []
    for field, message in found:
        if field:
            fields.setdefault(field, message)
        elif message not in whole:
            whole.append(message)
    if not fields and not whole:
        return exc
    return FmRefused(" ".join(whole) if whole else general, exc.status, fields)
