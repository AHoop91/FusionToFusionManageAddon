"""The Publish panel's scripts, tested with Node (``tests/js``) and, for the ones that need a page, in a real headless browser (``tests/js/dom``)."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
NO_BROWSER = 77   # the exit code of tests/js/browser/run.mjs when it finds no Edge or Chrome


@unittest.skipUnless(NODE, "Node is not installed")
class PanelScriptTests(unittest.TestCase):
    def test_node_tests_pass(self):
        tests = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.js"))
        result = subprocess.run([NODE, "--test", *tests], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_page_tests_pass_in_a_browser(self):
        result = subprocess.run([NODE, str(ROOT / "tests" / "js" / "browser" / "run.mjs")], cwd=ROOT, capture_output=True, text=True, timeout=600)
        if result.returncode == NO_BROWSER:
            self.skipTest("No Edge or Chrome is installed")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
