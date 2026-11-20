"""Finding the one Components record an item number stands for, in the picklist of the component linking field."""

import unittest

from src.fm.client import FmApiError
from src.fm.components import ComponentService, manage_link, parse_workspace_id


class Client:
    base_url = "https://acme.autodeskplm360.net"

    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def get_json(self, path, accept="application/json"):
        self.asked.append(path)
        return self.answer


def option(link, title, version=""):
    return {"link": link, "title": title, "version": version}


def matching(number, *options, lookup="LOOKUP"):
    return ComponentService(Client({"items": list(options)})).matching(lookup, number)


class MatchingTests(unittest.TestCase):
    def test_the_options_for_the_number_are_listed_and_a_longer_number_is_not(self):
        hits = matching("PN-1", option("/api/v3/workspaces/57/items/9", "PN-1 - Axle"), option("/x/10", "PN-10 - Other"))
        self.assertEqual([h.link for h in hits], ["/api/v3/workspaces/57/items/9"])

    def test_no_number_is_not_looked_up(self):
        client = Client({})
        with self.assertRaisesRegex(FmApiError, "The item has no number to look up."):
            ComponentService(client).matching("LOOKUP", "")
        self.assertEqual(client.asked, [])

    def test_no_match_says_how_many_options_came_back(self):
        with self.assertRaises(FmApiError) as raised:
            matching("PN-1", option("/x/1", "PN-2 - Gear"))
        self.assertIn("No component matching PN-1", str(raised.exception))
        self.assertIn("1 option(s)", str(raised.exception))

    def test_an_option_with_no_link_or_a_wrong_shape_is_left_out(self):
        hits = matching("PN-1", {"title": "PN-1 - No link"}, "x", option("/x/2", "PN-1 - Axle"))
        self.assertEqual([h.link for h in hits], ["/x/2"])


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
