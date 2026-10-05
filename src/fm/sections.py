"""The sections of a Fusion Manage workspace and which section holds each field.

An item is created or edited by sending its field values grouped by section, so every field a
publish sets has to be placed in its section. ``GET /api/v3/workspaces/{id}/sections`` only lists the
sections (link and title); each section's own link gives its fields. Fields inside a matrix (a grid of
fields) belong to the section too.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from ..core.logging_setup import get_logger
from .client import WORKSPACES, FmApiError, FmClient

log = get_logger("fm.sections")

_FIELD_ID = re.compile(r"/fields/([^/]+)/?$")
READERS = 4   # section details read at once


def parse_sections(data: Any) -> Dict[str, str]:
    """``{field id: section link}`` from a ``/sections`` answer, e.g. ``{"TITLE": "/api/v3/workspaces/242/sections/551"}``."""
    out: Dict[str, str] = {}

    def add(node: Any, section: str) -> None:
        if not isinstance(node, dict):
            return
        match = _FIELD_ID.search(_link(node))
        if match:
            out.setdefault(match.group(1), section)

    for section in data:
        link = _link(section)
        if not link:
            continue
        for field in section.get("fields") or []:
            add(field, link)
        for matrix in section.get("matrices") or []:
            for row in matrix.get("fields") or [] if isinstance(matrix, dict) else []:
                for field in row if isinstance(row, list) else []:
                    add(field, link)
    return out


def _link(node: Any) -> str:
    return str(node.get("__self__") or node.get("link") or "") if isinstance(node, dict) else ""


class SectionService:
    """Reads a workspace's sections through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def field_sections(self, workspace_id: str) -> Dict[str, str]:
        """``{field id: section link}`` for every field of the workspace."""
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/sections")
        listed = (data.get("sections") or data.get("items") or []) if isinstance(data, dict) else data
        entries = [e for e in listed if isinstance(e, dict)] if isinstance(listed, list) else []
        # The list holds links only; a section carrying its fields already needs no second read.
        with ThreadPoolExecutor(max_workers=READERS) as pool:
            details = list(pool.map(lambda e: e if "fields" in e or not _link(e) else self._client.get_json(_link(e)), entries))
        fields = parse_sections(details)
        if not fields:   # say so now, instead of every item failing with "not in any section"
            log.error("No fields found in the sections of workspace %s: %r", workspace_id, str(data)[:500])
            raise FmApiError(f"Could not read the fields of workspace {workspace_id}'s sections "
                             f"(answer was {type(data).__name__}).")
        return fields
