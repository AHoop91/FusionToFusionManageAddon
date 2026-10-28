"""The requests a publish makes to the Data Model: several components to a request."""

import unittest

from src.fusion_mfg.fusion_graphql_client import MfgApiError
from src.fusion_mfg.model_service import read_publish_components

SUMMARY = {"composition": "DESIGN"}


def component(name="Steel", url="https://example.test/t.png"):
    return {"allProperties": {"results": [{"name": "Material", "displayValue": name}]},
            "thumbnail": {"status": "COMPLETED", "signedUrl": url} if url else None,
            "lifecycle": {"itemUrn": "urn:item", "itemUrl": "https://example.test/item"}}


class FakeClient:
    """Answers each alias from ``components`` by component id; ``refuse`` ids make a request that holds one fail."""

    def __init__(self, components, refuse=(), error=None):
        self.components, self.refuse, self.error = components, set(refuse), error
        self.asked = []

    def query(self, text, variables=None, label=""):
        ids = [variables[f"id{n}"] for n in range(len([k for k in variables if k.startswith("id")]))]
        self.asked.append((text, variables, ids))
        if self.error:
            raise self.error
        if self.refuse & set(ids):
            raise MfgApiError("Field error", transient=False)
        return {f"c{n}": self.components.get(cid) for n, cid in enumerate(ids)}


class PublishReadTests(unittest.TestCase):
    def test_one_request_gives_every_component_its_properties_thumbnail_and_link(self):
        client = FakeClient({"a": component("Steel"), "b": component("Brass", "")})
        read = read_publish_components(client, SUMMARY, ["a", "b"], "t1")
        self.assertEqual(len(client.asked), 1)
        self.assertEqual(client.asked[0][1], {"composition": "DESIGN", "time": "t1", "id0": "a", "id1": "b"})
        self.assertEqual(read["a"]["properties"], [{"name": "Material", "value": "Steel"}])
        self.assertEqual(read["a"]["thumbnail_url"], "https://example.test/t.png")
        self.assertEqual(read["a"]["link"], {"urn": "urn:item", "url": "https://example.test/item"})
        self.assertEqual(read["b"]["thumbnail_url"], "")

    def test_a_component_with_no_thumbnail_and_no_link_gives_empty_values(self):
        client = FakeClient({"a": {"allProperties": {"results": []}, "thumbnail": None, "lifecycle": None}})
        read = read_publish_components(client, SUMMARY, ["a"])
        self.assertEqual(read["a"]["thumbnail_url"], "")
        self.assertEqual(read["a"]["link"], {"urn": "", "url": ""})
        self.assertNotIn("time", client.asked[0][1])

    def test_the_physical_properties_ride_in_the_same_request(self):
        client = FakeClient({"a": {"allProperties": {"results": []}, "primaryModel": {"physicalProperties": {"status": "PENDING"}}}})
        read_publish_components(client, SUMMARY, ["a"], physical=True)
        self.assertEqual(len(client.asked), 1)
        text = client.asked[0][0]
        for wanted in ("physicalProperties", "signedUrl", "itemUrn"):
            self.assertIn(wanted, text)

    def test_a_refused_request_is_read_in_halves_so_only_the_bad_component_fails(self):
        client = FakeClient({cid: component(cid) for cid in "abcd"}, refuse="c")
        read = read_publish_components(client, SUMMARY, list("abcd"))
        self.assertEqual([r["properties"][0]["value"] for r in (read["a"], read["b"], read["d"])], ["a", "b", "d"])
        self.assertIsInstance(read["c"], MfgApiError)
        self.assertEqual(client.asked[0][2], list("abcd"))   # tried together first

    def test_a_busy_answer_fails_them_all_without_splitting_the_request(self):
        busy = MfgApiError("503", transient=True)
        client = FakeClient({}, error=busy)
        read = read_publish_components(client, SUMMARY, ["a", "b", "c"])
        self.assertEqual(len(client.asked), 1)
        self.assertTrue(all(value is busy for value in read.values()))

    def test_a_summary_without_a_composition_or_an_id_is_refused(self):
        with self.assertRaises(ValueError):
            read_publish_components(FakeClient({}), {}, ["a"])
        with self.assertRaises(ValueError):
            read_publish_components(FakeClient({}), SUMMARY, ["a", ""])


if __name__ == "__main__":
    unittest.main()
