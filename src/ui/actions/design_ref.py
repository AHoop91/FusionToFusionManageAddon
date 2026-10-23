"""Which design is open in Fusion, as the Manufacturing Data Model knows it."""

from typing import Tuple


def model_ref() -> Tuple[str, str]:
    """``(model id, timestamp)`` of the open design, or ``("", "")``.

    Both come from the design's root data component. The timestamp pins the
    query to the version open in Fusion and may be empty. Runs on the UI thread.
    """
    import adsk.core
    import adsk.fusion
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    if design is None:
        return "", ""
    data = design.rootDataComponent
    return str(data.mfgdmModelId or ""), str(data.timestamp or "")
