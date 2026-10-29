import unittest

from src.fm.client import FmApiError
from src.fm import components
from src.fm.components import ComponentService, is_working
from src.fm.permissions import ATTACH_PERMISSIONS, denial


class _Client:
    """Answers each request with the next of ``answers`` (an exception is raised)."""

    def __init__(self, *answers, base_url="https://tenant"):
        self.answers = list(answers)
        self.paths = []
        self.base_url = base_url

    def get_json(self, path, accept="application/json"):
        self.paths.append(path)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _permissions(*names):
    return {"permissions": [{"name": "permission.shortname." + n} for n in names]}


class WorkspaceOfComponentsTests(unittest.TestCase):
    def setUp(self):
        components._WORKSPACES.clear()   # it is kept between calls, so each test starts without it

    def test_the_workspace_is_the_one_called_components(self):
        client = _Client({"items": [{"link": "/api/v3/workspaces/8", "title": "Items and BOMs"}, {"link": "/api/v3/workspaces/84", "title": " components "}]},
                         base_url="https://tenant-a")
        self.assertEqual(ComponentService(client).workspace_id(), "84")
        self.assertIn("/api/v3/workspaces?", client.paths[0])

    def test_it_is_asked_for_once_a_while_not_at_every_call(self):
        client = _Client({"items": [{"link": "/api/v3/workspaces/84", "title": "Components"}]}, base_url="https://tenant-b")
        self.assertEqual(ComponentService(client).workspace_id(), "84")
        self.assertEqual(ComponentService(client).workspace_id(), "84")
        self.assertEqual(len(client.paths), 1)

    def test_no_such_workspace_says_nothing(self):
        self.assertEqual(ComponentService(_Client({"items": []}, base_url="https://tenant-c")).workspace_id(), "")
        self.assertEqual(ComponentService(_Client(None, base_url="https://tenant-d")).workspace_id(), "")


WORKSPACES = {"items": [{"link": "/api/v3/workspaces/8", "title": "Items and BOMs"}, {"link": "/api/v3/workspaces/57", "title": "Components"}]}


def _search(*results):
    """The answer of the V3 search: each result is ``(item id, descriptor, version)``."""
    return {"totalCount": len(results), "items": [{"__self__": f"/api/v3/workspaces/57/items/{item}", "descriptor": descriptor, "version": version}
                                                   for item, descriptor, version in results]}


class WorkingVersionTests(unittest.TestCase):
    def setUp(self):
        components._WORKSPACES.clear()

    def find(self, *results):
        client = _Client(WORKSPACES, _search(*results))
        return ComponentService(client).find_working("PN-000701"), client

    def test_the_working_version_is_the_search_result(self):
        (link, reason), client = self.find((15745, "PN-000701 - Universal Joint", "[REV:w]"))
        self.assertEqual((link, reason), ("/api/v3/workspaces/57/items/15745", ""))
        asked = client.paths[1]   # the search, after the list of workspaces that says which is the Components
        self.assertTrue(asked.startswith("/api/v3/search-results?isFullQuery=true"))
        self.assertIn("query=PN-000701%20AND%20%28workspaceId%3D57%29", asked)
        self.assertIn("revision=3", asked)

    def test_a_result_for_a_longer_number_is_not_it(self):
        (link, _reason), _ = self.find((1, "PN-0007011 - Other", "[REV:w]"), (2, "PN-000701 - Universal Joint", "[REV:w]"))
        self.assertEqual(link, "/api/v3/workspaces/57/items/2")

    def test_no_working_version_is_said_so(self):
        (link, reason), _ = self.find()
        self.assertEqual(link, "")
        self.assertIn("No working version of the component PN-000701", reason)

    def test_two_working_versions_are_refused_naming_them(self):
        (link, reason), _ = self.find((1, "PN-000701 - A", "[REV:w]"), (2, "PN-000701 - B", "[REV:w]"))
        self.assertEqual(link, "")
        self.assertIn("2 working versions match", reason)

    def test_no_workspace_called_components_is_said_so(self):
        link, reason = ComponentService(_Client({"items": [{"link": "/api/v3/workspaces/8", "title": "Items and BOMs"}]}, base_url="https://nobody")).find_working("PN-000701")
        self.assertEqual(link, "")
        self.assertIn("No workspace called Components", reason)

    def test_the_version_names_the_working_one(self):
        self.assertTrue(is_working("[REV:w]"))
        self.assertTrue(is_working("[REV: W ]"))
        self.assertFalse(is_working("[REV:C]"))
        self.assertFalse(is_working(""))


class AttachDenialTests(unittest.TestCase):
    def test_a_user_who_may_attach_is_not_denied(self):
        self.assertEqual(denial(_Client(_permissions(*ATTACH_PERMISSIONS)), "84", ATTACH_PERMISSIONS, "Components", "attach files to"), "")

    def test_the_missing_permissions_are_named(self):
        message = denial(_Client(_permissions("view_items")), "84", ATTACH_PERMISSIONS, "Components", "attach files to")
        self.assertIn("attach files to the Components workspace", message)
        self.assertIn("Add Attachments", message)
        self.assertIn("Edit Attachments", message)
        self.assertNotIn("View Items", message)

    def test_a_refusal_to_read_them_is_a_denial(self):
        message = denial(_Client(FmApiError("no", 403)), "84", ATTACH_PERMISSIONS, "Items", "attach files to")
        self.assertIn("Insufficient permissions to attach files to the Items workspace", message)

    def test_a_failure_that_is_not_a_refusal_is_raised_not_called_a_denial(self):
        with self.assertRaises(FmApiError):
            denial(_Client(FmApiError("down", 503)), "84", ATTACH_PERMISSIONS, "Items", "attach files to")

    def test_a_401_is_a_denial_too(self):
        self.assertIn("Insufficient permissions", denial(_Client(FmApiError("no", 401)), "84", ATTACH_PERMISSIONS, "Items"))


if __name__ == "__main__":
    unittest.main()
