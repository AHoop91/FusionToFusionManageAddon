"""Which design is open, as the Data Model knows it. Run: python -m unittest discover tests"""

import sys
import types
import unittest
from unittest import mock

from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions.design_ref import model_ref


def with_design(design):
    """Fake ``adsk`` modules whose active product is ``design`` (``Design.cast`` answers what it is given, as Fusion does for a design)."""
    app = types.SimpleNamespace(activeProduct=design)
    core = types.SimpleNamespace(Application=types.SimpleNamespace(get=lambda: app))
    fusion = types.SimpleNamespace(Design=types.SimpleNamespace(cast=lambda product: product))
    adsk = types.ModuleType("adsk")
    adsk.core, adsk.fusion = core, fusion
    return mock.patch.dict(sys.modules, {"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion})


def design_with(model_id, timestamp):
    return types.SimpleNamespace(rootDataComponent=types.SimpleNamespace(mfgdmModelId=model_id, timestamp=timestamp))


class ModelRefTests(unittest.TestCase):
    def test_the_model_id_and_timestamp_of_the_open_design(self):
        with with_design(design_with("m1", "2024-01-01")):
            self.assertEqual(model_ref(), ("m1", "2024-01-01"))

    def test_no_open_design_gives_empty_text(self):
        with with_design(None):
            self.assertEqual(model_ref(), ("", ""))

    def test_a_design_with_no_data_component_gives_empty_text(self):
        with with_design(types.SimpleNamespace(rootDataComponent=None)):
            self.assertEqual(model_ref(), ("", ""))

    def test_what_fusion_leaves_empty_is_empty_text_not_none(self):
        with with_design(design_with(None, None)):
            self.assertEqual(model_ref(), ("", ""))

    def test_a_timestamp_may_be_empty_while_the_model_id_is_not(self):
        with with_design(design_with("m1", "")):
            self.assertEqual(model_ref(), ("m1", ""))


if __name__ == "__main__":
    unittest.main()
