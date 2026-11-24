"""A new manufacturing item, and a bought version of a made one, created in the Items workspace from the form of the workspace.

Both are created with ``ProductService.create`` (an item request is the same for any item) from the values the form of the workspace collects
(``fm.workspace_form``). Nothing here writes a bill of materials: a bought item has no children, and an item made by hand has none yet.

Make or buy is a field of the Items workspace chosen in Settings (``MakeBuyConfig``): no field id is known to the code. A bought version of an
item that is set to Make is a new item (it has its own life cycle and its own revisions):

* its number is the source's number and the suffix of the settings, which the add-in builds: a number the page sends is ignored;
* Make or buy is set to the Buy value, and the source link field is set to the source item;
* every other value the form holds is copied from the source and the person may change it, except what ``plan_copy`` skips;
* it is refused when the source is already a bought item (set to the Buy value; one not yet classified, with Make or buy empty, is allowed), when the number is taken, and when the source has a bought version already.

Nothing keeps a bought item's revision in step with the source: the source link is the source item as it was when the bought item was made.
The v3 search reads an index that lags a little behind a save, so two creations seconds apart can still both pass the check for a number.
"""

import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ..config.workspace_models import MakeBuyConfig, WorkspaceConfig
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..fm.client import WORKSPACES, FmApiError, FmClient
from ..fm.components import number_matches
from ..fm.item_view import load_image
from ..fm.items import ItemService, display_text
from ..fm.mbom import MbomService
from ..fm.refusal import FmRefused
from ..fm.bom import name_of
from ..fm.v3_search import ItemFinder, resolve_hits
from ..fm.mbom import DESCRIPTOR_FIELD, WORKING_FIELD
from ..fm.pages import page_url
from ..fm.v1_search import CONTAINS, DESCRIPTOR_TAB, IS_TRUE, LIFECYCLE, Field, Filter, Sort, V1Row, V1SearchService
from ..fm.workspace_form import (AUTO, CHECKBOX, DATE, IMAGE, INFO, INTEGER, LINK, LINKS, NUMBER, RADIO, SELECT, TEXT, TEXTAREA,
                                 WorkspaceFormService)
from .products import BAD_REQUEST, UNPROCESSABLE, ProductService, link_of

log = get_logger("publish.bought_items")

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")   # what the form's date control holds
_NOT_FILLED = (INFO, AUTO, IMAGE)   # the kinds of form field a person does not fill in
_LOCK_GUARD = threading.Lock()
_LOCKS: Dict[Tuple[str, str], threading.Lock] = {}   # (workspace, item number) -> the lock around checking the number and creating the item

Spec = Dict[str, Any]   # a field of the form, as ``workspace_form`` describes it


def _creation_lock(workspace_id: str, number: str) -> threading.Lock:
    """The lock that makes checking a number and creating the item with it one step, for this process."""
    with _LOCK_GUARD:
        return _LOCKS.setdefault((workspace_id, number.strip().lower()), threading.Lock())


def specs_of(form: Dict[str, Any]) -> Dict[str, Spec]:
    """Every field of a form (``WorkspaceFormService.form``), by its id: those of its sections and of the cells of its matrices."""
    found: Dict[str, Spec] = {}
    for section in form["sections"]:
        for spec in section["fields"]:
            found[spec["id"]] = spec
        for matrix in section["matrices"]:
            for row in matrix["rows"]:
                found.update({spec["id"]: spec for spec in row if spec})
    return found


def without(form: Dict[str, Any], ids: Any) -> Dict[str, Any]:
    """The form with the fields ``ids`` taken out (a matrix cell becomes empty), and a section that has nothing left to fill in left out."""
    sections = []
    for section in form["sections"]:
        fields = [spec for spec in section["fields"] if spec["id"] not in ids]
        matrices = [{**m, "rows": [[None if spec and spec["id"] in ids else spec for spec in row] for row in m["rows"]]} for m in section["matrices"]]
        if fields or any(spec for m in matrices for row in m["rows"] for spec in row):
            sections.append({**section, "fields": fields, "matrices": matrices})
    return {**form, "sections": sections}


