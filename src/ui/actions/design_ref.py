"""Which design is open in Fusion, as the Manufacturing Data Model knows it."""

from typing import Tuple


def model_ref() -> Tuple[str, str]:
    """``(model id, timestamp)`` of the open design, or ``("", "")`` when there is none, or it has no data component yet (it is not saved).

    Both come from the design's root data component. The timestamp pins the query to the version open in Fusion and may be empty. Runs on
    the UI thread. It reads only these two, unlike ``item_numbers.active_design_ref``, so the panel can ask it often.
    """
    import adsk.core   # Fusion's modules are loaded when asked, so what imports this runs without Fusion
    import adsk.fusion
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    data = design.rootDataComponent if design else None
    if data is None:
        return "", ""
    return str(data.mfgdmModelId or ""), str(data.timestamp or "")
