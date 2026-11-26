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
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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


def _info_spec(field_id: str, title: str, description: str) -> Dict[str, Any]:
    """The description of a field nobody can edit but that says something about itself (``kind`` is ``INFO``)."""
    return {"id": field_id, "title": title, "kind": INFO, "required": False, "options": [], "lookup": "", "description": description, "max_length": 0, "validators": []}


def _control_spec(field_id: str, row: Dict[str, Any], kind: str, options: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """The description of a field that has the control ``kind``."""
    lookup = last_segment(row.get("picklist"))
    return {"id": field_id, "title": str(row.get("name") or field_id), "kind": kind, "required": _required(row),
            "description": str(row.get("description") or "").strip(),
            "options": options.get(lookup, []) if kind in (SELECT, RADIO) else [], "lookup": lookup if kind in (LINK, LINKS) else "",
            "max_length": _max_length(row, kind), "validators": _validators(row)}


def _automatic(spec: Dict[str, Any]) -> Dict[str, Any]:
    """A field the add-in fills in itself: shown, but with nothing to enter, and never sent."""
    return {**spec, "kind": AUTO, "required": False, "options": [], "lookup": "", "max_length": 0, "validators": [],
            "description": t("data.workspace_auto_filled")}


class _FieldSpecs:
    """Describes the fields of a workspace for the form, each once. ``automatic`` are the ids of fields the add-in fills in itself. ``left_out`` collects
    the fields that have no control, for the log."""

    def __init__(self, rows: List[Dict[str, Any]], options: Dict[str, List[Dict[str, str]]], automatic: Set[str] = frozenset()) -> None:
        self.by_id = {id_of(row): row for row in rows if id_of(row)}
        self.left_out: List[str] = []
        self._options = options
        self._automatic = automatic
        self._placed: Set[str] = set()

    def spec(self, field_id: str) -> Optional[Dict[str, Any]]:
        """The form's description of a field (``id``, ``title``, ``kind``, ``required``, ``options``), or None when it is not to be filled in here."""
        found = self._describe(field_id)
        return _automatic(found) if found and field_id in self._automatic else found

    def _describe(self, field_id: str) -> Optional[Dict[str, Any]]:
        row = self.by_id.get(field_id)
        if row is None or field_id in self._placed or not_shown(row, set()) or is_computed(row):
            return None
        self._placed.add(field_id)
        if row.get("editability") == "NEVER":   # Fusion Manage shows it with what it says about it (the number, for one, is given when the item is saved)
            description = str(row.get("description") or "").strip()
            return _info_spec(field_id, str(row.get("name") or field_id), description) if description else None
        kind = _kind(row, self._options)
        if kind is None:
            self._note_left_out(field_id, row)
            return None
        return _control_spec(field_id, row, kind, self._options)

    def _note_left_out(self, field_id: str, row: Dict[str, Any]) -> None:
        """Record a field the form has no control for, and log how Fusion Manage describes it."""
        self.left_out.append(field_id)
        log.info("No control for field %s", field_id)
        log_body(log, "the definition of", {k: row.get(k) for k in ("type", "picklist", "picklistFieldDefinition", "editability", "fieldLength")}, field_id)


def _cell_at(row: List[Any], column: int, spec: Callable[[str], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """The description of the field at ``column`` of a grid row, or None when the row has none there or it is not to be filled in."""
    fid = field_id(row[column]) if column < len(row) else ""
    return spec(fid) if fid else None


def _column_titles(grid: Dict[str, Any], width: int, columns_kept: List[int], kept: List[List[Optional[Dict[str, Any]]]]) -> List[str]:
    """The names of the columns kept: by the layout when it names every column, else the title of the first field in each."""
    names = layout_names(grid, COLUMN_KEYS)
    if len(names) == width:
        return [names[c] for c in columns_kept]
    return [next((row[i]["title"] for row in kept if row[i]), "") for i in range(len(columns_kept))]


def _row_labels(grid: Dict[str, Any], height: int, rows_kept: List[int]) -> List[str]:
    """The names of the rows kept: by the layout when it names every one of its ``height`` rows, else blank."""
    labels = layout_names(grid, ROW_KEYS)
    return [labels[r] for r in rows_kept] if len(labels) == height else [""] * len(rows_kept)


def _kept_positions(cells: List[List[Optional[Dict[str, Any]]]]) -> Tuple[List[int], List[int]]:
    """``(columns, rows)``: the positions in a grid of cells that hold a field, the rows counted only by the columns kept."""
    columns_kept = [c for c in range(len(cells[0])) if any(row[c] for row in cells)]
    rows_kept = [r for r, row in enumerate(cells) if any(row[c] for c in columns_kept)]
    return columns_kept, rows_kept


def _matrix(grid: Dict[str, Any], spec: Callable[[str], Optional[Dict[str, Any]]]) -> Dict[str, Any]:
    """A grid of fields of a section as ``{"columns", "labels", "rows": [[field or None]]}``; a row or column with nothing to fill in is left out.
    The columns and rows are named as the Item panel names them: by the layout, else the titles of the first row's fields."""
    layout = [row for row in as_list(grid.get("fields")) if isinstance(row, list)]
    if not layout:
        return {}
    width = max(len(row) for row in layout)
    cells = [[_cell_at(row, c, spec) for c in range(width)] for row in layout]
    columns_kept, rows_kept = _kept_positions(cells)
    if not rows_kept:
        return {}
    kept = [[cells[r][c] for c in columns_kept] for r in rows_kept]
    return {"columns": _column_titles(grid, width, columns_kept, kept), "labels": _row_labels(grid, len(layout), rows_kept), "rows": kept}


def _section_form(section: Dict[str, Any], spec: Callable[[str], Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """The form's description of a section (``title``, ``fields``, ``matrices``, ``collapsed``), or None when it has nothing to fill in."""
    fields = [found for found in (spec(field_id(ref)) for ref in as_list(section.get("fields"))) if found]
    matrices = [found for found in (_matrix(grid, spec) for grid in dict_rows(section.get("matrices"))) if found]
    if not fields and not matrices:
        return None
    return {"title": str(section.get("title") or section.get("name") or ""), "fields": fields, "matrices": matrices,
            "collapsed": section.get("collapsed") is True}   # the section says whether it starts folded


def parse_form(rows: List[Dict[str, Any]], sections: List[Dict[str, Any]], options: Dict[str, List[Dict[str, str]]],
               automatic: Set[str] = frozenset()) -> Dict[str, Any]:
    """``{"sections": [{"title", "fields": [field], "matrices": [matrix], "collapsed"}], "left_out": [field id]}`` (a field is as ``_FieldSpecs.spec`` gives it, a matrix
    as ``_matrix`` does).

    ``options`` is the options of each picklist by its name. ``automatic`` are the ids of fields the add-in fills in itself (shown with nothing to
    enter). ``left_out`` are the fields that are in a section but have no control, for the log."""
    specs = _FieldSpecs(rows, options, automatic)
    found = (_section_form(section, specs.spec) for section in sections)
    return {"sections": [form for form in found if form], "left_out": specs.left_out}


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
        """The columns of the workspace's Grid tab a person can fill in for a row, as ``{"fields": [field]}`` (a field is as ``_FieldSpecs.spec`` gives it).
        ``link_column`` is the column that links the row to its component: it is set from the component, so it is not asked for.
        Raises ``FmApiError`` or ``AuthError`` when the grid cannot be read."""
        data = self._client.get_json(f"{WORKSPACES}/{workspace_id}/views/{GRID_VIEW}/fields")
        rows = self._with_validators(rows_in(data, "fields"))
        log.info("Grid of workspace %s: %d column(s)", workspace_id, len(rows))
        log_body(log, "the first columns of", rows[:LOG_ROWS], str(workspace_id))
        fields = _FieldSpecs(rows, self._options(rows))
        specs = [spec for field in fields.by_id if field != link_column and (spec := fields.spec(field))]
        log.info("Grid form of workspace %s: %s; left out for want of a control: %s", workspace_id, [s["id"] for s in specs], fields.left_out)
        return {"fields": [s for s in specs if s["kind"] != INFO]}
