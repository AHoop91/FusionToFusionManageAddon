"""Fusion Manage workspace configuration.

Each workspace the add-in writes to (items today; BOMs and others later) has
its own workspace id and its own field mapping: which Manufacturing Data
Model field fills which Fusion Manage field.

To support another workspace, add a ``WorkspaceKind`` to ``WORKSPACE_KINDS``.
To offer another source field, add a ``SourceField`` to ``SOURCE_FIELDS``.
"""

import re
from dataclasses import asdict, dataclass, field
from dataclasses import field as new_field   # ``MakeBuyConfig`` has a field named ``field``
from typing import Any, Dict, List, Optional

from ..core.shapes import dict_rows
from ..core.i18n import t
from .problems import Problem


@dataclass(frozen=True)
class FieldNeed:
    """A field a workspace must have: by its id, so a renamed title does not matter."""

    field_id: str
    type: str = ""   # the title of the field's type in Fusion Manage ("Single Selection"); "" takes any type
    section: str = ""   # the title of the section that holds it; "" takes any section


@dataclass(frozen=True)
class WorkspaceSchema:
    """What marks a workspace as the one a kind of workspace works with. The administrator may add more; nothing here may be missing."""

    tabs: tuple = ()   # ``workspaceTabName`` of each tab the workspace needs (e.g. "ITEM_DETAILS")
    fields: tuple = ()   # a ``FieldNeed`` for each field it needs


@dataclass(frozen=True)
class WorkspaceKind:
    """A workspace the add-in works with."""

    kind_id: str
    # Short FM permission names the user needs on the workspace at all.
    required_permissions: tuple = ()
    # DefaultMapping rows the "Add default fields" button adds.
    default_mappings: tuple = ()
    # Name (or the start of the name) of the picklist that links an item to a component (e.g. CUSTOM_LOOKUP_WS_COMPONENTS_...);
    # the workspace's Fusion Manage field using it is the "Component linking" field. Empty: none.
    component_lookup: str = ""
    # False: the workspace is only chosen by its id (no field mapping, no default values).
    mapped: bool = True
    # True: only revision controlled workspaces are offered for it; False: any workspace of the tenant.
    revision_only: bool = True
    # What the workspace must hold to be accepted (tabs, fields); None: nothing is checked beyond permissions.
    schema: Optional[WorkspaceSchema] = None
    # True: products are assigned in it, so its settings also say which field holds the Primary Component and which grid column the variants are linked in.
    assign: bool = False


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


COMPONENT_LOOKUPS = "CUSTOM_LOOKUP_WS_COMPONENTS"   # starts the name of every picklist that lists the items of the Components workspace

WORKSPACE_KINDS = [
    # The item BOM is always published, so its permissions are required.
    WorkspaceKind("items",
                  ("view_items", "add_items", "edit_items", "view_bom", "add_to_bom", "edit_bom"),
                  (DefaultMapping("item_number", "NUMBER"), DefaultMapping("name", "TITLE"),
                   DefaultMapping("description", "DESCRIPTION"), DefaultMapping("thumbnail", "IMAGE"),
                   DefaultMapping("material", "MATERIAL"),
                   DefaultMapping("physical:Height", "HEIGHT"), DefaultMapping("physical:Width", "WIDTH"),
                   DefaultMapping("physical:Length", "LENGTH"), DefaultMapping("physical:Mass", "ITEM_WEIGHT")),
                  "CUSTOM_LOOKUP_WS_COMPONENTS_ALL_INCLUDING_WORKING"),
    # Product Portfolio Management: the workspace, the field of the Primary Component and the Variants grid.
    WorkspaceKind("portfolio",
                  ("view_items",), mapped=False, revision_only=False, assign=True,
                  component_lookup=COMPONENT_LOOKUPS),
]

KINDS_BY_ID = {k.kind_id: k for k in WORKSPACE_KINDS}
ITEMS_KIND = "items"   # the kind the Item panel, the publish and the BOM work with
PORTFOLIO_KIND = "portfolio"   # the kind of the Portfolio Management tab
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
    """What the panel calls a source field: its label, or the property name for a named hub property. Always English, whatever the language:
    the names are the component's properties, which are mapped by name, and the lists of properties from the hub are in English too."""
    known = _SOURCES_BY_ID.get(source)
    return known.label if known else data_model_name(source) or source


