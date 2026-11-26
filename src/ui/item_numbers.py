"""The Item Number of a component, from the Manufacturing Data Model (integration layer: it reads the Data Model and a file of kept answers).

Fusion's API gives a component only its part number, and a part number need not match its item number. The item number is
what Fusion Manage knows an item by, so it is read from the Data Model: the design's own from its summary, a component below it
from the design's bill of materials (read once per version of the design and kept). A component with no item number has not
been published, so it is refused with ``NoItemNumber``.
"""

import json
import os
import threading
from functools import cache
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import adsk.core
import adsk.fusion

from ..core.cancel import CancelToken
from ..core.i18n import t
from ..core.logging_setup import get_logger
from ..core.paths import DataDirError, data_dir, temp_dir
from ..core.shapes import as_dict, dig
from ..fm.components import manage_link
from ..fusion_mfg.design_reads import DesignReads
from ..fusion_mfg.fusion_graphql_client import FusionGraphQlClient, MfgApiError
from ..fusion_mfg.hub_lookup import read_hub_id
from ..fusion_mfg.model_service import read_manage_item, read_thumbnail_url
from .item_number_error import NoItemNumber

log = get_logger("item_numbers")

# The Data Model's model of a design file (the hub's item whose id is the file's lineage id).
FILE_MODEL_QUERY = """
query ($hubId: ID!, $itemId: ID!) {
  item(hubId: $hubId, itemId: $itemId) {
    ... on DesignItem { tipRootModel { id timestamp } }
  }
}
"""


class DesignRef(NamedTuple):
    """Which version of which design to read: ``model_id`` and ``time`` as the Publish panel uses them."""

    model_id: str
    time: str
    file_id: str = ""   # the design's data file (lineage) id and the hub's name: what a design that Fusion has not loaded is found by
    hub_name: str = ""


class Subject(NamedTuple):
    """A component as Fusion Manage and Fusion each name it."""

    item_number: str   # what Fusion Manage finds the item by
    part_number: str   # what Fusion calls the component, to find it in the open design


def design_ref(design: Any) -> DesignRef:
    """The Data Model id and version of ``design``. A design a drawing references is not loaded by Fusion (it has no data component, so no
    id): its data file id and hub are given instead, and ``ItemNumbers`` asks the Data Model for the id. Empty when it is not saved. UI thread."""
    if design is None:
        return DesignRef("", "")
    data = design.rootDataComponent
    try:
        file_id = str(design.parentDocument.dataFile.id or "")
        hub = adsk.core.Application.get().data.activeHub
    except (AttributeError, RuntimeError):
        file_id, hub = "", None
    hub_name = hub.name if hub else ""
    if data is None:
        return DesignRef("", "", file_id, hub_name)
    return DesignRef(str(data.mfgdmModelId or ""), str(data.timestamp or ""), file_id, hub_name)


def component_ref(component: Any, design: Any) -> Optional[DesignRef]:
    """The reference of a component's own Data Model model, which Fusion gives a component that lives in a document of its own. Its summary
    names the component, so the design's bill of materials need not be read to find it. ``None`` for the design's top, a component with no
    model of its own, or one that shares the design's model: those are found in the design. UI thread."""
    try:
        model = str(component.mfgdmModelId or "")
        if not model or design is None or component.id == design.rootComponent.id or model == str(design.rootComponent.mfgdmModelId or ""):
            return None
    except (AttributeError, RuntimeError):
        return None
    return design_ref(design)._replace(model_id=model, time="")


def active_design_ref() -> DesignRef:
    """The reference of the open design. UI thread."""
    return design_ref(adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct))


def _same(a: str, b: str) -> bool:
    """Whether two part numbers are the same, ignoring case and surrounding spaces."""
    return a.strip().lower() == b.strip().lower()


class _Remembered:
    """Item numbers already found, kept in a file so they outlast Fusion. A saved version of a design never changes, so what was read for
    ``(model_id, time, part number)`` is still true. Only found numbers are kept; a missing one may be given later. Failures to read or write
    the file are logged and otherwise ignored: the Data Model is asked instead."""

    LIMIT = 1000   # entries kept; the oldest go first

    def __init__(self, path: str) -> None:
        self._path = path
        self._entries: Dict[str, List[str]] = self._load()

    @staticmethod
    def _key(ref: DesignRef, part_number: str) -> str:
        return f"{ref.model_id}|{ref.time}|{part_number.strip().lower()}"

    def _load(self) -> Dict[str, List[str]]:
        """The entries of the file; none when it is missing or not readable."""
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return {k: v for k, v in data.items() if isinstance(v, list) and len(v) == 2}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, AttributeError) as exc:
            log.warning("Item numbers kept from earlier are not read: %s", exc)
            return {}

    def get(self, ref: DesignRef, part_number: str) -> Optional[Subject]:
        """What was found for the part number in this version of the design, or None."""
        found = self._entries.get(self._key(ref, part_number))
        return Subject(found[0], found[1]) if found else None

    def add(self, ref: DesignRef, part_number: str, subject: Subject) -> None:
        """Keep what was found, as the newest entry, and write the file."""
        key = self._key(ref, part_number)
        self._entries.pop(key, None)   # re-added last, so it is the newest
        self._entries[key] = [subject.item_number, subject.part_number]
        while len(self._entries) > self.LIMIT:
            del self._entries[next(iter(self._entries))]
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._entries, f)
        except OSError as exc:
            log.warning("Item numbers are not kept for next time: %s", exc)


