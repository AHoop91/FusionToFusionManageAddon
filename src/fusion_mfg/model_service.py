"""Read one section of a model from the Manufacturing Data Model.

Sections are read separately and on demand, so the panel can show the summary first and fetch the rest only when it is needed.
"""

from typing import Any, Callable, Dict, List, Optional, Union

from ..core.logging_setup import get_logger
from ..core.shapes import as_dict
from .fusion_graphql_client import FusionGraphQlClient, MfgApiError
from .parsers import parse_component, parse_properties, parse_structure, parse_summary
from .physical import COMPONENT_WITH_PHYSICAL_QUERY, PHYSICAL_FIELDS, parse_physical

log = get_logger("model_service")

Progress = Callable[[int], None]   # told how many relations of a bill of materials have been read so far

# GraphQL text for reading one model. The ``bulkModels`` queries take its input list.
SUMMARY_QUERY = """
query ($input: [BulkModelsQueryInput!]!) {
  bulkModels(input: $input) {
    model {
      id
      component {
        id
        composition
        itemNumber { id }
        name { value }
        description { value }
        partNumber { value }
      }
    }
  }
}
"""

# The Fusion Manage item a component is linked to (the hyperlink on its Item Number in Fusion).
MANAGE_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    lifecycle { itemUrn itemUrl }
  }
}
"""

PROPERTIES_QUERY = """
query ($input: [BulkModelsQueryInput!]!) {
  bulkModels(input: $input) {
    model {
      component {
        allProperties(pagination: { limit: 500 }) {
          results { name displayValue }
        }
      }
    }
  }
}
"""

COMPONENT_PROPERTIES_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    allProperties(pagination: { limit: 500 }) {
      results { name displayValue }
    }
  }
}
"""

