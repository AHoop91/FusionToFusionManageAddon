"""Finding the one Components record an item number stands for, in the picklist of the component linking field."""

import unittest

from src.fm.components import NO_NUMBER, SHOWN, ComponentService, manage_link, parse_workspace_id


class Client:
    base_url = "https://acme.autodeskplm360.net"

    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def get_json(self, path, accept="application/json"):
        self.asked.append(path)
        return self.answer


def option(link, title, version=""):
    return {"link": link, "title": title, "version": version}


def find(number, *options, lookup="LOOKUP"):
    return ComponentService(Client({"items": list(options)})).find(lookup, number)


class FindTests(unittest.TestCase):
    def test_the_one_option_for_the_number_is_its_link(self):
        link, reason = find("PN-1", option("/api/v3/workspaces/57/items/9", "PN-1 - Axle"), option("/x/10", "PN-10 - Other"))
        self.assertEqual((link, reason), ("/api/v3/workspaces/57/items/9", ""))

    def test_no_number_is_not_looked_up(self):
        client = Client({})
        self.assertEqual(ComponentService(client).find("LOOKUP", ""), ("", NO_NUMBER))
        self.assertEqual(client.asked, [])

    def test_no_match_says_how_many_options_came_back(self):
        link, reason = find("PN-1", option("/x/1", "PN-2 - Gear"))
        self.assertEqual(link, "")
        self.assertIn("No component matching PN-1", reason)
        self.assertIn("1 option(s)", reason)

    def test_several_matches_are_named_but_only_the_first_few(self):
        options = [option(f"/x/{i}", f"PN-1 - Axle {i}", "[REV:w]") for i in range(SHOWN + 3)]
        link, reason = find("PN-1", *options)
        self.assertEqual(link, "")
        self.assertIn(f"{SHOWN + 3} components match PN-1", reason)
        self.assertIn(f"Axle {SHOWN - 1} [REV:w] ({SHOWN - 1})", reason)
        self.assertNotIn(f"Axle {SHOWN} ", reason)

    def test_an_option_with_no_link_or_a_wrong_shape_is_left_out(self):
        link, _ = find("PN-1", {"title": "PN-1 - No link"}, "x", option("/x/2", "PN-1 - Axle"))
        self.assertEqual(link, "/x/2")


class WorkspaceIdTests(unittest.TestCase):
    def test_the_workspace_is_found_by_title_ignoring_case_and_space(self):
        data = {"items": [{"title": "Items and BOMs", "link": "/api/v3/workspaces/8"}, {"title": " components ", "link": "/api/v3/workspaces/57/"}]}
        self.assertEqual(parse_workspace_id(data), "57")

    def test_the_name_and_self_link_are_read_when_there_is_no_title_or_link(self):
        self.assertEqual(parse_workspace_id({"items": [{"name": "Components", "__self__": "/api/v3/workspaces/57"}]}), "57")

    def test_none_found_or_a_wrong_shape_is_empty(self):
        for data in (None, {}, {"items": "x"}, {"items": [{"title": "Other", "link": "/x/1"}, "x"]}):
            with self.subTest(data=data):
                self.assertEqual(parse_workspace_id(data), "")


class ManageLinkTests(unittest.TestCase):
    def test_the_urn_names_the_item(self):
        self.assertEqual(manage_link("urn:adsk.plm:tenant.workspace.item:ACME.57.9", ""), "/api/v3/workspaces/57/items/9")

    def test_the_url_is_used_when_the_urn_says_nothing(self):
        self.assertEqual(manage_link("", "https://acme/api/v3/workspaces/57/items/9"), "/api/v3/workspaces/57/items/9")
        self.assertEqual(manage_link("", ""), "")


if __name__ == "__main__":
    unittest.main()
