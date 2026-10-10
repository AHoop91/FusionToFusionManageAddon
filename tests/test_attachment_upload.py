import unittest

from src.fm.client import UPLOAD_CHUNK_BYTES, _chunks
from src.fm.items import pick_hit
from src.fm.tabs import COUNTED, parse_counts

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


class PickHitTests(unittest.TestCase):
    HITS = [{"id": "1", "descriptor": "PN-0007011 - Other"}, {"id": "2", "descriptor": "PN-000701 - Universal Joint"}]

    def test_the_exact_item_number_wins_over_an_earlier_hit(self):
        self.assertEqual(pick_hit(self.HITS, "PN-000701")["id"], "2")

    def test_the_first_hit_is_used_when_none_matches_exactly(self):
        self.assertEqual(pick_hit(self.HITS, "PN-9")["id"], "1")


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