def _remembered_path() -> str:
    """Where the found item numbers are kept."""
    try:
        folder = data_dir()
    except DataDirError:   # what is remembered is only a shortcut: the add-in's folder in the temporary folder will do
        folder = temp_dir()
    return os.path.join(folder, "item_numbers.json")


class ItemNumbers:
    """Finds item numbers; the reads run on a worker thread, never on Fusion's."""

    def __init__(self, remembered_path: Optional[str] = None) -> None:
        self._remembered = _Remembered(remembered_path or _remembered_path())
        self.reads = DesignReads()   # the Data Model's summary and bill of materials of the design in use, read once per saved version
        self._file_lock = threading.Lock()   # one find of a design by its file at a time (the read ahead and the click arrive together)
        self._files: Dict[str, Tuple[str, str]] = {}   # design file id -> (model id, time), kept while the Export window is open
        self._hubs: Dict[str, str] = {}   # hub name -> hub id

    def _model_of_file(self, client: FusionGraphQlClient, ref: DesignRef) -> DesignRef:
        """``ref`` with the Data Model id of its design, found from the design's data file (the hub's item whose id is the file's lineage id)."""
        with self._file_lock:
            kept = self._files.get(ref.file_id)
            if kept is None:
                if ref.hub_name not in self._hubs:
                    self._hubs[ref.hub_name] = read_hub_id(client, ref.hub_name)
                data = client.query(FILE_MODEL_QUERY, {"hubId": self._hubs[ref.hub_name], "itemId": ref.file_id})
                model = as_dict(dig(data, "item", "tipRootModel"))
                if not model.get("id"):
                    raise NoItemNumber(t("app.number_drawing_design_not_found"))
                log.info("Design file %s is the Data Model's %s", ref.file_id, model["id"])
                kept = (str(model["id"]), str(model.get("timestamp") or ""))
                self._files[ref.file_id] = kept
        return ref._replace(model_id=kept[0], time=kept[1])

    def model_of(self, ref: DesignRef, cancel: Optional[CancelToken] = None) -> DesignRef:
        """``ref`` with its Data Model id (a design a drawing shows is found by its file). Raises ``NoItemNumber`` when the design is not saved. Worker thread."""
        if ref.model_id:
            return ref
        self._require_saved(ref)
        return self._model_of_file(FusionGraphQlClient(cancel), ref)

    def forget_files(self) -> None:
        """Drop the models found for design files, so the next lookup asks again (the design may have been saved since)."""
        with self._file_lock:
            self._files.clear()

    def _matching(self, client: FusionGraphQlClient, ref: DesignRef, summary: Dict[str, Any], part_number: str) -> Tuple[bool, List[Dict[str, Any]]]:
        """``(is the design itself, the components that have this part number)``, each with its ``id``, ``item_number`` and ``part_number``: the
        design's top from its summary ("" or its own part number), else the lines of its bill of materials (read once per version, then kept)."""
        top_part = str(summary.get("part_number") or "")
        if not part_number or _same(part_number, top_part):
            return True, [{"id": summary.get("component_id"), "item_number": summary.get("item_number"), "part_number": top_part}]
        rows = self.reads.structure(client, ref.model_id, ref.time, summary)
        return False, [r for r in rows if _same(str(r["part_number"]), part_number)]

    def thumbnail_url(self, ref: DesignRef, part_number: str, cancel: Optional[CancelToken] = None) -> str:
        """A signed url of the thumbnail of the component with ``part_number`` in the design ``ref`` ("" is the design itself); "" when the Data
        Model has none yet. It expires soon, so use it at once. Raises ``NoItemNumber`` when the component is not in the design. Worker thread."""
        ref, client, summary = self._summary_of(ref, cancel)
        return read_thumbnail_url(client, summary, self._the_component(client, ref, summary, part_number), ref.time)

    def _summary_of(self, ref: DesignRef, cancel: Optional[CancelToken]) -> Tuple[DesignRef, FusionGraphQlClient, Dict[str, Any]]:
        """``(ref with its model, Data Model client, summary of the design)``."""
        ref = self.model_of(ref, cancel)
        client = FusionGraphQlClient(cancel)
        return ref, client, self.reads.summary(client, ref.model_id, ref.time)

    @staticmethod
    def _require_saved(ref: DesignRef) -> None:
        """Raises ``NoItemNumber`` when the design is not saved."""
        if not ref.model_id and not ref.file_id:
            raise NoItemNumber(t("app.number_design_not_saved"))

    def _the_component(self, client: FusionGraphQlClient, ref: DesignRef, summary: Dict[str, Any], part_number: str) -> str:
        """The Data Model id of the component with ``part_number`` in the design. Raises ``NoItemNumber`` when there is no such component, or
        there are several."""
        _, matches = self._matching(client, ref, summary, part_number)
        ids = {str(m["id"] or "") for m in matches} - {""}
        if len(ids) != 1:
            label = part_number or t("app.number_the_design")
            raise NoItemNumber(t("app.number_not_in_bom", label=label) if not ids else t("app.number_several_components", label=label))
        return ids.pop()

    def describe(self, ref: DesignRef, cancel: Optional[CancelToken] = None) -> Dict[str, str]:
        """``{"number", "name", "thumbnail_url"}`` of the design itself, from the Data Model: its item number ("" when it has none), its name and
        a signed url of its thumbnail ("" when it has none yet or it could not be read; it expires soon). Raises ``NoItemNumber`` when the design
        is not saved. Worker thread."""
        ref, client, summary = self._summary_of(ref, cancel)
        try:
            thumbnail = read_thumbnail_url(client, summary, str(summary.get("component_id") or ""), ref.time)
        except MfgApiError as exc:   # the picture only decorates the answer: the design is described without it
            log.warning("The thumbnail of the design could not be read: %s", exc)
            thumbnail = ""
        return {"number": str(summary.get("item_number") or "").strip(), "name": str(summary.get("name") or summary.get("part_number") or ""),
                "thumbnail_url": thumbnail if thumbnail.startswith("https://") else ""}

    def record_link(self, ref: DesignRef, part_number: str = "", cancel: Optional[CancelToken] = None) -> str:
        """The API link of the record in the Components workspace (``/api/v3/workspaces/<workspace>/items/<item>``) of the component with
        ``part_number`` in the design ``ref`` ("" is the design itself), from the Data Model: "" when it is not linked to one yet. Raises
        ``NoItemNumber`` when the design is not saved or has no such component. Worker thread."""
        ref, client, summary = self._summary_of(ref, cancel)
        linked = read_manage_item(client, summary, self._the_component(client, ref, summary, part_number), ref.time)
        return manage_link(linked["urn"], linked["url"])

    def resolve(self, ref: DesignRef, part_number: str, cancel: Optional[CancelToken] = None) -> Subject:
        """The ``Subject`` of the component with ``part_number`` in the design ``ref`` ("" is the design itself). Worker thread."""
        self._require_saved(ref)
        data_model = cache(lambda: FusionGraphQlClient(cancel))   # made when the Data Model is first asked, so an item number kept from before needs no settings
        if not ref.model_id:   # a design a drawing references: Fusion has not loaded it, so it is found by its file
            ref = self._model_of_file(data_model(), ref)
        known = self._remembered.get(ref, part_number)
        if known:
            log.info("Part number %s is item number %s (kept from an earlier read)", known.part_number or "(the design)", known.item_number)
            return known
        subject = self._read_subject(data_model(), ref, part_number)
        self._remembered.add(ref, part_number, subject)
        return subject

    def _read_subject(self, client: FusionGraphQlClient, ref: DesignRef, part_number: str) -> Subject:
        """The ``Subject`` of the component with ``part_number`` in the design ``ref``, read from the Data Model. Raises ``NoItemNumber`` when
        the design has no such component, the component has several item numbers, or it has none (it is not published). Worker thread."""
        summary = self.reads.summary(client, ref.model_id, ref.time)
        is_design, matches = self._matching(client, ref, summary, part_number)
        found = {str(m["item_number"] or "") for m in matches}
        if is_design:
            part_number = matches[0]["part_number"]
        label = part_number or t("app.number_the_design")
        if not found:
            raise NoItemNumber(t("app.number_not_in_bom", label=label))
        if len(found) > 1:
            raise NoItemNumber(t("app.number_several_item_numbers", part_number=part_number))
        number = found.pop().strip()
        if not number:
            raise NoItemNumber(t("app.number_not_published", label=label))
        log.info("Part number %s is item number %s", part_number or "(the design)", number)
        return Subject(number, part_number)
