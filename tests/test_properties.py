"""The properties a hub offers: base, then custom, each by name, with the hidden, archived and non-component ones left out."""

import unittest

from src.fusion_mfg.hub_lookup import HUBS_QUERY
from src.fusion_mfg.properties import DEFINITIONS_QUERY, PropertyService, parse_definitions


def collection(*definitions):
    return {"results": [{"name": "c", "definitions": {"results": list(definitions)}}]}


def definition(name, **extra):
    return {"name": name, "specification": "", "isHidden": False, "isArchived": False, "applicableEntityTypes": [], **extra}


def answer(base=(), custom=()):
    return {"hub": {"basePropertyDefinitionCollections": collection(*base), "propertyDefinitionCollections": collection(*custom)}}


def names(properties, group):
    return [p["name"] for p in properties if p["group"] == group]


class ParseTests(unittest.TestCase):
    def test_base_then_custom_each_by_name_then_physical(self):
        found = parse_definitions(answer(base=[definition("b"), definition("A")], custom=[definition("z"), definition("Y")]))
        self.assertEqual([p["group"] for p in found], ["base", "base", "custom", "custom"] + ["physical"] * 7)
        self.assertEqual(names(found, "base"), ["A", "b"])
        self.assertEqual(names(found, "custom"), ["Y", "z"])

    def test_hidden_archived_and_nameless_are_left_out(self):
        found = parse_definitions(answer(base=[definition("hidden", isHidden=True), definition("old", isArchived=True), definition(""), definition("ok")]))
        self.assertEqual(names(found, "base"), ["ok"])

    def test_only_properties_of_components_are_offered(self):
        found = parse_definitions(answer(base=[definition("part", applicableEntityTypes=["COMPONENT", "DRAWING"]),
                                               definition("drawing", applicableEntityTypes=["DRAWING"]), definition("any")]))
        self.assertEqual(names(found, "base"), ["any", "part"])

    def test_a_property_carries_its_specification(self):
        found = parse_definitions(answer(base=[definition("mass", specification="MASS")]))
        self.assertEqual(found[0], {"name": "mass", "group": "base", "specification": "MASS"})

    def test_a_name_that_is_repeated_is_listed_once(self):
        found = parse_definitions(answer(base=[definition("a", specification="first"), definition("a", specification="second")]))
        self.assertEqual([(p["name"], p["specification"]) for p in found if p["group"] == "base"], [("a", "second")])


class ServiceTests(unittest.TestCase):
    def test_the_hub_is_found_by_name_and_its_definitions_read(self):
        asked = []

        class Client:
            def query(self, text, variables=None, label=""):
                asked.append((text, variables))
                return {"hubs": {"results": [{"id": "h1", "name": "Acme"}]}} if text == HUBS_QUERY else answer(base=[definition("a")])

        found = PropertyService(Client()).list_properties("Acme")
        self.assertEqual(asked, [(HUBS_QUERY, None), (DEFINITIONS_QUERY, {"hubId": "h1"})])
        self.assertEqual(names(found, "base"), ["a"])


if __name__ == "__main__":
    unittest.main()
