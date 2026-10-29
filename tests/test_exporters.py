"""Exporting a STEP file: the ways tried, and the document opened only when the others fail. Fusion's modules are stood in for."""

import sys
import types
import unittest
from unittest import mock

from src.publish import exporters


class Manager:
    """An export manager that fails for the geometries in ``refuses`` (by name) and notes each export."""

    def __init__(self, refuses=(), name="manager"):
        self.refuses, self.name, self.exported = set(refuses), name, []
        self._geometry = None

    def createSTEPExportOptions(self, path, geometry=None):
        self._geometry = getattr(geometry, "name", None)
        return (path, self._geometry)

    def execute(self, options):
        self.exported.append(options)
        return self._geometry not in self.refuses


class Geometry:
    def __init__(self, name):
        self.name = name


class Occurrence:
    def __init__(self, data_file="missing", component="component"):
        self.name = "occurrence"
        self.component = Geometry(component)
        self._data_file = data_file

    @property
    def documentReference(self):
        if self._data_file == "missing":
            raise RuntimeError("nested")
        return types.SimpleNamespace(dataFile=self._data_file)


class Document:
    def __init__(self, data_file, manager, has_design=True):
        self.dataFile, self.closed = data_file, []
        self.design = types.SimpleNamespace(exportManager=manager) if has_design else None
        self.products = types.SimpleNamespace(itemByProductType=lambda kind: self.design)

    def close(self, save):
        self.closed.append(save)


class Documents(list):
    def __init__(self, found=(), opens=None):
        super().__init__(found)
        self.opens, self.opened = opens, []

    def open(self, data_file, visible):
        self.opened.append((data_file, visible))
        return self.opens


def fusion(design_manager, documents):
    """Fake ``adsk`` modules whose active product is a design with ``design_manager``, and whose app holds ``documents``."""
    design = types.SimpleNamespace(exportManager=design_manager)
    app = types.SimpleNamespace(activeProduct=design, documents=documents)
    core = types.SimpleNamespace(Application=types.SimpleNamespace(get=lambda: app))
    fusion_module = types.SimpleNamespace(Design=types.SimpleNamespace(cast=lambda product: product))
    adsk = types.ModuleType("adsk")
    adsk.core, adsk.fusion, adsk.doEvents = core, fusion_module, lambda: None
    return mock.patch.dict(sys.modules, {"adsk": adsk, "adsk.core": core, "adsk.fusion": fusion_module})


class ExportStepTests(unittest.TestCase):
    def test_the_open_design_is_exported_whole(self):
        manager = Manager()
        with fusion(manager, Documents()):
            exporters.export_step("a.step")
        self.assertEqual(manager.exported, [("a.step", None)])

    def test_a_component_is_exported_as_its_occurrence_first(self):
        manager = Manager()
        with fusion(manager, Documents()):
            exporters.export_step("a.step", Occurrence())
        self.assertEqual(manager.exported, [("a.step", "occurrence")])

    def test_a_component_falls_back_to_its_component_and_nothing_is_opened(self):
        manager, documents = Manager(refuses={"occurrence"}), Documents()
        with fusion(manager, documents):
            exporters.export_step("a.step", Occurrence())
        self.assertEqual(manager.exported, [("a.step", "occurrence"), ("a.step", "component")])
        self.assertEqual(documents.opened, [])

    def test_a_document_already_open_is_used_and_left_open(self):
        data_file = types.SimpleNamespace(id="F1")
        own = Manager(name="own")
        document = Document(data_file, own)
        with fusion(Manager(refuses={"occurrence", "component"}), Documents([document])):
            exporters.export_step("a.step", Occurrence(data_file))
        self.assertEqual(own.exported, [("a.step", None)])
        self.assertEqual(document.closed, [])

    def test_a_document_opened_for_the_export_is_closed_unsaved_after_it(self):
        data_file = types.SimpleNamespace(id="F1")
        own = Manager(name="own")
        document = Document(data_file, own)
        documents = Documents(opens=document)
        with fusion(Manager(refuses={"occurrence", "component"}), documents):
            exporters.export_step("a.step", Occurrence(data_file))
        self.assertEqual(documents.opened, [(data_file, False)])
        self.assertEqual((own.exported, document.closed), ([("a.step", None)], [False]))

    def test_a_document_opened_for_the_export_is_closed_when_the_export_fails(self):
        data_file = types.SimpleNamespace(id="F1")
        document = Document(data_file, Manager(refuses={None}))
        with fusion(Manager(refuses={"occurrence", "component"}), Documents(opens=document)):
            with self.assertRaises(RuntimeError):
                exporters.export_step("a.step", Occurrence(data_file))
        self.assertEqual(document.closed, [False])

    def test_a_document_that_will_not_close_does_not_hide_the_export(self):
        data_file = types.SimpleNamespace(id="F1")
        own = Manager()
        document = Document(data_file, own)
        document.close = mock.Mock(side_effect=RuntimeError("busy"))
        with fusion(Manager(refuses={"occurrence", "component"}), Documents(opens=document)):
            exporters.export_step("a.step", Occurrence(data_file))
        self.assertEqual(own.exported, [("a.step", None)])

    def test_every_way_failing_says_why_each_did(self):
        with fusion(Manager(refuses={"occurrence", "component"}), Documents()):
            with self.assertRaises(RuntimeError) as caught:
                exporters.export_step("a.step", Occurrence())   # a nested component has no document of its own
        message = str(caught.exception)
        self.assertIn("occurrence: Fusion could not export the STEP file.", message)
        self.assertIn("component: Fusion could not export the STEP file.", message)
        self.assertIn("own document: The component's own document could not be found", message)

    def test_a_document_with_no_design_is_said(self):
        data_file = types.SimpleNamespace(id="F1")
        with fusion(Manager(refuses={"occurrence", "component"}), Documents(opens=Document(data_file, None, has_design=False))):
            with self.assertRaises(RuntimeError) as caught:
                exporters.export_step("a.step", Occurrence(data_file))
        self.assertIn("has no design", str(caught.exception))

    def test_an_open_document_that_is_not_a_design_is_refused(self):
        manager = Manager()
        with fusion(manager, Documents()):
            sys.modules["adsk.fusion"].Design.cast = lambda product: None
            with self.assertRaises(RuntimeError):
                exporters.export_step("a.step")


if __name__ == "__main__":
    unittest.main()
