"""The sections of a Fusion Manage workspace and which section holds each field.

An item is created or edited by sending its field values grouped by section, so every field a
publish sets has to be placed in its section. ``GET /api/v3/workspaces/{id}/sections`` only lists the
sections (link and title); each section's own link gives its fields. Fields inside a matrix (a grid of
fields) belong to the section too.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterator, List

from ..core.logging_setup import get_logger
from ..core.shapes import as_dict, as_list, dict_rows, rows_in
from .client import WORKSPACES, FmApiError, FmClient, last_segment
from .pages import field_id
from .ttl_cache import TtlCache

log = get_logger("fm.sections")

READERS = 4   # section details read at once
LOG_CHARS = 500   # of a sections answer that held no fields, kept in the log


def _link(node: Any) -> str:
    """The API link of a section ("" when it names none)."""
    node = as_dict(node)
    return str(node.get("__self__") or node.get("link") or "")


def _field_refs(section: Dict[str, Any]) -> Iterator[Any]:
    """The field references of a section: its own fields, then the fields in the grids (matrices) it holds."""
    yield from as_list(section.get("fields"))
    for matrix in dict_rows(section.get("matrices")):
        for row in as_list(matrix.get("fields")):
            yield from as_list(row)


def parse_sections(data: Any) -> Dict[str, str]:
    """``{field id: section link}`` from a ``/sections`` answer, e.g. ``{"TITLE": "/api/v3/workspaces/242/sections/551"}``.
    A field that two sections name belongs to the first."""
    out: Dict[str, str] = {}
    for section in dict_rows(data):
        link = _link(section)
        for ref in _field_refs(section) if link else ():
            field = field_id(ref)
            if field:
                out.setdefault(field, link)
    return out


class SectionService:
    """Reads a workspace's sections through an ``FmClient``."""

    _cache = TtlCache()   # (tenant, workspace id) -> {field id: section link}; a workspace's layout rarely changes
    _details_cache = TtlCache()   # (tenant, workspace id) -> the sections

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def field_sections(self, workspace_id: str) -> Dict[str, str]:
        """``{field id: section link}`` for every field of the workspace."""
        key = (self._client.tenant, workspace_id)
        cached = self._cache.get(key)
        return cached if cached is not None else self._cache.put(key, self._read(workspace_id))

    def layouts(self, workspace_id: str) -> Dict[str, Dict[str, Any]]:
        """``{section id: the section as the workspace lays it out}``: its fields and its matrices (grids of fields)."""
        return {last_segment(_link(s)): s for s in self._details(workspace_id) if _link(s)}

    def _details(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Every section of the workspace with its fields and matrices (read once, then shared for a few minutes)."""
        key = (self._client.tenant, workspace_id)
        cached = self._details_cache.get(key)
        if cached is not None:
            return cached
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/sections")
        entries = rows_in(data, "sections") or rows_in(data, "items")   # the list itself, or held under either name
        with ThreadPoolExecutor(max_workers=READERS) as pool:
            details = list(pool.map(self._detail, entries))
        return self._details_cache.put(key, details)

    def _detail(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """The section ``entry`` stands for with its fields. The list holds links only; an entry that carries its fields needs no second read."""
        if "fields" in entry or not _link(entry):
            return entry
        return as_dict(self._client.get_json(_link(entry)))

    def _read(self, workspace_id: str) -> Dict[str, str]:
        details = self._details(workspace_id)
        fields = parse_sections(details)
        if not fields:   # say so now, instead of every item failing with "not in any section"
            log.error("No fields found in the sections of workspace %s: %r", workspace_id, str(details)[:LOG_CHARS])
            raise FmApiError(f"Could not read the fields of workspace {workspace_id}'s sections ({len(details)} section(s) came back, none with a field).")
        return fields
