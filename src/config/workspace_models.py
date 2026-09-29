"""Fusion Manage workspace configuration.

Each workspace the add-in writes to (items today; BOMs and others later) has
its own workspace id and its own field mapping: which Manufacturing Data
Model field fills which Fusion Manage field.

To support another workspace, add a ``WorkspaceKind`` to ``WORKSPACE_KINDS``.
To offer another source field, add a ``SourceField`` to ``SOURCE_FIELDS``.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class WorkspaceKind:
    """A workspace the add-in works with."""

    kind_id: str
    title: str
    description: str
    options: tuple = ()   # WorkspaceOption entries shown on the workspace's tab
    # Short FM permission names the user needs on the workspace at all.
    required_permissions: tuple = ()


@dataclass(frozen=True)
class SourceField:
    """A Manufacturing Data Model field that can be mapped."""

    field_id: str
    label: str
    # "property" fills a text/number field; "file" pushes a file (e.g. the
    # thumbnail) into an FM image or attachment field.
    kind: str = "property"

    @property
    def can_match(self) -> bool:
        """Only property values can identify an existing item."""
        return self.kind == "property"


@dataclass(frozen=True)
class WorkspaceOption:
    """An on/off setting shown on a workspace card's Workspace tab."""

    option_id: str
    label: str
    description: str
    default: bool = False
    # Short FM permission names (e.g. "add_attachments") the option needs.
    permissions: tuple = ()


ITEM_OPTIONS = (
    WorkspaceOption("include_bom", "Publish Bill of Materials",
                    "Push the item's BOM rows along with the item.", True,
                    ("view_bom", "add_to_bom", "edit_bom")),
    WorkspaceOption("include_step", "Publish STEP Representation",
                    "Attach the STEP representation to the item.", False,
                    ("view_attachments", "add_attachments")),
    WorkspaceOption("include_drawing", "Publish Drawing Representation",
                    "Attach the drawing (PDF) representation to the item.", False,
                    ("view_attachments", "add_attachments")),
)

WORKSPACE_KINDS = [
    WorkspaceKind("items", "Items", "Manufacturing items created in Fusion Manage.", ITEM_OPTIONS,
                  ("view_items", "add_items", "edit_items")),
]

KINDS_BY_ID = {k.kind_id: k for k in WORKSPACE_KINDS}

SOURCE_FIELDS = [
    SourceField("part_number", "Part number"),
    SourceField("name", "Name"),
    SourceField("description", "Description"),
    SourceField("revision", "Revision"),
    SourceField("material", "Material"),
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
    # option_id -> on/off; missing ids fall back to the option's default.
    options: Dict[str, bool] = field(default_factory=dict)

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
        if sum(1 for row in self.mappings if row.match_key) > 1:
            problems.append(f"{title}: only one mapping can be the match key.")
        # A Fusion Manage field can be filled once, by a mapping or a static value.
        targets = [row.fm_field_id for row in self.mappings if row.fm_field_id]
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
                "options": dict(self.options)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any], kind: "WorkspaceKind" = None) -> "WorkspaceConfig":
        rows = data.get("mappings")
        statics = data.get("static_values")
        stored = data.get("options") if isinstance(data.get("options"), dict) else {}
        # Keep only options the kind defines, defaulting any that are missing.
        options = {o.option_id: bool(stored.get(o.option_id, o.default))
                   for o in (kind.options if kind else ())}
        return cls(
            options=options,
            workspace_id=str(data.get("workspace_id", "")).strip(),
            mappings=[FieldMapping.from_dict(r) for r in rows if isinstance(r, dict)]
            if isinstance(rows, list) else [],
            static_values=[StaticValue.from_dict(r) for r in statics if isinstance(r, dict)]
            if isinstance(statics, list) else [],
        )


@dataclass
class WorkspaceSettings:
    """Configuration for every workspace kind, keyed by ``WorkspaceKind.kind_id``."""

    workspaces: Dict[str, WorkspaceConfig] = field(
        default_factory=lambda: {k.kind_id: WorkspaceConfig.from_dict({}, k) for k in WORKSPACE_KINDS})

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
            kind.kind_id: WorkspaceConfig.from_dict(data.get(kind.kind_id) or {}, kind)
            for kind in WORKSPACE_KINDS
        })


def catalog() -> Dict[str, Any]:
    """Static lists the panel needs to render workspace cards and mapping rows."""
    return {
        "kinds": [{"id": k.kind_id, "title": k.title, "description": k.description,
                   "options": [{"id": o.option_id, "label": o.label, "description": o.description}
                               for o in k.options]}
                  for k in WORKSPACE_KINDS],
        "source_fields": [{"id": f.field_id, "label": f.label, "kind": f.kind,
                           "can_match": f.can_match} for f in SOURCE_FIELDS],
        "custom_prefix": CUSTOM_PREFIX,
        "base_prefix": BASE_PREFIX,
    }
