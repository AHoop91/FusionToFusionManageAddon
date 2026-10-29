"""Import what needs Fusion's modules, outside Fusion."""

import contextlib
import sys
from typing import Iterator
from unittest import mock

FUSION_MODULES = ("adsk", "adsk.core", "adsk.fusion")


@contextlib.contextmanager
def fusion_modules_stubbed() -> Iterator[None]:
    """Stand-ins for Fusion's modules while a module that imports them is imported (``src.ui.actions`` imports them for its dialogs).

    Only the stand-ins are removed afterwards. Patching all of ``sys.modules`` would also drop the modules of this project loaded by the
    import, and tests that ran earlier would then hold copies that are no longer the ones imported.
    """
    stubbed = [name for name in FUSION_MODULES if name not in sys.modules]
    for name in stubbed:
        sys.modules[name] = mock.MagicMock()
    try:
        yield
    finally:
        for name in stubbed:
            del sys.modules[name]
