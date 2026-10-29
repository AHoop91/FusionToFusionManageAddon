"""Validating a workspace and reading its fields and picklists for the mapping picker."""

import unittest

from src.auth.errors import AuthError
from src.config.workspace_models import WorkspaceKind
from src.fm.client import FmApiError
from src.fm.workspace import MAX_OPTIONS, OPTIONS_PAGE, WorkspaceService

KIND = WorkspaceKind("items", "Items", "", required_permissions=("view_items", "add_items"))
FIELD = "/api/v3/workspaces/242/views/1/fields/"


def permissions(*names):
    return {"permissions": [{"name": "permission.shortname." + n} for n in names]}


def field(fid, **extra):
    return {"__self__": FIELD + fid, "name": fid.title(), **extra}


class Client:
    """Answers each path (its query left off) with what ``answers`` holds for it; an exception held is raised."""

    def __init__(self, answers):
        self.answers, self.paths = answers, []

    def get_json(self, path, accept="application/json"):
        self.paths.append(path)
        answer = self.answers[path.split("?")[0]]
        if isinstance(answer, Exception):
            raise answer
        return answer


def validate(answers, workspace_id="242"):
    return WorkspaceService(Client(answers)).validate(KIND, workspace_id)


class ValidateTests(unittest.TestCase):
    BASE = "/api/v3/workspaces/242"

    def answers(self, workspace=None, granted=None, fields=None):
        return {self.BASE: {"name": "Items"} if workspace is None else workspace,
                self.BASE + "/users/@me/permissions": permissions("view_items", "add_items") if granted is None else granted,
                self.BASE + "/fields": {"fields": []} if fields is None else fields}

    def test_a_workspace_the_user_may_use_is_valid_and_carries_its_fields(self):
        result = validate(self.answers(fields={"fields": [field("TITLE")]}))
        self.assertEqual((result["valid"], result["message"]), (True, "Workspace 'Items' is valid."))
        self.assertEqual([f["id"] for f in result["fields"]], ["TITLE"])

    def test_an_id_that_is_not_a_number_is_refused_before_anything_is_asked(self):
        client = Client({})
        result = WorkspaceService(client).validate(KIND, "242/../x")
        self.assertEqual((result["valid"], client.paths), (False, []))

    def test_a_deleted_or_missing_workspace_is_not_valid(self):
        for workspace in ({"name": "Gone", "deleted": True}, None):
            with self.subTest(workspace=workspace):
                answers = self.answers(workspace=workspace)
                answers[self.BASE] = workspace
                self.assertIn("was not found or has been deleted", validate(answers)["message"])

    def test_missing_permissions_are_named(self):
        result = validate(self.answers(granted=permissions("view_items")))
        self.assertFalse(result["valid"])
        self.assertEqual(result["message"], "You need these permissions on 'Items': Add Items.")

    def test_a_workspace_with_no_name_is_called_by_its_id(self):
        self.assertEqual(validate(self.answers(workspace={"name": None}))["message"], "Workspace '242' is valid.")

    def test_a_refusal_or_a_missing_workspace_is_explained_and_other_failures_are_shown(self):
        for status, expected in ((404, "Workspace 242 was not found."), (403, "You do not have access to workspace 242."), (401, "You do not have access to workspace 242.")):
            with self.subTest(status=status):
                self.assertEqual(validate({self.BASE: FmApiError("x", status)})["message"], expected)
        self.assertEqual(validate({self.BASE: FmApiError("down", 503)})["message"], "down")

    def test_not_being_signed_in_is_said(self):
        self.assertIn("Not signed in", validate({self.BASE: AuthError("expired")})["message"])


