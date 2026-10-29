import unittest

from src.fm.client import UPLOAD_CHUNK_BYTES, _chunks
from src.fm.items import ItemChoices, resolve_hits
from src.fm.tabs import COUNTED, TabService, parse_counts

TABS = {"tabs": [
    {"name": "PART_ATTACHMENTS", "totalCount": 6,
     "sectionCounts": [{"name": "DIRECT_ATTACHMENTS", "totalCount": 4}, {"name": "RELATED_ATTACHMENTS", "totalCount": 2}]},
    {"name": "BOM_LIST", "totalCount": 5, "sectionCounts": None},
]}


class TabCountTests(unittest.TestCase):
    def test_sections_are_counted_beside_the_total(self):
        counts = parse_counts(TABS)
        self.assertEqual(counts["PART_ATTACHMENTS"], 6)
        self.assertEqual(counts["PART_ATTACHMENTS/DIRECT_ATTACHMENTS"], 4)
        self.assertEqual(counts["BOM_LIST"], 5)

    def test_the_files_tab_counts_its_own_files(self):
        counts = parse_counts(TABS)
        self.assertEqual(counts[COUNTED["PART_ATTACHMENTS"]], 4)

    def test_a_tab_counts_its_total_when_the_answer_does_not_split_it(self):
        class Client:
            tenant = "acme"

            def get_json(self, path):
                return {"tabs": [{"name": "PART_ATTACHMENTS", "totalCount": 6}, {"name": "BOM_LIST", "totalCount": "many"}]}

        counts = TabService(Client()).counts("1", "2")
        self.assertEqual((counts["files"], counts["bom"], counts["changelog"]), (6, 0, 0))


class ResolveHitsTests(unittest.TestCase):
    TWINS = [{"id": "1", "descriptor": "PN-001276 - End Cap Pulley Side"}, {"id": "2", "descriptor": "PN-001276 - End Cap Pulley Side"}]

    def test_one_hit_is_used_without_asking(self):
        picked, competing = resolve_hits([self.TWINS[0]], "PN-001276")
        self.assertEqual(picked["id"], "1")
        self.assertEqual(len(competing), 1)

    def test_several_exact_hits_need_a_choice(self):
        picked, competing = resolve_hits(self.TWINS, "PN-001276")
        self.assertIsNone(picked)
        self.assertEqual([hit["id"] for hit in competing], ["1", "2"])

    def test_one_exact_hit_among_look_alikes_is_used(self):
        hits = [{"id": "1", "descriptor": "PN-0012761 - Other"}, {"id": "2", "descriptor": "PN-001276 - End Cap"}]
        picked, competing = resolve_hits(hits, "pn-001276")
        self.assertEqual(picked["id"], "2")
        self.assertEqual(len(competing), 1)

    def test_several_look_alikes_and_no_exact_hit_need_a_choice(self):
        hits = [{"id": "1", "descriptor": "PN-0012761 - A"}, {"id": "2", "descriptor": "PN-0012762 - B"}]
        picked, competing = resolve_hits(hits, "PN-001276")
        self.assertIsNone(picked)
        self.assertEqual(len(competing), 2)

    def test_a_chosen_item_settles_it(self):
        picked, competing = resolve_hits(self.TWINS, "PN-001276", "2")
        self.assertEqual(picked["id"], "2")
        self.assertEqual(len(competing), 2)

    def test_no_hits_is_nothing_to_choose(self):
        self.assertEqual(resolve_hits([], "PN-1"), (None, []))


class ItemChoicesTests(unittest.TestCase):
    TWINS = ResolveHitsTests.TWINS

    def test_a_choice_is_kept_by_workspace_and_number_ignoring_case(self):
        choices = ItemChoices()
        choices.set("242", "PN-001276", "2")
        self.assertEqual(choices.resolve("242", " pn-001276 ", self.TWINS)[0]["id"], "2")
        self.assertIsNone(choices.resolve("999", "PN-001276", self.TWINS)[0])

    def test_a_choice_that_is_no_longer_a_hit_is_forgotten(self):
        choices = ItemChoices()
        choices.set("242", "PN-001276", "7")
        self.assertIsNone(choices.resolve("242", "PN-001276", self.TWINS)[0])
        choices.set("242", "PN-001276", "")
        self.assertIsNone(choices.resolve("242", "PN-001276", self.TWINS)[0])

    def test_an_empty_id_clears_the_choice(self):
        choices = ItemChoices()
        choices.set("242", "PN-001276", "1")
        choices.set("242", "PN-001276", "")
        self.assertIsNone(choices.resolve("242", "PN-001276", self.TWINS)[0])


class ChunkTests(unittest.TestCase):
    def test_progress_reaches_one_and_the_bytes_are_unchanged(self):
        content = b"x" * (UPLOAD_CHUNK_BYTES * 2 + 5)
        seen = []
        body = b"".join(_chunks(content, seen.append))
        self.assertEqual(body, content)
        self.assertEqual(seen[-1], 1.0)
        self.assertEqual(len(seen), 3)


if __name__ == "__main__":
    unittest.main()