def form_value(spec: Spec, value: Any) -> Any:
    """``value`` as Fusion Manage holds it in an item, as the form of ``spec`` takes it (see ``dev/workspace-forms.md``): text as it is, a number as
    text, a tick as ``True``, a picklist option as its link, a linked item as ``{"link"}`` and several as ``[{"link"}]``. A blank value is None.
    Raises ``FmApiError`` for a value that is not shaped as its kind of field is held: it is not guessed at."""
    kind = spec["kind"]

    def wrong() -> Any:
        raise FmApiError(t("app.bought_value_shape", field=spec["title"], kind=kind))

    if value is None or value == [] or (isinstance(value, str) and not value.strip()):
        return None
    if kind in (TEXT, TEXTAREA):
        return value if isinstance(value, str) else wrong()
    if kind == DATE:
        return value if isinstance(value, str) and _DATE.fullmatch(value) else wrong()
    if kind in (INTEGER, NUMBER):
        return str(value) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else wrong()
    if kind == CHECKBOX:   # ticked is ``true``; Fusion Manage gives it as a boolean or as the text "true" / "false" (the Products form reads both)
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            value = value.strip().lower() == "true"
        return (True if value else None) if isinstance(value, bool) else wrong()
    link = value.get("link") if isinstance(value, dict) else None
    if kind in (SELECT, RADIO):
        return link if isinstance(link, str) and link else wrong()
    if kind == LINK:
        return {"link": link} if isinstance(link, str) and link else wrong()
    if kind == LINKS:
        links = [item.get("link") for item in value if isinstance(item, dict)] if isinstance(value, list) else []
        return [{"link": link} for link in links] if links and all(isinstance(link, str) and link for link in links) else wrong()
    return wrong()


def plan_copy(form: Dict[str, Any], source: Dict[str, Any], make_buy: MakeBuyConfig, number_field: str, component_field: str
              ) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """What a bought item takes from its source: ``(values, skipped)``. ``values`` is ``{field id: value as the form takes it}`` for each
    field of the form the source has a value in (a field the form leaves out, being hidden, computed or never edited, is never copied: the form
    has already decided that, and a field in ``make_buy.skip_fields`` is left out); ``skipped`` is ``[{"field", "reason"}]`` for the fields that are set by the add-in or
    are not the bought item's (the item number, Make or buy, the source link and the component link) or are not chosen on the form (a picture: ``create_bought`` copies it as it is). An ``info`` field is never sent."""
    reasons = {number_field: t("data.bought_skip_number"), make_buy.field: t("data.bought_skip_make_buy"),
               make_buy.source_field: t("data.bought_skip_source")}
    if component_field:
        reasons[component_field] = t("data.bought_skip_component")
    specs = specs_of(form)
    skipped = [{"field": field, "reason": reason} for field, reason in reasons.items()]
    values: Dict[str, Any] = {}
    left_out = set(make_buy.skip_fields)   # the fields Settings says are not copied
    for field, spec in specs.items():
        if field in reasons or field in left_out:
            continue
        if spec["kind"] == IMAGE:   # not on the form: ``create_bought`` copies the picture as it is
            skipped.append({"field": field, "reason": t("data.bought_skip_image")})
        elif spec["kind"] not in _NOT_FILLED:
            value = form_value(spec, source.get(field))
            if value is not None:
                values[field] = value
    return values, skipped


def _names(text: str, source_number: str, descriptor: str) -> bool:
    """Whether the title of a source link names the source item itself: its descriptor, or its number alone or then " - " and the name.
    (Not ``number_matches``: it takes "PN-1-2" for "PN-1" too.)"""
    title, number = text.strip().lower(), source_number.strip().lower()
    return title == number or title.startswith(number + " - ") or title == (descriptor or "").strip().lower()


def _texts(row: V1Row, field_id: str) -> List[str]:
    """The titles a row of a v1 search holds in the field ``field_id`` (a blank one is left out)."""
    return [text for key, text in row.entries if key.upper() == field_id.upper() and text]


class Plan(NamedTuple):
    """What a bought version is made from: the form of the workspace and its fields by id, the source (its id, link, descriptor, number and
    values as Fusion Manage holds them) and the new item's number."""
    form: Dict[str, Any]
    specs: Dict[str, Spec]
    source_id: str
    source_link: str
    descriptor: str
    source_number: str
    number: str
    source: Dict[str, Any]