class FieldsTests(unittest.TestCase):
    BASE = "/api/v3/workspaces/242"

    def fields(self, *rows):
        return WorkspaceService(Client({self.BASE + "/fields": {"fields": list(rows)}})).fields(self.BASE)

    def test_a_field_is_described_for_the_picker_and_the_list_is_sorted_by_title(self):
        found, error = self.fields(field("ZED"), field("TYPE", type={"title": "Single Selection"}, picklist="/api/v3/lookups/KINDS"), {"name": "no id"})
        self.assertEqual(error, "")
        self.assertEqual([f["id"] for f in found], ["TYPE", "ZED"])
        self.assertEqual(found[0], {"id": "TYPE", "title": "Type", "type": "Single Selection", "picklist": "KINDS", "link_lookup": "", "shown": True, "computed": False})

    def test_a_field_that_links_to_another_workspace_or_cannot_be_edited_is_text(self):
        found, _ = self.fields(field("LINK", picklist="/api/v3/lookups/WS", picklistFieldDefinition="x"), field("LOCKED", picklist="/api/v3/lookups/L", editability="NEVER"))
        self.assertEqual({f["id"]: (f["picklist"], f["link_lookup"]) for f in found}, {"LINK": ("", "WS"), "LOCKED": ("", "")})

    def test_hidden_and_computed_fields_are_marked(self):
        found, _ = self.fields(field("HID", visibility="NEVER"), field("FORMULA", formulaField=True), field("PLAIN"))
        self.assertEqual({f["id"]: (f["shown"], f["computed"]) for f in found}, {"HID": (False, False), "FORMULA": (True, True), "PLAIN": (True, False)})

    def test_fields_that_cannot_be_read_give_the_reason_not_an_exception(self):
        found, error = WorkspaceService(Client({self.BASE + "/fields": FmApiError("down", 503)})).fields(self.BASE)
        self.assertEqual(found, [])
        self.assertIn("Could not load the workspace's fields", error)

    def test_a_search_can_be_filtered_by_the_fields_shown_and_not_computed(self):
        service = WorkspaceService(Client({self.BASE + "/fields": {"fields": [field("A"), field("B", visibility="NEVER"), field("C", formulaField=True)]}}))
        self.assertEqual([f["id"] for f in service.filterable_fields(self.BASE)], ["A"])

    def test_filterable_fields_raise_when_the_fields_cannot_be_read(self):
        with self.assertRaises(FmApiError):
            WorkspaceService(Client({self.BASE + "/fields": FmApiError("down", 503)})).filterable_fields(self.BASE)


class OptionsTests(unittest.TestCase):
    def test_a_picklist_whose_options_cannot_be_loaded_leaves_its_field_as_text(self):
        base = "/api/v3/workspaces/242"
        answers = {base: {"name": "Items"}, base + "/users/@me/permissions": permissions("view_items", "add_items"),
                   base + "/fields": {"fields": [field("OK", picklist="/api/v3/lookups/GOOD"), field("BAD", picklist="/api/v3/lookups/BAD")]},
                   "/api/v3/lookups/GOOD": {"totalCount": 1, "items": [{"link": "/api/v3/lookups/GOOD/options/1", "title": "One"}]},
                   "/api/v3/lookups/BAD": FmApiError("down", 503)}
        result = validate(answers)
        self.assertEqual(result["picklists"], {"GOOD": [{"value": "/api/v3/lookups/GOOD/options/1", "title": "One"}]})
        self.assertEqual({f["id"]: f["picklist"] for f in result["fields"]}, {"OK": "GOOD", "BAD": ""})

    def test_every_page_of_a_picklist_is_read(self):
        class Paged:
            def __init__(self):
                self.paths = []

            def get_json(self, path, accept="application/json"):
                self.paths.append(path)
                start = int(path.split("offset=")[1].split("&")[0])
                return {"totalCount": 150, "items": [{"link": f"/o/{start + i}", "title": f"T{start + i}"} for i in range(min(OPTIONS_PAGE, 150 - start))]}

        client = Paged()
        options = WorkspaceService(client).options("L")
        self.assertEqual((len(options), options[0], options[-1]["title"]), (150, {"value": "/o/0", "title": "T0"}, "T149"))
        self.assertEqual(len(client.paths), 2)

    def test_an_option_with_no_link_is_left_out_and_one_with_no_title_is_called_by_its_link(self):
        client = Client({"/api/v3/lookups/L": {"totalCount": 2, "items": [{"title": "no link"}, {"link": "/o/2"}]}})
        self.assertEqual(WorkspaceService(client).options("L"), [{"value": "/o/2", "title": "/o/2"}])

    def test_a_list_that_never_ends_stops_at_the_most_options_it_will_read(self):
        class Endless:
            calls = 0

            def get_json(self, path, accept="application/json"):
                Endless.calls += 1
                return {"totalCount": 10 ** 9, "items": [{"link": f"/o/{Endless.calls}-{i}"} for i in range(OPTIONS_PAGE)]}

        self.assertEqual(len(WorkspaceService(Endless()).options("L")), MAX_OPTIONS)

    def test_a_total_that_is_not_a_number_ends_the_paging(self):
        client = Client({"/api/v3/lookups/L": {"totalCount": "lots", "items": [{"link": "/o/1", "title": "One"}]}})
        self.assertEqual(len(WorkspaceService(client).options("L")), 1)
        self.assertEqual(len(client.paths), 1)

    def test_a_picklist_that_cannot_be_read_has_no_options(self):
        self.assertEqual(WorkspaceService(Client({"/api/v3/lookups/L": FmApiError("down", 503)})).options("L"), [])
        self.assertEqual(WorkspaceService(Client({"/api/v3/lookups/L": AuthError("expired")})).options("L"), [])

    def test_a_page_asked_for_with_odd_numbers_starts_at_zero(self):
        client = Client({"/api/v3/lookups/L": {"totalCount": 0, "items": []}})
        WorkspaceService(client).options_page("L", "x", 10)
        self.assertIn("offset=0&limit=10", client.paths[0])


if __name__ == "__main__":
    unittest.main()
