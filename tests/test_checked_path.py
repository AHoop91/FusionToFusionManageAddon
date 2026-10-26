"""A path built from ids the page sent stays inside the Fusion Manage API."""

import unittest

from src.fm.client import FmApiError, checked_path


class CheckedPathTests(unittest.TestCase):
    def test_ordinary_paths_pass(self):
        for path in ("/api/v3/workspaces/242/items/15727", "/api/v3/users/@me", "/api/v3/workspaces/1/items/2/bom?depth=1&query=a%20b",
                     "/api/v3/workspaces/1/items/{{item:X}}/bom-items"):
            self.assertEqual(checked_path(path), path)

    def test_a_path_that_climbs_out_or_breaks_the_request_is_refused(self):
        for path in ("/api/v3/workspaces/../../x", "/api/v3/workspaces/1/items/%2e%2e/x", "/api/v3/workspaces/1%2fx",
                     "/api/v3/workspaces/1\\x", "/api/v3/workspaces/1 x", "/api/v3/workspaces/1\r\nX: y", "/api/v3/x#frag", "api/v3/x"):
            with self.assertRaises(FmApiError, msg=path):
                checked_path(path)


if __name__ == "__main__":
    unittest.main()
