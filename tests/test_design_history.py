"""When what the Export window exports was last saved: which document answers for a drawing, a component, a design, and what is said when none can."""

import sys
import types
import unittest
from unittest import mock


class _Stub(types.ModuleType):
    """A stand-in for Fusion's ``adsk`` modules: any name in it is an empty class."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(name, (), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, value)
        return value


_NAMES = ("adsk", "adsk.core", "adsk.fusion", "adsk.drawing")
_saved = {}
design_history = None


def setUpModule():
    global design_history
    for name in _NAMES:
        _saved[name] = sys.modules.get(name)
        sys.modules[name] = _Stub(name)
    for sub in ("core", "fusion", "drawing"):
        setattr(sys.modules["adsk"], sub, sys.modules["adsk." + sub])
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]
    from src.ui import design_history as module
    design_history = module


def tearDownModule():
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _document(name, saved, modified=False, references=()):
    data_file = types.SimpleNamespace(versionNumber=1, latestVersionNumber=1, dateCreated=saved)
    return types.SimpleNamespace(name=name, dataFile=data_file, isModified=modified, documentReferences=list(references))


def _occurrence(number, name="Bracket", saved=None):
    reference = types.SimpleNamespace(dataFile=types.SimpleNamespace(versionNumber=1, latestVersionNumber=1, dateCreated=saved))
    component = types.SimpleNamespace(partNumber=number, name=name)
    return types.SimpleNamespace(component=component, documentReference=reference)


class SavedStateTest(unittest.TestCase):
    def setUp(self):
        self.app = types.SimpleNamespace(activeDocument=None, activeProduct=None)
        fake = types.SimpleNamespace(
            core=types.SimpleNamespace(Application=types.SimpleNamespace(get=lambda: self.app)),
            fusion=types.SimpleNamespace(Design=types.SimpleNamespace(cast=lambda product: product),
                                         Occurrence=types.SimpleNamespace(cast=lambda entity: entity if hasattr(entity, "component") else None)))
        self.drawing = False
        for patcher in (mock.patch.object(design_history, "adsk", fake),
                        mock.patch.object(design_history.drawing_source, "active_drawing", lambda: object() if self.drawing else None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_no_open_document_has_no_date(self):
        answer = design_history.saved_state("PN-1", [])
        self.assertIsNone(answer["saved"])
        self.assertTrue(answer["reason"])

    def test_a_design_is_dated_by_its_own_document(self):
        self.app.activeDocument = _document("Frame", 100.0)
        self.app.activeProduct = object()
        answer = design_history.saved_state("PN-1", [])
        self.assertEqual((answer["saved"], answer["unsaved"], answer["reason"]), (100.0, False, ""))
        self.assertIn("Frame", answer["saved_in"])

    def test_a_design_with_changes_not_saved_says_so(self):
        self.app.activeDocument = _document("Frame", 100.0, modified=True)
        self.app.activeProduct = object()
        answer = design_history.saved_state("PN-1", [])
        self.assertTrue(answer["unsaved"])
        self.assertIn("Frame", answer["unsaved_in"])

    def test_a_selected_component_is_dated_by_its_own_document(self):
        self.app.activeDocument = _document("Frame", 100.0)
        self.app.activeProduct = object()
        answer = design_history.saved_state("PN-2", [_occurrence("PN-2", "Bracket", saved=300.0)])
        self.assertEqual(answer["saved"], 300.0)
        self.assertIn("Bracket", answer["saved_in"])

    def test_a_drawing_is_dated_by_the_later_save_of_it_and_its_designs(self):
        design = _document("Frame", 500.0)
        self.app.activeDocument = _document("Sheet", 100.0, references=[types.SimpleNamespace(referencedDocument=design),
                                                                        types.SimpleNamespace(referencedDocument=None)])
        self.drawing = True
        answer = design_history.saved_state("PN-1", [])
        self.assertEqual(answer["saved"], 500.0)
        self.assertIn("Frame", answer["saved_in"])

    def test_a_document_that_cannot_be_dated_is_not_guessed(self):
        self.app.activeDocument = types.SimpleNamespace(name="Frame", dataFile=None, isModified=False)
        self.app.activeProduct = object()
        answer = design_history.saved_state("PN-1", [])
        self.assertIsNone(answer["saved"])
        self.assertIn("Frame", answer["reason"])

    def test_with_no_design_and_no_drawing_there_is_no_holder(self):
        self.app.activeDocument = _document("Other", 100.0)
        answer = design_history.saved_state("PN-1", [])
        self.assertIsNone(answer["saved"])
        self.assertIn("PN-1", answer["reason"])

    def test_a_failure_to_read_is_an_answer_not_an_error(self):
        self.app.activeDocument = types.SimpleNamespace(name="Frame")   # no data file: reading it raises
        self.app.activeProduct = object()
        answer = design_history.saved_state("PN-1", [])
        self.assertIsNone(answer["saved"])
        self.assertTrue(answer["reason"])


if __name__ == "__main__":
    unittest.main()
