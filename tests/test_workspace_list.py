import unittest

from src.fm.workspace import WorkspaceService


def _row(workspace_id, name, type_id, deleted=False, controlled=False):
    return {"__self__": f"/api/v3/workspaces/{workspace_id}", "name": name,
            "type": f"/api/v3/workspace-types/{type_id}", "deleted": deleted, "controlled": controlled}


class _Client:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.paths = []

    def get_json(self, path, accept="application/json"):
        self.paths.append(path)
        return self.pages.pop(0)


class RevisionControlledTests(unittest.TestCase):
    def test_only_revision_controlled_workspaces_are_listed_by_name(self):
        client = _Client({"totalCount": 5, "items": [
            _row(9, "Change Orders", 7), _row(242, "Items", 6), _row(76, "Old", 6, deleted=True),
            _row(57, "Components", 6, controlled=True), _row(300, "Parts", 6)]})
        found = WorkspaceService(client).revision_controlled()
        self.assertEqual(found, [{"id": "242", "name": "Items"}, {"id": "300", "name": "Parts"}])

    def test_every_page_is_read(self):
        client = _Client({"totalCount": 2, "items": [_row(1, "B", 6)]},
                         {"totalCount": 2, "items": [_row(2, "A", 6)]})
        found = WorkspaceService(client).revision_controlled()
        self.assertEqual([w["id"] for w in found], ["2", "1"])
        self.assertIn("offset=1", client.paths[1])

    def test_an_unexpected_answer_lists_nothing(self):
        self.assertEqual(WorkspaceService(_Client("nope")).revision_controlled(), [])


class AllWorkspacesTests(unittest.TestCase):
    def test_every_live_workspace_is_listed_and_says_whether_it_is_revision_controlled(self):
        client = _Client({"totalCount": 4, "items": [
            _row(9, "Portfolio", 1), _row(242, "Items", 6), _row(76, "Old", 1, deleted=True), _row(57, "Components", 6, controlled=True)]})
        found = WorkspaceService(client).all_workspaces()
        self.assertEqual(found, [{"id": "242", "name": "Items", "revision": True}, {"id": "9", "name": "Portfolio", "revision": False}])


class PicklistOrderTests(unittest.TestCase):
    def test_the_options_of_a_picklist_are_asked_for_by_title(self):
        client = _Client({"totalCount": 1, "items": [{"link": "/api/v3/lookups/L/options/2", "title": "1 Best"}]},
                         {"totalCount": 1, "items": [{"link": "/api/v3/lookups/L/options/2", "title": "1 Best"}]})
        service = WorkspaceService(client)
        service.options("L")
        service.options_page("L", 0, 50, "bes")
        self.assertTrue(all("asc=title" in path for path in client.paths), client.paths)


if __name__ == "__main__":
    unittest.main()
