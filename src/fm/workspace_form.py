"""The form for a new item of a workspace: its sections and the fields in each that a person can fill in (and, as Fusion Manage does, the
fields it only describes, such as the number it gives the item).

``GET /api/v3/workspaces/{id}/fields`` describes each field (type, picklist, whether it can be edited), and the workspace's sections say
which fields each holds and in which order (see ``sections``). A field that cannot be filled in is left out: one Fusion Manage works out, one
nobody can edit that says nothing about itself, one hidden from the form, and the kinds of field the form has no control for (grids of
values the form cannot show).

A field is required when its ``fieldValidators`` hold a ``required`` validator. The first rows of the answer are written to the log. Fusion
Manage refuses what is missing in any case, and the form shows what it said.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Set

from ..core.i18n import t
from ..core.logging_setup import get_logger, log_body
from ..core.shapes import as_dict, as_list, dict_rows, rows_in, whole
from .client import WORKSPACES, FmApiError, FmClient, id_of, last_segment
from .item_view import COLUMN_KEYS, ROW_KEYS, layout_names, not_shown
from .pages import field_id
from .sections import SectionService
from .workspace import GRID_VIEW, WorkspaceService, is_computed

log = get_logger("fm.workspace_form")

READERS = 4   # picklists read at once
LOG_ROWS = 3   # field rows of the answer a verbose log keeps

# the control a field gets, by what its type's title says
TEXT, TEXTAREA, INTEGER, NUMBER, DATE, CHECKBOX, SELECT, RADIO, INFO, LINK, LINKS, IMAGE, AUTO = (
    "text", "textarea", "integer", "number", "date", "checkbox", "select", "radio", "info", "link", "links", "image", "auto")
_KINDS = (("paragraph", TEXTAREA), ("check", CHECKBOX), ("integer", INTEGER), ("float", NUMBER), ("currency", NUMBER), ("decimal", NUMBER),
          ("number", NUMBER), ("date", DATE), ("text", TEXT), ("alpha", TEXT), ("url", TEXT), ("email", TEXT), ("phone", TEXT))


def _validator_rows(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The validators a field holds, as ``[{"validatorName", "variables"}]``."""
    return dict_rows(row.get("fieldValidators"))


def _required(row: Dict[str, Any]) -> bool:
    """Whether the field must be filled in: it has a ``required`` validator."""
    return any(str(v.get("validatorName") or "").lower() == "required" for v in _validator_rows(row))


