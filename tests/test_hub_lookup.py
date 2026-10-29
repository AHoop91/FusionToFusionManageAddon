"""Finding a hub by name: the name matches ignoring case, the only hub is taken when none matches, and anything else is an error."""

import unittest

from src.fusion_mfg.fusion_graphql_client import MfgApiError
from src.fusion_mfg.hub_lookup import HUBS_QUERY, find_hub_id, read_hub_id


def hubs(*rows):
    return {"hubs": {"results": [{"id": hub_id, "name": name} for hub_id, name in rows]}}


class FakeClient:
    def __init__(self, data):
        self.data, self.asked = data, []

    def query(self, text, variables=None, label=""):
        self.asked.append(text)
        return self.data


class FindTests(unittest.TestCase):
    def test_the_name_matches_ignoring_case_and_space(self):
        self.assertEqual(find_hub_id(hubs(("1", "Acme"), ("2", "Other")), "  other "), "2")

    def test_the_only_hub_is_taken_when_no_name_matches(self):
        self.assertEqual(find_hub_id(hubs(("1", "Acme")), "Elsewhere"), "1")
        self.assertEqual(find_hub_id(hubs(("1", "Acme")), ""), "1")

    def test_a_name_that_matches_none_of_several_is_an_error(self):
        with self.assertRaises(MfgApiError):
            find_hub_id(hubs(("1", "Acme"), ("2", "Other")), "Elsewhere")

    def test_no_hubs_is_an_error(self):
        for data in (hubs(), {}, None, {"hubs": "x"}):
            with self.subTest(data=data):
                with self.assertRaises(MfgApiError):
                    find_hub_id(data, "Acme")

    def test_a_hub_with_no_name_does_not_match_the_text_none(self):
        data = {"hubs": {"results": [{"id": "1", "name": None}, {"id": "2", "name": "Acme"}]}}
        with self.assertRaises(MfgApiError):
            find_hub_id(data, "None")


class ReadTests(unittest.TestCase):
    def test_the_hubs_are_asked_for_once(self):
        client = FakeClient(hubs(("1", "Acme")))
        self.assertEqual(read_hub_id(client, "Acme"), "1")
        self.assertEqual(client.asked, [HUBS_QUERY])


if __name__ == "__main__":
    unittest.main()
