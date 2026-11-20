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


class WorkingVersionTests(unittest.TestCase):
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
