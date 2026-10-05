"""Fusion Manage workspace configuration.

Each workspace the add-in writes to (items today; BOMs and others later) has
its own workspace id and its own field mapping: which Manufacturing Data
Model field fills which Fusion Manage field.

To support another workspace, add a ``WorkspaceKind`` to ``WORKSPACE_KINDS``.
To offer another source field, add a ``SourceField`` to ``SOURCE_FIELDS``.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


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
    match_key: bool = False


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

    @property
    def can_match(self) -> bool:
        """Only property values can identify an existing item."""
        return self.kind == "property"


WORKSPACE_KINDS = [
    # The item BOM is always published, so its permissions are required.
    WorkspaceKind("items", "Items", "Manufacturing items created in Fusion Manage.",
                  ("view_items", "add_items", "edit_items", "view_bom", "add_to_bom", "edit_bom"),
                  (DefaultMapping("part_number", "NUMBER", True), DefaultMapping("name", "TITLE"),
                   DefaultMapping("description", "DESCRIPTION"), DefaultMapping("thumbnail", "IMAGE"),
                   DefaultMapping("material", "MATERIAL")),
                  "CUSTOM_LOOKUP_WS_COMPONENTS_ALL_INCLUDING_WORKING"),
]

KINDS_BY_ID = {k.kind_id: k for k in WORKSPACE_KINDS}

SOURCE_FIELDS = [
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
_PROPERTY_PREFIXES = (CUSTOM_PREFIX, BASE_PREFIX)


def is_valid_source(source: str) -> bool:
    """True for a known source field or a named hub property."""
    for prefix in _PROPERTY_PREFIXES:
        if source.startswith(prefix):
            return bool(source[len(prefix):].strip())
    return source in _SOURCES_BY_ID


def data_model_name(source: str) -> str:
    """Name of the Data Model property a source reads ("" for a file source or an unknown one)."""
    for prefix in _PROPERTY_PREFIXES:
        if source.startswith(prefix):
            return source[len(prefix):]
    known = _SOURCES_BY_ID.get(source)
    return (known.data_model_name or known.label) if known and known.kind == "property" else ""


def can_match(source: str) -> bool:
    """Hub properties are property values, so they can be the match key."""
    field_def = _SOURCES_BY_ID.get(source)
    return field_def.can_match if field_def else source.startswith(_PROPERTY_PREFIXES)


@dataclass
class FieldMapping:
    """One mapping row: a source field fills a Fusion Manage field."""

    source: str = ""
    fm_field_id: str = ""
    # The match key identifies an existing item so it is updated, not duplicated.
    match_key: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "fm_field_id": self.fm_field_id, "match_key": self.match_key}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldMapping":
        return cls(
            source=str(data.get("source", "")).strip(),
            fm_field_id=str(data.get("fm_field_id", "")).strip(),
            match_key=bool(data.get("match_key", False)),
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

    def validate(self, title: str) -> List[str]:
        """Return human-readable problems; ``title`` names the workspace."""
        problems = []
        if self.workspace_id and not self.workspace_id.isdigit():
            problems.append(f"{title}: Workspace ID must be a number.")
        seen = set()
        for row in self.mappings:
            if not is_valid_source(row.source):
                problems.append(f"{title}: choose a source field (and name any custom property) for every mapping.")
            elif row.source in seen:
                problems.append(f"{title}: source field '{row.source}' is mapped twice.")
            elif row.match_key and not can_match(row.source):
                problems.append(f"{title}: '{row.source}' cannot be the match key.")
            seen.add(row.source)
            if not row.fm_field_id:
                problems.append(f"{title}: enter a Fusion Manage field ID for every mapping.")
        keys = sum(1 for row in self.mappings if row.match_key)
        if keys > 1:
            problems.append(f"{title}: only one mapping can be the match key.")
        elif keys == 0 and self.workspace_id:
            problems.append(f"{title}: tick Key on one mapping so existing items in Fusion Manage can be matched.")
        # A Fusion Manage field can be filled once, by a mapping or a static value.
        targets = [row.fm_field_id for row in self.mappings if row.fm_field_id]
        if self.component_field:
            targets.append(self.component_field)
        for row in self.static_values:
            if not row.fm_field_id:
                problems.append(f"{title}: choose a Fusion Manage field for every static value.")
            else:
                targets.append(row.fm_field_id)
        for fm_field_id in sorted({t for t in targets if targets.count(t) > 1}):
            problems.append(f"{title}: Fusion Manage field '{fm_field_id}' is filled more than once.")
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
        return cls(
            workspace_id=str(data.get("workspace_id", "")).strip(),
            component_field=str(data.get("component_field", "")).strip(),
            mappings=[FieldMapping.from_dict(r) for r in rows if isinstance(r, dict)]
            if isinstance(rows, list) else [],
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
            problems += self.workspaces[kind.kind_id].validate(kind.title)
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
        "source_fields": [{"id": f.field_id, "label": f.label, "kind": f.kind,
                           "can_match": f.can_match} for f in SOURCE_FIELDS],
        "custom_prefix": CUSTOM_PREFIX,
        "base_prefix": BASE_PREFIX,
    }
