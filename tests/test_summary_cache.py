"""A design's summary is kept on disk per version, survives a restart, and a damaged file only costs the copies in it."""

import os
import tempfile
import unittest

from src.fusion_mfg import summary_cache
from src.fusion_mfg.summary_cache import SummaryCache

SUMMARY = {"component_id": "c1", "composition": "ORIGINAL", "item_number": "PN-1", "part_number": "PN-1", "description": "Joint"}


class SummaryCacheTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "summary-cache.json")

    def test_an_unknown_version_has_nothing(self):
        self.assertIsNone(SummaryCache(self.path).get("model|2026"))

    def test_a_kept_summary_is_given_back_and_survives_a_restart(self):
        SummaryCache(self.path).put("model|2026", SUMMARY)
        self.assertEqual(SummaryCache(self.path).get("model|2026"), SUMMARY)

    def test_another_version_of_the_same_model_is_another_entry(self):
        cache = SummaryCache(self.path)
        cache.put("model|2026", SUMMARY)
        self.assertIsNone(cache.get("model|2027"))

    def test_a_summary_is_replaced_by_a_newer_one(self):
        cache = SummaryCache(self.path)
        cache.put("model|2026", SUMMARY)
        cache.put("model|2026", {**SUMMARY, "description": "Changed"})
        self.assertEqual(SummaryCache(self.path).get("model|2026")["description"], "Changed")

    def test_a_copy_given_back_cannot_change_what_is_kept(self):
        cache = SummaryCache(self.path)
        cache.put("model|2026", SUMMARY)
        cache.get("model|2026")["description"] = "Changed"
        self.assertEqual(cache.get("model|2026")["description"], "Joint")

    def test_the_least_recently_used_goes_first(self):
        original = summary_cache.MAX_ENTRIES
        summary_cache.MAX_ENTRIES = 2
        self.addCleanup(setattr, summary_cache, "MAX_ENTRIES", original)
        cache = SummaryCache(self.path)
        cache.put("a", SUMMARY)
        cache.put("b", SUMMARY)
        cache.get("a")            # a is used again, so b is now the oldest
        cache.put("c", SUMMARY)
        self.assertIsNotNone(cache.get("a"))
        self.assertIsNone(cache.get("b"))
        self.assertIsNotNone(cache.get("c"))

    def test_a_damaged_file_starts_the_cache_again(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        cache = SummaryCache(self.path)
        self.assertIsNone(cache.get("model|2026"))
        cache.put("model|2026", SUMMARY)
        self.assertEqual(SummaryCache(self.path).get("model|2026"), SUMMARY)


if __name__ == "__main__":
    unittest.main()