def _validators(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The validators of a field as ``[{"name", "variables"}]`` for the form to check. ``required`` and ``maxlength`` are not here: the field says
    those itself (``required``, ``max_length``)."""
    found = []
    for validator in _validator_rows(row):
        name = str(validator.get("validatorName") or "")
        if name and name.lower() not in ("required", "maxlength"):
            found.append({"name": name, "variables": {str(k): str(v) for k, v in as_dict(validator.get("variables")).items()}})
    return found


def _max_length(row: Dict[str, Any], kind: str) -> int:
    """How many characters a text field takes (0 for no limit): the smaller of its ``maxlength`` validator and its ``fieldLength``."""
    if kind not in (TEXT, TEXTAREA):
        return 0
    limits = [whole(as_dict(v.get("variables")).get("maxlength")) for v in _validator_rows(row) if str(v.get("validatorName") or "").lower() == "maxlength"]
    limits.append(whole(row.get("fieldLength")))
    return min((n for n in limits if n > 0), default=0)


def _kind(row: Dict[str, Any], options: Dict[str, List[Dict[str, str]]]) -> Optional[str]:
    """The control for a field, or None when the form has none for it."""
    lookup = last_segment(row.get("picklist"))
    kind = row.get("type")
    title = str(kind.get("title") if isinstance(kind, dict) else kind or "").lower()
    if row.get("picklistFieldDefinition") and lookup:   # items of another workspace, found by searching their lookup
        return LINKS if "multi" in title else LINK
    if lookup in options:
        return RADIO if "radio" in title else SELECT
    if "image" in title:
        return IMAGE
    return next((kind for word, kind in _KINDS if word in title), None)


def _spec(field_id: str, by_id: Dict[str, Dict[str, Any]], options: Dict[str, List[Dict[str, str]]], placed: Set[str],
          left_out: List[str]) -> Optional[Dict[str, Any]]:
    """The form's description of a field (``id``, ``title``, ``kind``, ``required``, ``options``), or None when it is not to be filled in here."""
    row = by_id.get(field_id)
    if row is None or field_id in placed or not_shown(row, set()) or is_computed(row):
        return None
    title = str(row.get("name") or field_id)
    description = str(row.get("description") or "").strip()
    if row.get("editability") == "NEVER":   # Fusion Manage shows it with what it says about it (the number, for one, is given when the item is saved)
        if not description:
            return None
        placed.add(field_id)
        return {"id": field_id, "title": title, "kind": INFO, "required": False, "options": [], "lookup": "", "description": description, "max_length": 0, "validators": []}
    placed.add(field_id)
    kind = _kind(row, options)
    if kind is None:
        left_out.append(field_id)
        log.info("No control for field %s", field_id)
        log_body(log, "the definition of", {k: row.get(k) for k in ("type", "picklist", "picklistFieldDefinition", "editability", "fieldLength")}, field_id)
        return None
    lookup = last_segment(row.get("picklist"))
    return {"id": field_id, "title": title, "kind": kind, "required": _required(row), "description": description,
            "options": options.get(lookup, []) if kind in (SELECT, RADIO) else [], "lookup": lookup if kind in (LINK, LINKS) else "",
            "max_length": _max_length(row, kind), "validators": _validators(row)}


def _matrix(grid: Dict[str, Any], spec: Callable[[str], Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """A grid of fields of a section as ``{"columns", "labels", "rows": [[field or None]]}``; a row or column with nothing to fill in is left out.
    The columns and rows are named as the Item panel names them: by the layout, else the titles of the first row's fields."""
    layout = [row for row in as_list(grid.get("fields")) if isinstance(row, list)]
    if not layout:
        return {}
    width = max(len(row) for row in layout)
    cells = [[spec(field_id(row[c])) if c < len(row) and field_id(row[c]) else None for c in range(width)] for row in layout]
    columns_kept = [c for c in range(width) if any(row[c] for row in cells)]
    rows_kept = [r for r, row in enumerate(cells) if any(row[c] for c in columns_kept)] if columns_kept else []
    if not rows_kept:
        return {}
    names = layout_names(grid, COLUMN_KEYS)
    columns = ([names[c] for c in columns_kept] if len(names) == width
               else [next((cells[r][c]["title"] for r in rows_kept if cells[r][c]), "") for c in columns_kept])
    labels = layout_names(grid, ROW_KEYS)
    return {"columns": columns, "labels": [labels[r] for r in rows_kept] if len(labels) == len(layout) else [""] * len(rows_kept),
            "rows": [[cells[r][c] for c in columns_kept] for r in rows_kept]}


def _automatic(spec: Dict[str, Any]) -> Dict[str, Any]:
    """A field the add-in fills in itself: shown, but with nothing to enter, and never sent."""
    return {**spec, "kind": AUTO, "required": False, "options": [], "lookup": "", "max_length": 0, "validators": [],
            "description": t("data.workspace_auto_filled")}


def parse_form(rows: List[Dict[str, Any]], sections: List[Dict[str, Any]], options: Dict[str, List[Dict[str, str]]],
               automatic: Set[str] = frozenset()) -> Dict[str, Any]:
    """``{"sections": [{"title", "fields": [field], "matrices": [matrix], "collapsed"}], "left_out": [field id]}`` (a field is as ``_spec`` gives it, a matrix
    as ``_matrix`` does).

    ``options`` is the options of each picklist by its name. ``automatic`` are the ids of fields the add-in fills in itself (shown with nothing to
    enter). ``left_out`` are the fields that are in a section but have no control, for the log."""
    by_id = {id_of(row): row for row in rows if id_of(row)}
    placed: Set[str] = set()
    left_out: List[str] = []

    def spec(field: str) -> Optional[Dict[str, Any]]:
        found = _spec(field, by_id, options, placed, left_out)
        return _automatic(found) if found and field in automatic else found

    form: List[Dict[str, Any]] = []
    for section in sections:
        fields = [found for found in (spec(field_id(ref)) for ref in as_list(section.get("fields"))) if found]
        matrices = [found for found in (_matrix(grid, spec) for grid in dict_rows(section.get("matrices"))) if found]
        if fields or matrices:
            form.append({"title": str(section.get("title") or section.get("name") or ""), "fields": fields, "matrices": matrices,
                         "collapsed": section.get("collapsed") is True})   # the section says whether it starts folded
    return {"sections": form, "left_out": left_out}


class WorkspaceFormService:
    """Reads the form of a workspace through an ``FmClient``."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def form(self, workspace_id: str, automatic: Set[str] = frozenset()) -> Dict[str, Any]:
        """The form for a new item (see ``parse_form``; ``automatic`` is the ids of the fields filled in by the add-in). Raises ``FmApiError`` or ``AuthError`` when the workspace cannot be read."""
        with ThreadPoolExecutor(max_workers=2) as pair:   # the fields and the sections do not depend on each other
            sections_read = pair.submit(SectionService(self._client).layouts, workspace_id, True)
            data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/fields")
            sections = list(sections_read.result().values())
        rows = rows_in(data, "fields")
        log.info("Form of workspace %s: %d field(s)", workspace_id, len(rows))
        log_body(log, "the first fields of", rows[:LOG_ROWS], str(workspace_id))
        form = parse_form(rows, sections, self._options(rows), automatic)
        log.info("Form of workspace %s: %s; left out for want of a control: %s", workspace_id,
                 [(s["title"], [f["id"] for f in s["fields"]], len(s["matrices"])) for s in form["sections"]], form["left_out"])
        return form

    def _options(self, rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
        """The options of each fixed picklist the fields use, by the name of the picklist (read a few at a time)."""
        lookups = sorted({last_segment(r.get("picklist")) for r in rows if r.get("picklist") and not r.get("picklistFieldDefinition")
                          and r.get("editability") != "NEVER"} - {""})
        service = WorkspaceService(self._client)
        with ThreadPoolExecutor(max_workers=READERS) as pool:
            return {lookup: found for lookup, found in zip(lookups, pool.map(service.options, lookups)) if found}

    def _with_validators(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The list of a grid's columns gives a column's validators as a link (``validators``) to read, not as ``fieldValidators``: each link is
        read (a list of ``{"validatorName", "variables"}``), and what it holds is put on the row as ``fieldValidators``. Raises ``FmApiError``."""
        def read(row: Dict[str, Any]) -> Dict[str, Any]:
            link = row.get("validators")
            if row.get("fieldValidators") or not isinstance(link, str) or not link:
                return row
            return {**row, "fieldValidators": dict_rows(self._client.get_json(link))}
        with ThreadPoolExecutor(max_workers=READERS) as pool:
            return list(pool.map(read, rows))

    def grid_form(self, workspace_id: str, link_column: str) -> Dict[str, Any]:
        """The columns of the workspace's Grid tab a person can fill in for a row, as ``{"fields": [field]}`` (a field is as ``_spec`` gives it).
        ``link_column`` is the column that links the row to its component: it is set from the component, so it is not asked for.
        Raises ``FmApiError`` or ``AuthError`` when the grid cannot be read."""
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/views/{GRID_VIEW}/fields")
        rows = self._with_validators(rows_in(data, "fields"))
        log.info("Grid of workspace %s: %d column(s)", workspace_id, len(rows))
        log_body(log, "the first columns of", rows[:LOG_ROWS], str(workspace_id))
        options = self._options(rows)
        by_id = {id_of(row): row for row in rows if id_of(row)}
        placed: Set[str] = set()
        left_out: List[str] = []
        specs = [spec for field in by_id if field != link_column and (spec := _spec(field, by_id, options, placed, left_out))]
        log.info("Grid form of workspace %s: %s; left out for want of a control: %s", workspace_id, [s["id"] for s in specs], left_out)
        return {"fields": [s for s in specs if s["kind"] != INFO]}