# A component's thumbnail alone, so a slow one never holds up the rest. The url is short-lived, so a publish asks for it
# again when it needs it.
THUMBNAIL_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    thumbnail { status signedUrl }
  }
}
"""

# What a publish reads of a component: its properties, its thumbnail url and the Fusion Manage item it is linked to. Several
# components go in one request, each under its own alias (``c0``, ``c1`` ...), so the Data Model is asked once for all of them.
PUBLISH_FIELDS = """
    allProperties(pagination: { limit: 500 }) {
      results { name displayValue }
    }
    thumbnail { status signedUrl }
    lifecycle { itemUrn itemUrl }"""


def publish_query(count: int, extra_fields: str = "") -> str:
    """The query for ``count`` components (variables ``id0`` ... , ``composition`` and ``time``); ``extra_fields`` are added to each."""
    declared = "".join(f", $id{n}: ID!" for n in range(count))
    components = "\n".join(f"  c{n}: component(componentId: $id{n}, composition: $composition, time: $time) {{{PUBLISH_FIELDS}\n    {extra_fields}\n  }}"
                           for n in range(count))
    return f"query ($composition: BOMCompositionEnum!, $time: DateTime{declared}) {{\n{components}\n}}\n"


# The whole bill of materials: one flat list of relations down to STRUCTURE_DEPTH levels. Each relation names its parent (fromComponent),
# so the parser rebuilds the tree. Results are paged with a cursor.
STRUCTURE_DEPTH = 50   # no assembly is assumed to stop at some depth: a read that still reaches this is an error, not a cut-off BOM
# The most a page may hold is 250 ("PaginationInput.limit must be between 1 and 250"), and a page of that size costs 467 of the 1000
# points a query may cost. Every page has a fixed cost in time (about two seconds with six relations in it), so the biggest page is
# used. How long a full page takes has not been measured.
STRUCTURE_PAGE_SIZE = 250

STRUCTURE_QUERY = """
query ($componentId: ID!, $composition: BOMCompositionEnum!, $time: DateTime, $depth: Int, $cursor: String, $limit: Int) {
  component(componentId: $componentId, composition: $composition, time: $time) {
    bomRelations(depth: $depth, pagination: { cursor: $cursor, limit: $limit }) {
      pagination { cursor }
      results {
        sequenceNumber
        quantityProperty { displayValue }
        fromComponent { id }
        toComponent {
          id
          hasChildren
          itemNumber { id }
          name { value }
          description { value }
          partNumber { value }
        }
      }
    }
  }
}
"""

SUMMARY = "summary"        # the design's name, number and root component
PROPERTIES = "properties"  # the design's own component's properties
# Sections read with ``bulkModels`` from the open model.
SECTIONS = {
    SUMMARY: (SUMMARY_QUERY, parse_summary),
    PROPERTIES: (PROPERTIES_QUERY, parse_properties),
}
STRUCTURE = "structure"    # the whole BOM tree
LEVEL = "level"            # the lines directly under one component (the design when no id is given), not what is below them
COMPONENT = "component"    # the properties of one component, by id
THUMBNAIL = "thumbnail"    # the design's thumbnail url, on its own, so a slow one never holds up the rest
SECTION_NAMES = (*SECTIONS, STRUCTURE, LEVEL, COMPONENT, THUMBNAIL)
MAX_PAGES = 100   # at 250 relations a page: 25,000 relations; more is an error rather than a BOM cut short

# Components to a publish request. A request may cost 1000 points, and the physical properties cost the most; a request that is too
# dear is refused and read again in halves (``read_publish_components``), so a size that is too big costs time, not a failure.
PUBLISH_BATCH = 4
PUBLISH_BATCH_PHYSICAL = 2


def read_section(client: FusionGraphQlClient, section: str, model_id: str, saved_at: str = "",
                 summary: Optional[Dict[str, Any]] = None, component_id: str = "", physical: bool = False,
                 progress: Optional[Progress] = None) -> Any:
    """Parsed ``section`` of a model.

    ``saved_at`` pins the query to a version and is sent only when non-empty.
    ``structure``, ``level``, ``component`` and ``thumbnail`` also need the ``summary`` (for the root component id and composition), and
    ``component`` the ``component_id`` (``thumbnail`` and ``level`` take one too, else it is the design's).
    ``physical`` adds the physical properties (mass, volume, ...) to the properties of ``properties`` and ``component``; they are slow for
    the Data Model to work out, so only a caller that maps them asks.
    ``progress(count)`` is called after each page of the ``structure`` that is followed by another, with the relations read so far.
    Raises when the query fails; the caller decides how to show that.
    """
    summary = summary or {}
    if section == STRUCTURE:
        return _read_structure(client, summary, saved_at, progress)
    if section == LEVEL:
        return _read_structure(client, summary, saved_at, progress, root_id=component_id, depth=1)
    if section == COMPONENT:
        return _read_component(client, summary, component_id, saved_at, physical)
    if section == THUMBNAIL:
        return {"url": read_thumbnail_url(client, summary, component_id or summary.get("component_id", ""), saved_at)}
    if physical and section == PROPERTIES and summary.get("component_id"):   # the design's own component, with its physical properties
        return _read_component(client, summary, summary["component_id"], saved_at, physical)["properties"]
    query, parse = SECTIONS[section]
    entry = {"modelId": model_id}
    if saved_at:
        entry["time"] = saved_at
    return parse(client.query(query, {"input": [entry]}, label=section))


def _by_name(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(rows, key=lambda row: row["name"].lower())


def _component_variables(summary: Dict[str, Any], component_id: str, saved_at: str) -> Dict[str, Any]:
    """The variables that address one component of the design (at version ``saved_at`` when given); raises while the summary has no ids."""
    composition = summary.get("composition", "")
    if not component_id or not composition:
        raise ValueError("The summary has no component id yet.")
    variables: Dict[str, Any] = {"componentId": component_id, "composition": composition}
    if saved_at:
        variables["time"] = saved_at
    return variables


def _component_in(data: Dict[str, Any]) -> Dict[str, Any]:
    """The ``component`` of a query answer (empty when the answer has none)."""
    return as_dict(data.get("component"))


def _thumbnail_url(node: Dict[str, Any]) -> str:
    """The signed thumbnail url of a component in a query answer (empty when it has none yet)."""
    return str(as_dict(node.get("thumbnail")).get("signedUrl") or "")


def _manage_item(node: Dict[str, Any]) -> Dict[str, str]:
    """``{"urn", "url"}`` of the Fusion Manage item a component in a query answer is linked to (empty values when it is not linked)."""
    lifecycle = as_dict(node.get("lifecycle"))
    return {"urn": str(lifecycle.get("itemUrn") or ""), "url": str(lifecycle.get("itemUrl") or "")}


def read_thumbnail_url(client: FusionGraphQlClient, summary: Dict[str, Any], component_id: str, saved_at: str = "") -> str:
    """A fresh signed url of a component's thumbnail (empty when it has none yet); it expires soon, so use it at once."""
    data = client.query(THUMBNAIL_QUERY, _component_variables(summary, component_id, saved_at), label="thumbnail")
    return _thumbnail_url(_component_in(data))


def read_manage_item(client: FusionGraphQlClient, summary: Dict[str, Any], component_id: str, saved_at: str = "") -> Dict[str, str]:
    """``{"urn", "url"}`` of the Fusion Manage item a component is linked to (empty values when it is not linked)."""
    data = client.query(MANAGE_QUERY, _component_variables(summary, component_id, saved_at), label="manage link")
    return _manage_item(_component_in(data))


def publish_batch_size(physical: bool) -> int:
    """How many components one publish request holds."""
    return PUBLISH_BATCH_PHYSICAL if physical else PUBLISH_BATCH


def read_publish_components(client: FusionGraphQlClient, summary: Dict[str, Any], component_ids: List[str], saved_at: str = "",
                            physical: bool = False) -> Dict[str, Union[Dict[str, Any], Exception]]:
    """What a publish reads of each component, in one request: by component id, ``properties`` (with the physical ones when ``physical``),
    the ``thumbnail_url`` (empty when it has none yet; it expires soon, so use it at once) and the Fusion Manage ``link`` of the item it is
    linked to (``{"urn", "url"}``, empty values when it is not linked), or the error that kept it from being read.

    When the Data Model refuses the request for a reason other than being busy, the components are read again in halves until the one it
    refuses is alone, so a single bad component fails only itself. A busy answer (already retried) fails all of them."""
    composition = summary.get("composition", "")
    if not composition or not component_ids or not all(component_ids):
        raise ValueError("The summary has no component id yet.")
    variables: Dict[str, Any] = {"composition": composition, **{f"id{n}": cid for n, cid in enumerate(component_ids)}}
    if saved_at:
        variables["time"] = saved_at
    try:
        data = client.query(publish_query(len(component_ids), PHYSICAL_FIELDS if physical else ""), variables,
                            label=f"publish x{len(component_ids)}" + (" + physical" if physical else ""))
    except MfgApiError as exc:
        if exc.transient:
            return {cid: exc for cid in component_ids}
        if len(component_ids) == 1:
            return {component_ids[0]: exc}
        log.info("The Data Model refused %d components together (%s); reading them in halves", len(component_ids), exc)
        half = len(component_ids) // 2
        return {**read_publish_components(client, summary, component_ids[:half], saved_at, physical),
                **read_publish_components(client, summary, component_ids[half:], saved_at, physical)}
    return {cid: _publish_read(as_dict(data.get(f"c{n}")), physical) for n, cid in enumerate(component_ids)}


def _properties_of(data: Dict[str, Any], physical: bool) -> List[Dict[str, str]]:
    """The properties of the component in a query answer, with its physical ones (``physical``), by name."""
    properties = parse_component(data)["properties"]
    return _by_name(properties + parse_physical(data)) if physical else properties


def _publish_read(node: Dict[str, Any], physical: bool) -> Dict[str, Any]:
    """What a publish keeps of one component's part of a ``publish_query`` answer."""
    return {"properties": _properties_of({"component": node}, physical), "thumbnail_url": _thumbnail_url(node), "link": _manage_item(node)}


def _read_component(client: FusionGraphQlClient, summary: Dict[str, Any], component_id: str, saved_at: str, physical: bool = False) -> Any:
    """``{"properties": [...]}`` of one component, with its physical properties when ``physical``."""
    query, label = (COMPONENT_WITH_PHYSICAL_QUERY, "properties + physical") if physical else (COMPONENT_PROPERTIES_QUERY, "properties")
    data = client.query(query, _component_variables(summary, component_id, saved_at), label=label)
    return {"properties": _properties_of(data, physical)}


def _read_structure(client: FusionGraphQlClient, summary: Dict[str, Any], saved_at: str, progress: Optional[Progress] = None,
                    root_id: str = "", depth: int = STRUCTURE_DEPTH) -> Any:
    """The lines below ``root_id`` (the design when empty) down to ``depth`` levels, as ``parse_structure`` rows. ``depth`` 1 is one
    level: only the lines directly under it, whatever the answer holds below them."""
    root_id = root_id or summary.get("component_id", "")
    variables = _component_variables(summary, root_id, saved_at)
    variables.update(depth=depth, limit=STRUCTURE_PAGE_SIZE, cursor=None)
    relations: List[Any] = []
    for page in range(1, MAX_PAGES + 1):
        data = client.query(STRUCTURE_QUERY, variables, label=f"structure page {page}")
        node = as_dict(_component_in(data).get("bomRelations"))
        relations.extend(node.get("results") or [])
        variables["cursor"] = as_dict(node.get("pagination")).get("cursor")
        if not variables["cursor"]:
            break
        if progress:   # only a structure of several pages has a count worth showing
            progress(len(relations))
    else:   # the last page still named a next one: showing what was read would pass a part of the BOM off as all of it
        raise MfgApiError(f"The Bill of Materials has more than {MAX_PAGES * STRUCTURE_PAGE_SIZE} components, more than can be read.")
    rows = parse_structure(relations, root_id)
    deepest = max((int(row["level"]) for row in rows), default=-1) + 1   # levels below the root
    log.debug("Read the structure of %s to depth %d: %d relation(s) in %d page(s), %d level(s) deep", root_id, depth, len(relations), page, deepest)
    if depth == 1:   # one level was asked for: keep the direct lines, whatever else the answer carried
        return [row for row in rows if int(row["level"]) == 0]
    if deepest >= STRUCTURE_DEPTH:   # the read stopped at its depth: there may be more below
        raise MfgApiError(f"The Bill of Materials is nested {STRUCTURE_DEPTH} levels deep or more, more than can be read.")
    return rows
