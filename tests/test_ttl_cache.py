import unittest
from unittest import mock

from src.fm import ttl_cache
from src.fm.ttl_cache import TtlCache


class TtlCacheTests(unittest.TestCase):
    def test_a_missing_key_is_none(self):
        self.assertIsNone(TtlCache().get(("tenant", "1")))

    def test_a_kept_value_is_returned_until_it_expires(self):
        cache = TtlCache(seconds=10)
        with mock.patch.object(ttl_cache.time, "monotonic", return_value=100.0):
            self.assertEqual(cache.put("key", {"a": 1}), {"a": 1})
        with mock.patch.object(ttl_cache.time, "monotonic", return_value=109.0):
            self.assertEqual(cache.get("key"), {"a": 1})
        with mock.patch.object(ttl_cache.time, "monotonic", return_value=110.0):
            self.assertIsNone(cache.get("key"))

    def test_an_empty_value_is_kept(self):
        cache = TtlCache()
        cache.put("key", set())
        self.assertEqual(cache.get("key"), set())

    def test_clear_drops_everything(self):
        cache = TtlCache()
        cache.put("key", 1)
        cache.clear()
        self.assertIsNone(cache.get("key"))


if __name__ == "__main__":
    unittest.main()