class BoughtItems:
    """Makes manufacturing items and their bought versions in the Items workspace through an ``FmClient``. Call from a worker thread."""

    def __init__(self, client: FmClient, workspace_id: str, cfg: WorkspaceConfig) -> None:
        self._client, self._workspace, self._cfg = client, str(workspace_id), cfg

    @property
    def _make_buy(self) -> MakeBuyConfig:
        return self._cfg.make_buy

    def _form(self) -> Tuple[Dict[str, Any], Dict[str, Spec]]:
        form = WorkspaceFormService(self._client).form(self._workspace)
        return form, specs_of(form)

    def _number_spec(self, specs: Dict[str, Spec], form: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """``(number field, form)`` with the item number a person fills in. Fusion Manage describes the number as given when the item is saved,
        which the form shows as a note (``info``); the add-in writes the number itself when it publishes, so here it is a required text field.
        Raises ``ValueError`` when the number is not mapped and ``FmApiError`` when the form does not hold it."""
        field = self._cfg.item_number_field()
        spec = specs.get(field)
        if spec is None or spec["kind"] not in (TEXT, INFO):
            raise FmApiError(t("app.item_number_not_on_form", field=field))
        entry = {**spec, "kind": TEXT, "required": True, "description": ""}
        sections = [{**section, "fields": [entry if f["id"] == field else f for f in section["fields"]]} for section in form["sections"]]
        specs[field] = entry
        return field, {**form, "sections": sections}

    def _check_make_buy(self, specs: Dict[str, Spec], source: bool) -> Spec:
        """The spec of the Make or buy field, after checking that it is a picklist holding both values (and, for ``source``, that the source
        link field is one that links to an item). Raises ``FmApiError`` saying what to change in the settings."""
        make_buy = self._make_buy
        spec = specs.get(make_buy.field)
        if spec is None or spec["kind"] not in (SELECT, RADIO):
            raise FmApiError(t("app.make_buy_field_not_list", field=make_buy.field))
        options = {option["value"] for option in spec["options"]}
        for value in (make_buy.make_value, make_buy.buy_value):
            if value not in options:
                raise FmApiError(t("app.make_buy_value_not_option", field=spec["title"], value=value))
        if source and (specs.get(make_buy.source_field) or {}).get("kind") != LINK:
            raise FmApiError(t("app.make_buy_source_not_link", field=make_buy.source_field))
        return spec

    @staticmethod
    def _option_title(spec: Spec, link: str) -> str:
        return next(option["title"] for option in spec["options"] if option["value"] == link)

    def assembly_form(self) -> Dict[str, Any]:
        """The form for a new manufacturing item: ``{"form", "locked", "number_field"}``. ``locked`` is ``{field id: value as text}`` for what the add-in
        sets (Make or buy, to Make, when it is set up): the field stays in its section of the form, shown with that value and not to be changed.
        Raises ``FmApiError`` or ``ValueError`` with the reason."""
        form, specs = self._form()
        number_field, form = self._number_spec(specs, form)
        locked: Dict[str, str] = {}
        if self._make_buy.is_set():
            spec = self._check_make_buy(specs, source=False)
            locked[spec["id"]] = self._option_title(spec, self._make_buy.make_value)
        return {"form": form, "locked": locked, "number_field": number_field}

    def create_assembly(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Create a manufacturing item from ``values`` (``{field id: value}``): Make or buy is set to Make when it is set up, whatever the values
        say. Answers ``{"id", "link", "number"}``. Raises ``FmRefused`` for a missing or taken number, else ``FmApiError`` with Fusion Manage's
        reason."""
        number_field = self._cfg.item_number_field()
        number = str(values.get(number_field) or "").strip()
        if not number:
            raise FmRefused(t("app.item_number_required"), UNPROCESSABLE, {number_field: t("app.item_number_required")})
        sent = {**self._editable(values, self._form()[1]), number_field: number}
        if self._make_buy.is_set():
            sent[self._make_buy.field] = self._make_buy.make_value
        with _creation_lock(self._workspace, number):
            if MbomService(self._client).number_taken(self._workspace, number):
                message = t("app.item_number_taken", number=number)
                raise FmRefused(message, UNPROCESSABLE, {number_field: message})
            return self._create(sent, number)

    def _source(self, source_id: str, source_number: str) -> Tuple[str, str]:
        """``(id, descriptor)`` of the source: ``source_id`` as it is (its descriptor is not known, ""), or the item the working version search finds
        for ``source_number`` with its descriptor. Exactly one of the two is given. Raises ``FmApiError`` when neither or both are, when no item has
        the number (publish it first) and when several share it. The search is made on every call: the answer is never kept from the form."""
        if bool(source_id) == bool(source_number.strip()):
            raise FmApiError(t("app.bought_no_source"), UNPROCESSABLE)
        if source_id:
            if not source_id.isdigit():   # it goes into an address
                raise FmApiError(t("app.bought_no_source"), UNPROCESSABLE)
            return source_id, ""
        number = source_number.strip()
        picked, competing = resolve_hits(ItemFinder(self._client).search(self._workspace, number), number)
        if not competing:
            raise FmApiError(t("app.bought_source_not_published", number=number), UNPROCESSABLE)
        if picked is None:
            raise FmApiError(t("app.bought_source_shared", number=number), UNPROCESSABLE)
        return picked["id"], picked["descriptor"]

    def _plan(self, source_id: str, source_number: str) -> Plan:
        """Read the source (given by its id or its item number, see ``_source``) and the form, and check what a bought version needs: the
        settings, a source that is set to Make and has a number, and a new number that fits its field. Raises ``FmApiError`` (or ``ValueError``
        for an item number that is not mapped) with the reason."""
        make_buy = self._make_buy
        if not make_buy.is_set():
            raise FmApiError(t("app.make_buy_not_set_up"), UNPROCESSABLE)
        source_id, _ = self._source(source_id, source_number)
        with ThreadPoolExecutor(max_workers=2) as pair:   # the source and the form do not depend on each other
            read = pair.submit(ItemService(self._client).read_named, self._workspace, source_id)
            form, specs = self._form()
            descriptor, source = read.result()
        return self._planned(source_id, form, specs, descriptor, source)

    def _planned(self, source_id: str, form: Dict[str, Any], specs: Dict[str, Spec], descriptor: str, source: Dict[str, Any]) -> Plan:
        """The ``Plan`` for the source item read (``descriptor``, ``source``) and the form, after the checks ``_plan`` describes."""
        make_buy = self._make_buy
        number_field, form = self._number_spec(specs, form)
        self._check_make_buy(specs, source=True)
        item_number = display_text(source.get(number_field)).strip()
        if not item_number:
            raise FmApiError(t("app.bought_source_no_number"), UNPROCESSABLE)
        if link_of(source.get(make_buy.field)) == make_buy.buy_value:   # a bought item is not made, so there is nothing to buy a version of; one never classified is fine
            raise FmApiError(t("app.bought_source_is_bought", number=item_number), UNPROCESSABLE)
        number = item_number + make_buy.suffix
        limit = specs[number_field]["max_length"]
        if limit and len(number) > limit:
            raise FmApiError(t("app.bought_number_too_long", number=number, length=len(number), max=limit), UNPROCESSABLE)
        return Plan(form, specs, source_id, f"{WORKSPACES}/{self._workspace}/items/{source_id}", descriptor, item_number, number, source)

    @staticmethod
    def _editable(values: Dict[str, Any], specs: Dict[str, Dict[str, Any]], left_out: Tuple[str, ...] = ()) -> Dict[str, Any]:
        """Only the values of fields the form holds and a person may fill, except those of ``left_out``: a page cannot send a hidden, computed, picture
        or information field."""
        return {field: value for field, value in values.items() if field in specs and specs[field]["kind"] not in _NOT_FILLED and field not in left_out}

    def _refuse_if_made(self, plan: Plan) -> None:
        """Raises ``FmRefused`` when the number is taken or the source has a bought version already (an item numbered from the source's whose
        source link field names the source). A failed search raises: it is not "free"."""
        self._refuse(plan, MbomService(self._client).number_taken(self._workspace, plan.number), self._rows_containing(plan.source_number))

    def _refuse(self, plan: Plan, taken: bool, rows: List[V1Row]) -> None:
        """``_refuse_if_made`` for the answers of its two searches: whether the number is ``taken`` and the ``rows`` whose number contains the source's."""
        if taken:
            raise FmRefused(t("app.item_number_taken", number=plan.number), UNPROCESSABLE, {})
        number_field = self._cfg.item_number_field()
        for row in rows:
            if any(_names(text, plan.source_number, plan.descriptor) for text in _texts(row, self._make_buy.source_field)):
                raise FmRefused(t("app.bought_made_from", source=plan.source_number, number=row.values.get(number_field, "")), UNPROCESSABLE, {})

    def _rows_containing(self, text: str) -> List[V1Row]:
        """The rows of the Items workspace (source link field and number field) whose number contains ``text``: one v1 search. A failed search raises."""
        number_field = self._cfg.item_number_field()
        return V1SearchService(self._client).rows(self._workspace, [Field(self._make_buy.source_field), Field(number_field)], [Sort(number_field)],
                                                  [Filter(number_field, CONTAINS, text)])

    def _bought_rows(self, number: str) -> List[V1Row]:
        """The rows of the working versions whose source link contains ``number`` (source link, number, Make or buy and descriptor): one v1 search.
        A failed search raises. The filter ``CONTAINS`` on the source link field has not been checked against a live tenant."""
        make_buy, number_field = self._make_buy, self._cfg.item_number_field()
        fields = [Field(make_buy.source_field), Field(number_field), Field(make_buy.field), Field(DESCRIPTOR_FIELD, DESCRIPTOR_TAB)]
        filters = [Filter(make_buy.source_field, CONTAINS, number), Filter(WORKING_FIELD, IS_TRUE, "", LIFECYCLE)]
        return V1SearchService(self._client).rows(self._workspace, fields, [Sort(number_field)], filters)

    def _found(self, rows: List[V1Row], buy_title: str, number: str, descriptor: str) -> Optional[Dict[str, str]]:
        """``{"id", "link", "number", "name", "url"}`` (``url``: its page in Fusion Manage) of the first row (by item number) that is a bought item (its
        Make or buy is ``buy_title``, lower case) whose source link names the source item itself (``_names``), so another item whose number only
        contains the source's is not taken for it; None when none is."""
        make_buy, number_field = self._make_buy, self._cfg.item_number_field()
        for row in rows:
            bought = any(text.strip().lower() == buy_title for text in _texts(row, make_buy.field))
            if bought and any(_names(text, number, descriptor) for text in _texts(row, make_buy.source_field)):
                return {"id": row.dms_id, "link": f"{WORKSPACES}/{self._workspace}/items/{row.dms_id}", "number": row.values.get(number_field, ""),
                        "url": page_url(self._client.base_url, self._client.tenant, self._workspace, row.dms_id),
                        "name": name_of(row.values.get(DESCRIPTOR_FIELD, ""))}
        return None

    def _look(self, pool: ThreadPoolExecutor, number: str) -> Tuple[Future, Future, Future]:
        """Start the three searches that depend on the source's item number, on ``pool``: ``(number_taken for the new number, the rows that contain
        the number (``_refuse_if_made``), the bought versions (``_bought_rows``))``."""
        return (pool.submit(MbomService(self._client).number_taken, self._workspace, number + self._make_buy.suffix),
                pool.submit(self._rows_containing, number), pool.submit(self._bought_rows, number))

    def open(self, source_id: str = "", source_number: str = "") -> Dict[str, Any]:
        """What the dialog of a bought version shows for the source ``source_id`` (or, when none is given, the item numbered ``source_number``): either
        ``{"found": {"id", "link", "number", "name", "url"}}``, the bought version there is already, or the form for a new one: ``{"form", "number",
        "number_field", "values", "locked", "source_id"}`` (``source_id`` is the source the page sends on with the create, which then searches for nothing).
        When both are given the id is used and ``source_number`` is only the number the page expects it to have, so the searches that need the number
        can start with the item's read; if the item has another number they are made again with its own.

        The item, the form and the searches are read together, after the id is known (a search by ``source_number`` only when no id is given).
        A bought version is decided before anything is refused, as the two requests this replaces did: one bought item whose source link names the source
        (``_found``) is offered, else ``_planned`` and ``_refuse_if_made`` refuse a source that is bought, a number that is too long or taken, and a source
        that has a bought version under another number. Raises ``FmApiError`` or ``FmRefused`` with the reason, and whatever a read raises (a failed search
        is not "none")."""
        make_buy = self._make_buy
        if not make_buy.is_set():
            raise FmApiError(t("app.make_buy_not_set_up"), UNPROCESSABLE)
        expected = source_number.strip()
        source_id, _ = self._source(source_id, "" if source_id else expected)
        number_field = self._cfg.item_number_field()
        with ThreadPoolExecutor(max_workers=8) as pool:
            read = pool.submit(ItemService(self._client).read_named, self._workspace, source_id)
            form_read = pool.submit(self._form)
            looks = self._look(pool, expected) if expected else None
            descriptor, source = read.result()
            number = display_text(source.get(number_field)).strip()
            if number.casefold() != expected.casefold():   # not the item the page expects: what was started was for another number
                looks = self._look(pool, number) if number else None
            form, specs = form_read.result()
            buy_title = self._option_title(self._check_make_buy(specs, source=True), make_buy.buy_value).strip().lower()
            found = self._found(looks[2].result(), buy_title, number, descriptor) if looks else None
            if found:
                return {"found": found}
            plan = self._planned(source_id, form, specs, descriptor, source)   # refuses a source with no number: ``looks`` is set from here on
            self._refuse(plan, looks[0].result(), looks[1].result())
        values, skipped = plan_copy(plan.form, plan.source, make_buy, number_field, self._cfg.component_field)
        locked = self._locked(plan)
        form = without(plan.form, {item["field"] for item in skipped} - set(locked))
        return {"form": form, "number": plan.number, "number_field": number_field, "values": values, "locked": locked, "source_id": source_id}

    def _locked(self, plan: Plan) -> Dict[str, str]:
        """``{field id: value as text}`` of what the add-in sets in a bought version: the item number, Make or buy, the source link and, when the form
        holds it, the component link (empty)."""
        make_buy = self._make_buy
        locked = {self._cfg.item_number_field(): plan.number, make_buy.field: self._option_title(plan.specs[make_buy.field], make_buy.buy_value),
                  make_buy.source_field: plan.descriptor or plan.source_number}
        if self._cfg.component_field in plan.specs:
            locked[self._cfg.component_field] = t("data.bought_locked_none")
        return locked

    def create_bought(self, source_id: str, values: Dict[str, Any], source_number: str = "") -> Dict[str, Any]:
        """Create the bought version of ``source_id`` (or of the item numbered ``source_number``, found again here) from ``values`` (what the form holds, ``{field id: value}``). The number, Make or buy and the
        source link are set here whatever ``values`` hold. Answers ``{"id", "link", "number"}``. Raises as ``open`` does, and ``FmApiError``
        with Fusion Manage's reason (``FmRefused`` names the fields)."""
        plan = self._plan(source_id, source_number)
        make_buy = self._make_buy
        number_field = self._cfg.item_number_field()
        forced = {number_field: plan.number, make_buy.field: make_buy.buy_value, make_buy.source_field: {"link": plan.source_link}}
        sent = {**self._editable(values, plan.specs, (self._cfg.component_field,)), **forced}
        with _creation_lock(self._workspace, plan.number):
            self._refuse_if_made(plan)
            return self._create({**self._pictures(plan), **sent}, plan.number)

    def _pictures(self, plan: Plan) -> Dict[str, str]:
        """``{image field id: the source's picture as a data uri}`` for each image field of the form the source has a picture in, except those Settings
        say are not copied. A picture that cannot be read raises ``FmApiError``: the bought version is not made without it, and nothing is said of it later."""
        left_out = set(self._make_buy.skip_fields)
        pictures: Dict[str, str] = {}
        for field, spec in plan.specs.items():
            if spec["kind"] != IMAGE or field in left_out:
                continue
            link = link_of(plan.source.get(field))
            if not link:
                continue
            picture = load_image(self._client, link)
            if not picture:
                raise FmApiError(t("app.bought_picture_unreadable", source=plan.source_number), UNPROCESSABLE)
            pictures[field] = picture
        return pictures

    def _create(self, values: Dict[str, Any], number: str) -> Dict[str, Any]:
        """Send the create and answer ``{"id", "link", "number"}``. A refusal that Fusion Manage gave as a plain 400 is reported as 422: the panel
        takes a plain 400 for a search it could not read."""
        try:
            made = ProductService(self._client).create(self._workspace, values)
        except FmApiError as exc:
            if exc.status == BAD_REQUEST and not isinstance(exc, FmRefused):
                raise FmApiError(str(exc), UNPROCESSABLE, exc.body) from exc
            raise
        log.info("Created item %s (%s) in workspace %s", number, made["id"], self._workspace)
        return {**made, "number": number}
