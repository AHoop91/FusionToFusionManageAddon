"""Development probe for the publish export.

Publishing needs, for each component of the open design, its data file (to export a
STEP, read a thumbnail) and its drawings (to export PDFs). This probe writes to the
log what the Fusion API exposes for that, so the exporters can be written against
facts. It runs on the UI thread when Add Items is clicked (it blocks Fusion for a moment), and is removed when the exporters
are done.
"""

from typing import Any, Callable, Dict, List

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...core.logging_setup import get_logger
from ..message_bridge import MessageBridge

log = get_logger("publish_probe")

MAX_OCCURRENCES = 25
_INTERESTING = ("export", "pdf", "step", "thumbnail", "datafile", "document", "drawing", "mfgdm", "urn", "lineage", "version")


def _public(obj: Any) -> List[str]:
    """Public attribute names of an API object."""
    return sorted(n for n in dir(obj) if not n.startswith("_"))


def _hints(obj: Any) -> str:
    """Attribute names of ``obj`` that matter for exporting, as one log string."""
    return ", ".join(n for n in _public(obj) if any(h in n.lower() for h in _INTERESTING)) or "(none)"


def _try(label: str, action: Callable[[], Any]) -> Any:
    """Run one probe step; a failing step is logged and never stops the others."""
    try:
        value = action()
        log.info("%s: %s", label, value)
        return value
    except Exception as exc:  # a probe must never disturb the panel
        log.info("%s: FAILED %s: %s", label, type(exc).__name__, exc)
        return None


def _probe_file(label: str, data_file: Any, app: Any) -> None:
    """What a DataFile offers: identity, thumbnail, and whether it can be found again by id."""
    if data_file is None:
        log.info("%s: no data file", label)
        return
    _try(label + " file", lambda: f"id={data_file.id} name={data_file.name} ext={data_file.fileExtension} version={data_file.versionNumber}")
    _try(label + " file members", lambda: _hints(data_file))
    _try(label + " findFileById", lambda: getattr(app.data.findFileById(data_file.id), "name", None))


def run_probe() -> None:
    """Log the export-relevant parts of the Fusion API for the open design."""
    import adsk.core
    import adsk.fusion
    app = adsk.core.Application.get()
    log.info("PROBE start: Fusion %s", _try("version", lambda: app.version))
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        log.info("PROBE: active product is not a design")
        return
    root = design.rootDataComponent
    _try("rootDataComponent", lambda: f"mfgdmModelId={root.mfgdmModelId} timestamp={root.timestamp}")
    _try("rootDataComponent members", lambda: _hints(root))
    _try("design members", lambda: _hints(design))
    _try("exportManager members", lambda: _hints(design.exportManager))
    _try("has createSTEPExportOptions", lambda: hasattr(design.exportManager, "createSTEPExportOptions"))
    _probe_file("root", _try("root dataFile", lambda: design.parentDocument.dataFile), app)
    _try("root thumbnail members", lambda: _hints(design.parentDocument))

    occurrences = design.rootComponent.allOccurrences
    log.info("PROBE occurrences: %d (showing %d)", occurrences.count, min(occurrences.count, MAX_OCCURRENCES))
    for i in range(min(occurrences.count, MAX_OCCURRENCES)):
        occ = occurrences.item(i)
        label = f"occ[{i}] {occ.name}"
        _try(label, lambda: f"referenced={occ.isReferencedComponent} part={occ.component.partNumber} component={occ.component.name}")
        if i == 0:
            _try("occurrence members", lambda: _hints(occ))
            _try("component members", lambda: _hints(occ.component))
        ref = _try(label + " documentReference", lambda: occ.documentReference)
        _probe_file(label, getattr(ref, "dataFile", None) if ref is not None else None, app)

    _try("adsk modules", lambda: [n for n in _public(adsk) if n in ("drawing", "fusion", "core", "cam", "drawings")])
    drawing = _try("adsk.drawing", lambda: __import__("adsk.drawing", fromlist=["x"]))
    if drawing is not None:
        _try("adsk.drawing hints", lambda: _hints(drawing))
        _try("adsk.drawing classes", lambda: ", ".join(_public(drawing)[:60]))
    _try("open documents", lambda: [d.name for d in app.documents])
    log.info("PROBE done")


def register_publish_probe_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService) -> None:
    """Register the probe; it runs when Add Items is clicked."""
    def probe_publish_api(_payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            run_probe()
        except Exception:
            log.exception("Publish probe failed")
        return {}

    bridge.register("probe_publish_api", probe_publish_api)