def kind_texts(kind: WorkspaceKind) -> tuple:
    """The title and description of a workspace kind, in the language in use. Raises ``ValueError`` for a kind with no texts."""
    if kind.kind_id == ITEMS_KIND:
        return t("data.ws_kind_items_title"), t("data.ws_kind_items_description")
    if kind.kind_id == PORTFOLIO_KIND:
        return t("data.ws_kind_portfolio_title"), t("data.ws_kind_portfolio_description")
    raise ValueError(f"No texts for the workspace kind {kind.kind_id!r}")


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
class VariantsConfig:
    """The Variants grid of a product: the column that links each row to its component."""

    link_column: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"link_column": self.link_column}

    @classmethod
    def from_dict(cls, data: Any) -> "VariantsConfig":
        return cls(link_column=str(data.get("link_column", "")).strip() if isinstance(data, dict) else "")


SUFFIX_MAX = 20   # most characters of the suffix a bought item's number takes after its source's number
OPTION_PREFIX = "/api/v3/lookups/"   # the start of the link of a picklist option (``fm.client.LOOKUPS``, which this package cannot import: it imports this one)
_SUFFIX = re.compile(r"[A-Za-z0-9._-]+")   # what an item number may hold, as the add-in writes numbers


@dataclass
class MakeBuyConfig:
    """Make or buy on the Items workspace: which field says it, its two values, the field that links a bought item to the item it is bought as,
    and the suffix that makes a bought item's number from its source's. The values are the links of picklist options. Nothing is known of the
    tenant's field ids, so every part is chosen in Settings; the feature is off until all five are."""

    field: str = ""
    make_value: str = ""
    buy_value: str = ""
    source_field: str = ""
    suffix: str = ""
    # The ids of the fields a bought version does not copy from its source (besides what the add-in sets itself). Empty: every field the form holds is copied.
    skip_fields: List[str] = new_field(default_factory=list)

    def is_set(self) -> bool:
        """Whether every part is chosen (a bought version can be made)."""
        return all((self.field, self.make_value, self.buy_value, self.source_field, self.suffix))

    def is_touched(self) -> bool:
        """Whether any part is chosen."""
        return any((self.field, self.make_value, self.buy_value, self.source_field, self.suffix))

    def problems(self) -> List[Problem]:
        """What is wrong with the choices (none when nothing is chosen). A field filled twice is reported by ``WorkspaceConfig._filled_twice``."""
        if not self.is_touched():
            return []
        problems: List[Problem] = []
        parts = (("field", self.field), ("make_value", self.make_value), ("buy_value", self.buy_value), ("source_field", self.source_field),
                 ("suffix", self.suffix))
        unset = next((part for part, value in parts if not value), "")
        if unset:
            problems.append(Problem(t("data.ws_make_buy_incomplete"), area="make_buy", part=unset))
        if self.suffix and (len(self.suffix) > SUFFIX_MAX or not _SUFFIX.fullmatch(self.suffix)):
            problems.append(Problem(t("data.ws_make_buy_suffix", max=SUFFIX_MAX), area="make_buy", part="suffix"))
        for part, value in (("make_value", self.make_value), ("buy_value", self.buy_value)):
            if value and not value.startswith(OPTION_PREFIX):   # a value is an option of the field's picklist, held as its link
                problems.append(Problem(t("data.ws_make_buy_value_not_option"), area="make_buy", part=part))
        if self.make_value and self.make_value == self.buy_value:
            problems.append(Problem(t("data.ws_make_buy_same_value"), area="make_buy", part="buy_value"))
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "MakeBuyConfig":
        data = data if isinstance(data, dict) else {}
        left = data.get("skip_fields")
        ids = [str(item).strip() for item in left] if isinstance(left, list) else []
        return cls(**{name: str(data.get(name, "")).strip() for name in ("field", "make_value", "buy_value", "source_field", "suffix")},
                   skip_fields=list(dict.fromkeys(item for item in ids if item)))


