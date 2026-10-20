"""An attribute the item panel sets must not share a name with one of its methods: it would hide the method (``self._load`` became a token
slot, and the thread that was to run the method called the slot instead)."""

import ast
import os
import unittest

PATH = os.path.join(os.path.dirname(__file__), "..", "src", "ui", "item_panel.py")


class ItemPanelNamesTest(unittest.TestCase):
    def test_no_attribute_hides_a_method(self):
        with open(PATH, encoding="utf-8") as source:
            tree = ast.parse(source.read())
        panel = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ItemPanel")
        methods = {n.name for n in panel.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        attributes = {t.attr for node in ast.walk(panel) if isinstance(node, (ast.Assign, ast.AnnAssign))
                      for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                      if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self"}
        self.assertEqual(methods & attributes, set())


if __name__ == "__main__":
    unittest.main()
