"""Read one section of a model from the Manufacturing Data Model.

Sections are read separately and on demand, so the panel can show the summary
first and fetch the rest only when it is needed.
"""

from typing import Any, Callable, Dict

from ..core.logging_setup import get_logger
from .graphql_client import MfgApiError, MfgGraphQlClient
from .physical import COMPONENT_WITH_PHYSICAL_QUERY, parse_physical
from .parsers import parse_component, parse_properties, parse_structure, parse_summary
from .queries import (COMPONENT_PROPERTIES_QUERY, MANAGE_QUERY, PROPERTIES_QUERY, STRUCTURE_DEPTH,
                      STRUCTURE_PAGE_SIZE, STRUCTURE_QUERY, SUMMARY_QUERY, THUMBNAIL_QUERY)

# Sections read with ``bulkModels`` from the open model.
SECTIONS = {
    "summary": (SUMMARY_QUERY, parse_summary),
    "properties": (PROPERTIES_QUERY, parse_properties),
}
STRUCTURE = "structure"    # the whole BOM tree
COMPONENT = "component"    # the properties of one component, by id
THUMBNAIL = "thumbnail"    # the design's thumbnail url, on its own: the Data Model is slow to give it
SECTION_NAMES = (*SECTIONS, STRUCTURE, COMPONENT, THUMBNAIL)
MAX_PAGES = 100   # at 250 relations a page: 25,000 relations; more is an error rather than a BOM cut short

log = get_logger("model_service")


def read_section(client: MfgGraphQlClient, section: str, model_id: str, time: str = "",
                 summary: Dict[str, Any] = None, component_id: str = "", physical: bool = False,
                 progress: Callable[[int], None] = None) -> Any:
    """Parsed ``section`` of a model.

    ``time`` pins the query to a version and is sent only when non-empty.
    ``structure``, ``component`` and ``thumbnail`` also need the ``summary`` (for the root
    component id and composition), and ``component`` the ``component_id``.
    ``physical`` adds the physical properties (mass, volume, ...) to the properties of ``properties`` and
    ``component``; they are slow for the Data Model to work out, so only a caller that maps them asks.
    ``progress(count)`` is called after each page of the ``structure`` that is followed by another, with the relations read so far.
    Raises when the query fails; the caller decides how to show that.
    """
    if section == STRUCTURE:
        return _read_structure(client, summary or {}, time, progress)
    if section == COMPONENT:
        return _read_component(client, summary or {}, component_id, time, physical)
    if section == THUMBNAIL:
        return {"url": read_thumbnail_url(client, summary or {}, (summary or {}).get("component_id", ""), time)}
    if physical and section == "properties" and summary and summary.get("component_id"):   # the design's own component, with its physical properties
        return _read_component(client, summary, summary["component_id"], time, physical)["properties"]
    query, parse = SECTIONS[section]
    entry = {"modelId": model_id}
    if time:
        entry["time"] = time
    return parse(client.query(query, {"input": [entry]}, label=section))


def _sorted(rows: Any) -> Any:
    return sorted(rows, key=lambda r: r["name"].lower())


def _component_variables(summary: Dict[str, Any], component_id: str, time: str) -> Dict[str, Any]:
    composition = summary.get("composition", "")
    if not component_id or not composition:
        raise ValueError("The summary has no component id yet.")
    variables: Dict[str, Any] = {"componentId": component_id, "composition": composition}
    if time:
        variables["time"] = time
    return variables


def read_thumbnail_url(client: MfgGraphQlClient, summary: Dict[str, Any], component_id: str, time: str = "") -> str:
    """A fresh signed url of a component's thumbnail (empty when it has none yet); it expires soon, so use it at once."""
    node = (client.query(THUMBNAIL_QUERY, _component_variables(summary, component_id, time), label="thumbnail").get("component") or {})
    return str((node.get("thumbnail") or {}).get("signedUrl") or "")


def read_manage_item(client: MfgGraphQlClient, summary: Dict[str, Any], component_id: str, time: str = "") -> Dict[str, str]:
    """``{"urn", "url"}`` of the Fusion Manage item a component is linked to (empty values when it is not linked)."""
    node = (client.query(MANAGE_QUERY, _component_variables(summary, component_id, time), label="manage link").get("component") or {}).get("lifecycle") or {}
    return {"urn": str(node.get("itemUrn") or ""), "url": str(node.get("itemUrl") or "")}


def _read_component(client: MfgGraphQlClient, summary: Dict[str, Any], component_id: str, time: str, physical: bool = False) -> Any:
    variables = _component_variables(summary, component_id, time)
    if physical:
        data = client.query(COMPONENT_WITH_PHYSICAL_QUERY, variables, label="properties + physical")
        return {"properties": _sorted(parse_component(data)["properties"] + parse_physical(data))}
    return parse_component(client.query(COMPONENT_PROPERTIES_QUERY, variables, label="properties"))


def _read_structure(client: MfgGraphQlClient, summary: Dict[str, Any], time: str, progress: Callable[[int], None] = None) -> Any:
    root_id = summary.get("component_id", "")
    variables = _component_variables(summary, root_id, time)
    variables.update(depth=STRUCTURE_DEPTH, limit=STRUCTURE_PAGE_SIZE, cursor=None)
    relations = []
    for page in range(1, MAX_PAGES + 1):
        node = (client.query(STRUCTURE_QUERY, variables, label=f"structure page {page}").get("component") or {}).get("bomRelations") or {}
        relations.extend(node.get("results") or [])
        variables["cursor"] = (node.get("pagination") or {}).get("cursor")
        if not variables["cursor"]:
            break
        if progress:   # only a structure of several pages has a count worth showing
            progress(len(relations))
    else:   # the last page still named a next one: showing what was read would pass a part of the BOM off as all of it
        raise MfgApiError(f"The Bill of Materials has more than {MAX_PAGES * STRUCTURE_PAGE_SIZE} components, more than can be read.")
    rows = parse_structure(relations, root_id)
    deepest = max((int(r["level"]) for r in rows), default=-1) + 1   # levels below the root
    log.debug("Read the structure: %d relation(s) in %d page(s), %d level(s) deep", len(relations), page, deepest)
    if deepest >= STRUCTURE_DEPTH:   # the read stopped at its depth: there may be more below
        raise MfgApiError(f"The Bill of Materials is nested {STRUCTURE_DEPTH} levels deep or more, more than can be read.")
    return rows