@dataclass
class WorkspaceConfig:
    """A workspace id, its field mapping and its static values."""

    workspace_id: str = ""
    mappings: List[FieldMapping] = field(default_factory=list)
    static_values: List[StaticValue] = field(default_factory=list)
    # The Fusion Manage field that links an item to its component ("" = not linked).
    component_field: str = ""
    # The Variants grid of a product (only a workspace of a kind that is assigned uses it).
    variants: VariantsConfig = field(default_factory=VariantsConfig)
    # Make or buy (only the Items workspace uses it).
    make_buy: MakeBuyConfig = field(default_factory=MakeBuyConfig)
    # Whether the feature of the workspace's kind is on at all (both the Items and the Portfolio Management kinds can be turned off).
    enabled: bool = True

    def maps_physical(self) -> bool:
        """Whether a mapped field takes a physical property (mass, volume ...): they are slow to read, so only a caller that maps them asks."""
        return any(m.source.startswith(PHYSICAL_PREFIX) and m.fm_field_id for m in self.mappings)

    def item_number_field(self) -> str:
        """The id of the Fusion Manage field the item number is mapped to. Raises ``ValueError`` when it is not mapped (``validate`` reports it too)."""
        field = next((m.fm_field_id for m in self.mappings if m.source == ITEM_NUMBER_SOURCE), "")
        if not field:
            raise ValueError(t("data.ws_item_number_not_mapped", field=LEGACY_NUMBER_FIELD))
        return field

    def setup_problem(self, title: str, mapped: bool = True) -> str:
        """Why this workspace cannot be used yet ("" when its settings are complete): it needs a workspace ID and, unless ``mapped`` is False
        (a workspace only chosen by its id), valid mappings. A workspace that is turned off cannot be used either."""
        if not self.enabled:
            return t("data.ws_off", title=title)
        if not self.workspace_id:
            return t("data.ws_id_not_set", title=title)
        problems = self.validate(mapped)
        return problems[0] if problems else ""

    def validate(self, mapped: bool = True) -> List[str]:
        """Return human-readable problems, each saying which row it is in and what to do. ``mapped`` is False for a workspace that is only
        chosen by its id: nothing about mappings is checked then."""
        problems: List[str] = []
        if self.workspace_id and not self.workspace_id.isdigit():
            problems.append(Problem(t("data.ws_id_not_number"), area="id"))
        if not mapped:
            return problems
        problems += self._mapping_problems()
        for index, row in enumerate(self.static_values):
            if not row.fm_field_id:
                problems.append(Problem(t("data.ws_choose_field", name=t("data.ws_default_value", n=index + 1)), area="static", row=index, part="field"))
        problems += self.make_buy.problems()
        problems += self._filled_twice()
        if self.workspace_id and not any(row.source == ITEM_NUMBER_SOURCE for row in self.mappings):
            problems.append(Problem(t("data.ws_item_number_not_mapped", field=LEGACY_NUMBER_FIELD), area="mappings"))
        return problems

    def _mapping_problems(self) -> List[Problem]:
        """The mapped rows whose source is not valid or is used by an earlier row, and those with no Fusion Manage field."""
        problems: List[Problem] = []
        first_row_of_source: Dict[str, int] = {}
        for index, row in enumerate(self.mappings):
            name = t("data.ws_mapped_field", n=index + 1)
            if not is_valid_source(row.source):
                what = t("data.ws_enter_property_name") if row.source.strip() else t("data.ws_choose_property")
                problems.append(Problem(t("data.ws_row_problem", name=name, what=what), area="mapping", row=index, part="source"))
            elif row.source in first_row_of_source:
                problems.append(Problem(
                    t("data.ws_property_used_twice", name=name, property=_source_label(row.source), other=first_row_of_source[row.source] + 1),
                    area="mapping", row=index, part="source"))
            else:
                first_row_of_source[row.source] = index
            if not row.fm_field_id:
                problems.append(Problem(t("data.ws_choose_field", name=name), area="mapping", row=index, part="field"))
        return problems

    def _filled_twice(self) -> List[Problem]:
        """A Fusion Manage field can be filled once: by a mapped field, the Component field or a default value."""
        problems: List[Problem] = []
        filled: Dict[str, str] = {}
        places = ([("mapping", i, t("data.ws_mapped_field", n=i + 1), t("data.ws_mapped_field_inline", n=i + 1), r.fm_field_id) for i, r in enumerate(self.mappings)]
                  + [("component", 0, t("data.ws_component_field"), t("data.ws_component_field_inline"), self.component_field)]
                  + [("make_buy", 0, t("data.ws_make_buy_field"), t("data.ws_make_buy_field_inline"), self.make_buy.field),
                     ("make_buy", 0, t("data.ws_make_buy_source"), t("data.ws_make_buy_source_inline"), self.make_buy.source_field)]
                  + [("static", i, t("data.ws_default_value", n=i + 1), t("data.ws_default_value_inline", n=i + 1), r.fm_field_id)
                     for i, r in enumerate(self.static_values)])
        for area, index, name, inline, fm_field_id in places:
            if not fm_field_id:
                continue
            if fm_field_id in filled:
                problems.append(Problem(
                    t("data.ws_field_filled_twice", name=name, field=fm_field_id, by=filled[fm_field_id]), area=area, row=index, part="field"))
            else:
                filled[fm_field_id] = inline
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return {"workspace_id": self.workspace_id,
                "mappings": [row.to_dict() for row in self.mappings],
                "static_values": [row.to_dict() for row in self.static_values],
                "component_field": self.component_field,
                "variants": self.variants.to_dict(),
                "make_buy": self.make_buy.to_dict(),
                "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceConfig":
        mappings = [FieldMapping.from_dict(r) for r in dict_rows(data.get("mappings"))]
        # Earlier versions mapped the Part number to NUMBER; the Item Number is what that field holds now.
        if not any(m.source == ITEM_NUMBER_SOURCE for m in mappings):
            for m in mappings:
                if m.source == "part_number" and m.fm_field_id == LEGACY_NUMBER_FIELD:
                    m.source = ITEM_NUMBER_SOURCE
        return cls(
            workspace_id=str(data.get("workspace_id", "")).strip(),
            component_field=str(data.get("component_field", "")).strip(),
            variants=VariantsConfig.from_dict(data.get("variants")),
            make_buy=MakeBuyConfig.from_dict(data.get("make_buy")),
            enabled=data.get("enabled", True) is not False,
            mappings=mappings,
            static_values=[StaticValue.from_dict(r) for r in dict_rows(data.get("static_values"))],
        )


@dataclass
class WorkspaceSettings:
    """Configuration for every workspace kind, keyed by ``WorkspaceKind.kind_id``."""

    workspaces: Dict[str, WorkspaceConfig] = field(
        default_factory=lambda: {k.kind_id: WorkspaceConfig() for k in WORKSPACE_KINDS})

    def get(self, kind_id: str) -> WorkspaceConfig:
        """The settings of a workspace kind. Raises ``KeyError`` for a kind that is not one of ``WORKSPACE_KINDS``."""
        return self.workspaces[kind_id]

    def validate(self) -> List[str]:
        problems: List[str] = []
        for kind in WORKSPACE_KINDS:
            for problem in self.get(kind.kind_id).validate(kind.mapped):
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


def _kind_entry(kind: WorkspaceKind) -> Dict[str, Any]:
    """One workspace kind as the panel renders its card."""
    title, description = kind_texts(kind)
    return {"id": kind.kind_id, "title": title, "description": description, "component_lookup": kind.component_lookup, "mapped": kind.mapped,
            "revision_only": kind.revision_only, "assign": kind.assign, "default_mappings": [asdict(m) for m in kind.default_mappings]}


def catalog() -> Dict[str, Any]:
    """Static lists the panel needs to render workspace cards and mapping rows."""
    return {
        "kinds": [_kind_entry(k) for k in WORKSPACE_KINDS],
        "source_fields": [{"id": f.field_id, "label": f.label, "kind": f.kind} for f in SOURCE_FIELDS],
        "custom_prefix": CUSTOM_PREFIX,
        "base_prefix": BASE_PREFIX,
        "physical_prefix": PHYSICAL_PREFIX,
    }
