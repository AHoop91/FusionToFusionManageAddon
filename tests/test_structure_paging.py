"""The structure is read a page at a time, says how far it has got, and is never passed off as complete when it is cut short."""

import unittest

from src.fusion_mfg import model_service
from src.fusion_mfg.graphql_client import MfgApiError

SUMMARY = {"component_id": "root", "composition": "ORIGINAL"}


def relation(number):
    return {"fromComponent": {"id": "root"}, "toComponent": {"id": f"c{number}"}}


def chain(levels):
    """Relations of one component under another, ``levels`` deep: root > c1 > c2 > ..."""
    parents = ["root"] + [f"c{n}" for n in range(1, levels)]
    return [{"fromComponent": {"id": parent}, "toComponent": {"id": f"c{n}"}} for n, parent in enumerate(parents, start=1)]


class Pages:
    """A client whose structure query answers the given pages in turn; every page but the last names a next one."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = 0

    def query(self, _text, _variables, label=""):
        page = self.pages[self.asked]
        self.asked += 1
        cursor = f"next{self.asked}" if self.asked < len(self.pages) else None
        return {"component": {"bomRelations": {"results": page, "pagination": {"cursor": cursor}}}}


class StructurePagingTests(unittest.TestCase):
    def test_every_page_is_read_and_progress_is_reported_until_the_last(self):
        client = Pages([[relation(1), relation(2)], [relation(3)]])
        seen = []
        rows = model_service.read_section(client, "structure", "m", "", SUMMARY, progress=seen.append)
        self.assertEqual(client.asked, 2)
        self.assertEqual(seen, [2])   # after the first page; the last page ends the read, so there is nothing more to wait for
        self.assertEqual(len(rows), 3)

    def test_a_structure_of_one_page_reports_no_progress(self):
        seen = []
        model_service.read_section(Pages([[relation(1)]]), "structure", "m", "", SUMMARY, progress=seen.append)
        self.assertEqual(seen, [])

    def test_a_structure_longer_than_the_page_limit_is_an_error(self):
        client = Pages([[relation(1)]] * (model_service.MAX_PAGES + 1))
        with self.assertRaises(MfgApiError):
            model_service.read_section(client, "structure", "m", "", SUMMARY)
        self.assertEqual(client.asked, model_service.MAX_PAGES)


class StructureDepthTests(unittest.TestCase):
    def test_an_assembly_deeper_than_twenty_levels_is_read_whole(self):
        rows = model_service.read_section(Pages([chain(30)]), "structure", "m", "", SUMMARY)
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[-1]["level"], 29)

    def test_a_read_that_reaches_the_depth_limit_is_an_error(self):
        with self.assertRaises(MfgApiError):
            model_service.read_section(Pages([chain(model_service.STRUCTURE_DEPTH)]), "structure", "m", "", SUMMARY)

    def test_a_component_inside_itself_is_an_error_not_a_cut_off(self):
        loop = [{"fromComponent": {"id": "root"}, "toComponent": {"id": "a"}},
                {"fromComponent": {"id": "a"}, "toComponent": {"id": "root"}}]
        with self.assertRaises(ValueError):
            model_service.read_section(Pages([loop]), "structure", "m", "", SUMMARY)


class LevelTests(unittest.TestCase):
    """One level is the lines directly under one component: the design's, or an assembly's that was opened."""

    def test_a_level_asks_for_one_level_under_the_component_it_is_given(self):
        asked = []

        class Client:
            def query(self, _text, variables, label=""):
                asked.append(variables)
                return {"component": {"bomRelations": {"results": [{"fromComponent": {"id": "asm"}, "toComponent": {"id": "c1", "hasChildren": True}}],
                                                       "pagination": {"cursor": None}}}}

        rows = model_service.read_section(Client(), "level", "m", "", SUMMARY, component_id="asm")
        self.assertEqual((asked[0]["componentId"], asked[0]["depth"]), ("asm", 1))
        self.assertEqual([(r["id"], r["level"], r["has_children"]) for r in rows], [("c1", 0, True)])

    def test_a_level_without_an_id_is_the_designs(self):
        client = Pages([[relation(1)]])
        rows = model_service.read_section(client, "level", "m", "", SUMMARY)
        self.assertEqual([r["id"] for r in rows], ["c1"])

    def test_lines_deeper_than_the_level_are_dropped_whatever_the_answer_holds(self):
        deeper = [relation(1), {"fromComponent": {"id": "c1"}, "toComponent": {"id": "c2"}}]
        rows = model_service.read_section(Pages([deeper]), "level", "m", "", SUMMARY)
        self.assertEqual([r["id"] for r in rows], ["c1"])


if __name__ == "__main__":
    unittest.main()
