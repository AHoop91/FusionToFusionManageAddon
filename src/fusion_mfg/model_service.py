"""Read one section of a model from the Manufacturing Data Model.

Sections are read separately and on demand, so the panel can show the summary
first and fetch the rest only when it is needed.
"""

from typing import Any, Dict

from .graphql_client import MfgGraphQlClient
from .parsers import parse_component, parse_properties, parse_structure, parse_summary
from .queries import (COMPONENT_PROPERTIES_QUERY, PROPERTIES_QUERY, STRUCTURE_DEPTH,
                      STRUCTURE_PAGE_SIZE, STRUCTURE_QUERY, SUMMARY_QUERY)

# Sections read with ``bulkModels`` from the open model.
SECTIONS = {
    "summary": (SUMMARY_QUERY, parse_summary),
    "properties": (PROPERTIES_QUERY, parse_properties),
}
STRUCTURE = "structure"    # the whole BOM tree
COMPONENT = "component"    # the properties and drawings of one component, by id
SECTION_NAMES = (*SECTIONS, STRUCTURE, COMPONENT)
MAX_PAGES = 50


def read_section(client: MfgGraphQlClient, section: str, model_id: str, time: str = "",
                 summary: Dict[str, Any] = None, component_id: str = "") -> Any:
    """Parsed ``section`` of a model.

    ``time`` pins the query to a version and is sent only when non-empty.
    ``structure`` and ``component`` also need the ``summary`` (for the root
    component id and composition), and ``component`` the ``component_id``.
    Raises when the query fails; the caller decides how to show that.
    """
    if section == STRUCTURE:
        return _read_structure(client, summary or {}, time)
    if section == COMPONENT:
        return _read_component(client, summary or {}, component_id, time)
    query, parse = SECTIONS[section]
    entry = {"modelId": model_id}
    if time:
        entry["time"] = time
    return parse(client.query(query, {"input": [entry]}))


def _component_variables(summary: Dict[str, Any], component_id: str, time: str) -> Dict[str, Any]:
    composition = summary.get("composition", "")
    if not component_id or not composition:
        raise ValueError("The summary has no component id yet.")
    variables: Dict[str, Any] = {"componentId": component_id, "composition": composition}
    if time:
        variables["time"] = time
    return variables


def _read_component(client: MfgGraphQlClient, summary: Dict[str, Any], component_id: str, time: str) -> Any:
    return parse_component(
        client.query(COMPONENT_PROPERTIES_QUERY, _component_variables(summary, component_id, time)))


def _read_structure(client: MfgGraphQlClient, summary: Dict[str, Any], time: str) -> Any:
    root_id = summary.get("component_id", "")
    variables = _component_variables(summary, root_id, time)
    variables.update(depth=STRUCTURE_DEPTH, limit=STRUCTURE_PAGE_SIZE, cursor=None)
    relations = []
    for _ in range(MAX_PAGES):
        node = (client.query(STRUCTURE_QUERY, variables).get("component") or {}).get("bomRelations") or {}
        relations.extend(node.get("results") or [])
        variables["cursor"] = (node.get("pagination") or {}).get("cursor")
        if not variables["cursor"]:
            break
    return parse_structure(relations, root_id)
