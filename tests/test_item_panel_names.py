"""An attribute a panel sets must not share a name with one of its methods: it would hide the method (``self._load`` became a token
slot, and the thread that was to run the method called the slot instead). Checked for the Item panel and the classes split from it."""

import ast
import os
import unittest

UI = os.path.join(os.path.dirname(__file__), "..", "src", "ui")


def hidden_methods(module: str, class_name: str):
    """The names that are both a method of ``class_name`` and an attribute its methods set on ``self``."""
    with open(os.path.join(UI, module), encoding="utf-8") as source:
        tree = ast.parse(source.read())
    panel = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    methods = {n.name for n in panel.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    attributes = {t.attr for node in ast.walk(panel) if isinstance(node, (ast.Assign, ast.AnnAssign))
                  for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                  if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self"}
    return methods & attributes


class PanelNamesTest(unittest.TestCase):
    def test_no_attribute_hides_a_method(self):
        self.assertEqual(hidden_methods("item_panel.py", "ItemPanel"), set())

    def test_no_attribute_of_the_export_panel_hides_a_method(self):
        self.assertEqual(hidden_methods("export_panel.py", "ExportPanel"), set())

    def test_no_attribute_of_the_number_finder_hides_a_method(self):
        self.assertEqual(hidden_methods("number_finder.py", "NumberFinder"), set())


if __name__ == "__main__":
    unittest.main()
