"""Whether a Fusion Manage workspace has the layout a kind of workspace needs.

Workspace ids differ in every tenant, so a workspace is recognised by what it holds: the tabs, and the fields with their type and the
section that holds each (see ``WorkspaceSchema`` in ``config/workspace_models.py``). ``read_layout`` reads what the workspace has and
``problems`` says what it lacks, all at once, so the administrator can fix the workspace in one go.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from ..config.workspace_models import FieldNeed, WorkspaceSchema
from ..core.i18n import t
from ..core.logging_setup import get_logger
from .client import WORKSPACES, FmClient, last_segment
from .sections import SectionService, parse_sections
from .tabs import parse_labels

log = get_logger("fm.workspace_schema")


@dataclass
class Layout:
    """What a workspace has. ``fields`` is ``{field id: {"title", "type"}}``; ``sections`` is ``{field id: title of its section}``."""

    tabs: Dict[str, str] = field(default_factory=dict)   # workspaceTabName -> the tab's label
    fields: Dict[str, Dict[str, str]] = field(default_factory=dict)
    sections: Dict[str, str] = field(default_factory=dict)


def _same(a: str, b: str) -> bool:
    return a.strip().lower() == b.strip().lower()


def _section_title(section: Dict[str, Any]) -> str:
    return str(section.get("title") or section.get("name") or "")


def read_layout(client: FmClient, workspace_id: str, fields: Sequence[Dict[str, Any]]) -> Layout:
    """The layout of a workspace, read afresh (an administrator who has just fixed the workspace checks it again at once).
    ``fields`` are the workspace's fields as ``WorkspaceService.fields`` gives them. Raises ``FmApiError`` or ``AuthError`` when a read fails."""
    tabs = parse_labels(client.get_json(f"{WORKSPACES}/{workspace_id}/tabs"))
    layouts = SectionService(client).layouts(workspace_id, fresh=True)
    titles = {section_id: _section_title(section) for section_id, section in layouts.items()}
    placed = {field_id: titles.get(last_segment(link), "") for field_id, link in parse_sections(list(layouts.values())).items()}
    layout = Layout(tabs, {f["id"]: {"title": f["title"], "type": f["type"]} for f in fields}, placed)
    log.info("Layout of workspace %s: tabs=%s; fields=%s", workspace_id, sorted(tabs),
             [(i, f["type"], placed.get(i, "")) for i, f in sorted(layout.fields.items())])   # what to pick the required fields from
    return layout


def _field_problems(need: FieldNeed, layout: Layout) -> List[str]:
    found = layout.fields.get(need.field_id)
    if found is None:
        return []   # reported with the other missing fields
    problems = []
    if need.type and not _same(found["type"], need.type):
        problems.append(t("data.schema_wrong_type", field=need.field_id, actual=found["type"] or "?", expected=need.type))
    if need.section and not _same(layout.sections.get(need.field_id, ""), need.section):
        problems.append(t("data.schema_wrong_section", field=need.field_id, actual=layout.sections.get(need.field_id) or "?", expected=need.section))
    return problems


def problems(schema: WorkspaceSchema, layout: Layout) -> List[str]:
    """What ``layout`` lacks of ``schema``: each missing tab, missing field and field of the wrong type or in the wrong section, as a sentence."""
    found: List[str] = []
    lacking_tabs = [name for name in schema.tabs if name not in layout.tabs]
    if lacking_tabs:
        found.append(t("data.schema_missing_tabs", tabs=", ".join(lacking_tabs)))
    lacking_fields = [need.field_id for need in schema.fields if need.field_id not in layout.fields]
    if lacking_fields:
        found.append(t("data.schema_missing_fields", fields=", ".join(lacking_fields)))
    for need in schema.fields:
        found.extend(_field_problems(need, layout))
    return found
