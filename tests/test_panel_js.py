"""The Publish panel's scripts, tested with Node (``tests/js``): the Bill of Materials data and, where jsdom is installed, the whole panel."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node is not installed")
class PanelScriptTests(unittest.TestCase):
    def test_node_tests_pass(self):
        tests = sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.js"))
        result = subprocess.run([NODE, "--test", *tests], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
