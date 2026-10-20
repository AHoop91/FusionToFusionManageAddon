"""Fusion Manage workspace configuration.

Each workspace the add-in writes to (items today; BOMs and others later) has
its own workspace id and its own field mapping: which Manufacturing Data
Model field fills which Fusion Manage field.

To support another workspace, add a ``WorkspaceKind`` to ``WORKSPACE_KINDS``.
To offer another source field, add a ``SourceField`` to ``SOURCE_FIELDS``.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .problems import Problem


@dataclass(frozen=True)
class WorkspaceKind:
    """A workspace the add-in works with."""

    kind_id: str
    title: str
    description: str
    # Short FM permission names the user needs on the workspace at all.
    required_permissions: tuple = ()
    # DefaultMapping rows the "Add default fields" button adds.
    default_mappings: tuple = ()
    # Name of the picklist that links an item to a component (e.g. CUSTOM_LOOKUP_WS_COMPONENTS_...);
    # the workspace's Fusion Manage field using it is the "Component linking" field. Empty: none.
    component_lookup: str = ""


@dataclass(frozen=True)
class DefaultMapping:
    """A mapping row added by "Add default fields"."""

    source: str
    fm_field_id: str


@dataclass(frozen=True)
class SourceField:
    """A Manufacturing Data Model field that can be mapped."""

    field_id: str
    label: str
    # "property" fills a text/number field; "file" pushes a file (e.g. the
    # thumbnail) into an FM image or attachment field.
    kind: str = "property"
    # The Data Model's own name for the property, where it differs from the label shown in Settings.
    data_model_name: str = ""


WORKSPACE_KINDS = [
    # The item BOM is always published, so its permissions are required.
    WorkspaceKind("items", "Items", "Manufacturing items created in Fusion Manage.",
                  ("view_items", "add_items", "edit_items", "view_bom", "add_to_bom", "edit_bom"),
                  (DefaultMapping("item_number", "NUMBER"), DefaultMapping("name", "TITLE"),
                   DefaultMapping("description", "DESCRIPTION"), DefaultMapping("thumbnail", "IMAGE"),
                   DefaultMapping("material", "MATERIAL"),
                   DefaultMapping("physical:Height", "HEIGHT"), DefaultMapping("physical:Width", "WIDTH"),
                   DefaultMapping("physical:Length", "LENGTH"), DefaultMapping("physical:Mass", "ITEM_WEIGHT")),
                  "CUSTOM_LOOKUP_WS_COMPONENTS_ALL_INCLUDING_WORKING"),
]

KINDS_BY_ID = {k.kind_id: k for k in WORKSPACE_KINDS}
ITEMS_KIND = "items"   # the kind the Item panel, the publish and the BOM work with
LEGACY_NUMBER_FIELD = "NUMBER"   # the field the Part number used to be mapped to by default
ITEM_NUMBER_SOURCE = "item_number"   # the source every items workspace must map: it names the Fusion Manage field holding the item number

SOURCE_FIELDS = [
    SourceField("item_number", "Item Number"),
    SourceField("part_number", "Part number"),
    SourceField("name", "Name"),
    SourceField("description", "Description"),
    SourceField("revision", "Revision"),
    SourceField("material", "Material", data_model_name="materialName"),
    SourceField("lifecycle_state", "Lifecycle state"),
    SourceField("thumbnail", "Thumbnail", "file"),
]

_SOURCES_BY_ID = {f.field_id: f for f in SOURCE_FIELDS}

# Hub properties are stored as "custom:<name>" or "base:<name>", so any
# property defined on the Manufacturing Data Model item can be mapped by name.
CUSTOM_PREFIX = "custom:"
BASE_PREFIX = "base:"
PHYSICAL_PREFIX = "physical:"   # "physical:Mass": a physical property of the component (see ``fusion_mfg.physical``)
PHYSICAL_NAMES = ("Mass", "Volume", "Area", "Density", "Length", "Width", "Height")   # Length, Width and Height are the bounding box
_PROPERTY_PREFIXES = (CUSTOM_PREFIX, BASE_PREFIX, PHYSICAL_PREFIX)


def is_valid_source(source: str) -> bool:
    """True for a known source field or a named hub property."""
    for prefix in _PROPERTY_PREFIXES:
        if source.startswith(prefix):
            return bool(source[len(prefix):].strip())
    return source in _SOURCES_BY_ID


def _source_label(source: str) -> str:
    """What the panel calls a source field: its label, or the property name for a named hub property."""
    known = _SOURCES_BY_ID.get(source)
    return known.label if known else data_model_name(source) or source


def data_model_name(source: str) -> str:
    """Name of the Data Model property a source reads ("" for a file source or an unknown one)."""
    if source.startswith(PHYSICAL_PREFIX):   # listed as "Physical Mass", so it never meets a hub property of the same name
        return "Physical " + source[len(PHYSICAL_PREFIX):]
    for prefix in _PROPERTY_PREFIXES:
        if source.startswith(prefix):
            return source[len(prefix):]
    known = _SOURCES_BY_ID.get(source)
    return (known.data_model_name or known.label) if known and known.kind == "property" else ""


@dataclass
class FieldMapping:
    """One mapping row: a source field fills a Fusion Manage field."""

    source: str = ""
    fm_field_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "fm_field_id": self.fm_field_id}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldMapping":
        return cls(
            source=str(data.get("source", "")).strip(),
            fm_field_id=str(data.get("fm_field_id", "")).strip(),
        )


@dataclass
class StaticValue:
    """A Fusion Manage field that is always set to the same value."""

    fm_field_id: str = ""
    value: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"fm_field_id": self.fm_field_id, "value": self.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StaticValue":
        return cls(fm_field_id=str(data.get("fm_field_id", "")).strip(),
                   value=str(data.get("value", "")))


@dataclass
class WorkspaceConfig:
    """A workspace id, its field mapping and its static values."""

    workspace_id: str = ""
    mappings: List[FieldMapping] = field(default_factory=list)
    static_values: List[StaticValue] = field(default_factory=list)
    # The Fusion Manage field that links an item to its component ("" = not linked).
    component_field: str = ""

    def setup_problem(self, title: str) -> str:
        """Why this workspace cannot be used yet ("" when its settings are complete): it needs a workspace ID and valid mappings."""
        if not self.workspace_id:
            return f"The {title} workspace ID is not set."
        problems = self.validate()
        return problems[0] if problems else ""

    def validate(self) -> List[str]:
        """Return human-readable problems, each saying which row it is in and what to do."""
        problems: List[str] = []
        if self.workspace_id and not self.workspace_id.isdigit():
            problems.append(Problem("Workspace: the ID must be a number. Choose a workspace from the list.", area="id"))
        first_row_of_source: Dict[str, int] = {}
        for index, row in enumerate(self.mappings):
            name = f"Mapped field {index + 1}"
            if not is_valid_source(row.source):
                what = "enter the name of the property" if row.source.strip() else "choose a Component Property"
                problems.append(Problem(f"{name}: {what}.", area="mapping", row=index, part="source"))
            elif row.source in first_row_of_source:
                problems.append(Problem(
                    f"{name}: the Component Property '{_source_label(row.source)}' is already used by mapped field "
                    f"{first_row_of_source[row.source] + 1}. Each property can be mapped once.", area="mapping", row=index, part="source"))
            else:
                first_row_of_source[row.source] = index
            if not row.fm_field_id:
                problems.append(Problem(f"{name}: choose a Fusion Manage Item Field.", area="mapping", row=index, part="field"))
        for index, row in enumerate(self.static_values):
            if not row.fm_field_id:
                problems.append(Problem(f"Default value {index + 1}: choose a Fusion Manage Item Field.", area="static", row=index, part="field"))
        # A Fusion Manage field can be filled once: by a mapped field, the Component field or a default value.
        filled: Dict[str, str] = {}
        places = ([("mapping", i, f"Mapped field {i + 1}", r.fm_field_id) for i, r in enumerate(self.mappings)]
                  + [("component", 0, "The Component field", self.component_field)]
                  + [("static", i, f"Default value {i + 1}", r.fm_field_id) for i, r in enumerate(self.static_values)])
        for area, index, name, fm_field_id in places:
            if not fm_field_id:
                continue
            if fm_field_id in filled:
                problems.append(Problem(
                    f"{name}: the Fusion Manage Item Field '{fm_field_id}' is already filled by {filled[fm_field_id].lower()}. "
                    "Each field can be filled once.", area=area, row=index, part="field"))
            else:
                filled[fm_field_id] = name
        if self.workspace_id and not any(row.source == ITEM_NUMBER_SOURCE for row in self.mappings):
            problems.append(Problem(
                "Item Number is not mapped. Add a mapped field with the Component Property 'Item Number' and the Fusion Manage Item Field "
                f"'{LEGACY_NUMBER_FIELD}' (Add default fields adds it).", area="mappings"))
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return {"workspace_id": self.workspace_id,
                "mappings": [row.to_dict() for row in self.mappings],
                "static_values": [row.to_dict() for row in self.static_values],
                "component_field": self.component_field}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceConfig":
        rows = data.get("mappings")
        statics = data.get("static_values")
        mappings = ([FieldMapping.from_dict(r) for r in rows if isinstance(r, dict)]
                    if isinstance(rows, list) else [])
        # Earlier versions mapped the Part number to NUMBER; the Item Number is what that field holds now.
        if not any(m.source == ITEM_NUMBER_SOURCE for m in mappings):
            for m in mappings:
                if m.source == "part_number" and m.fm_field_id == LEGACY_NUMBER_FIELD:
                    m.source = ITEM_NUMBER_SOURCE
        return cls(
            workspace_id=str(data.get("workspace_id", "")).strip(),
            component_field=str(data.get("component_field", "")).strip(),
            mappings=mappings,
            static_values=[StaticValue.from_dict(r) for r in statics if isinstance(r, dict)]
            if isinstance(statics, list) else [],
        )


@dataclass
class WorkspaceSettings:
    """Configuration for every workspace kind, keyed by ``WorkspaceKind.kind_id``."""

    workspaces: Dict[str, WorkspaceConfig] = field(
        default_factory=lambda: {k.kind_id: WorkspaceConfig() for k in WORKSPACE_KINDS})

    def get(self, kind_id: str) -> WorkspaceConfig:
        return self.workspaces[kind_id]

    def validate(self) -> List[str]:
        problems: List[str] = []
        for kind in WORKSPACE_KINDS:
            for problem in self.workspaces[kind.kind_id].validate():
                problem.where["workspace"] = kind.kind_id
                problems.append(problem)
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return {kind_id: cfg.to_dict() for kind_id, cfg in self.workspaces.items()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceSettings":
        """Build from stored JSON; unknown kinds are ignored, missing ones defaulted."""
        # Older files stored a single ``items_workspace_id``.
        if "items_workspace_id" in data:
            data = {"items": {"workspace_id": data["items_workspace_id"]}}
        return cls(workspaces={
            kind.kind_id: WorkspaceConfig.from_dict(data.get(kind.kind_id) or {})
            for kind in WORKSPACE_KINDS
        })


def catalog() -> Dict[str, Any]:
    """Static lists the panel needs to render workspace cards and mapping rows."""
    return {
        "kinds": [{"id": k.kind_id, "title": k.title, "description": k.description, "component_lookup": k.component_lookup,
                   "default_mappings": [asdict(m) for m in k.default_mappings]}
                  for k in WORKSPACE_KINDS],
        "source_fields": [{"id": f.field_id, "label": f.label, "kind": f.kind} for f in SOURCE_FIELDS],
        "custom_prefix": CUSTOM_PREFIX,
        "base_prefix": BASE_PREFIX,
        "physical_prefix": PHYSICAL_PREFIX,
    }
