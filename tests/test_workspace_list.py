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


if __name__ == "__main__":
    unittest.main()
