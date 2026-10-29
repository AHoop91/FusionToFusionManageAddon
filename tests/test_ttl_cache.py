import threading
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

    def test_an_expired_entry_is_dropped_when_it_is_asked_for(self):
        cache = TtlCache(seconds=10)
        with mock.patch.object(ttl_cache.time, "monotonic", return_value=100.0):
            cache.put("key", 1)
        with mock.patch.object(ttl_cache.time, "monotonic", return_value=200.0):
            self.assertIsNone(cache.get("key"))
        self.assertEqual(len(cache._entries), 0)

    def test_expired_entries_nobody_asks_for_again_do_not_pile_up(self):
        cache = TtlCache(seconds=10)
        with mock.patch.object(ttl_cache.time, "monotonic", return_value=100.0):
            for i in range(ttl_cache.SWEEP_AT):
                cache.put(i, i)
        with mock.patch.object(ttl_cache.time, "monotonic", return_value=200.0):
            cache.put("new", 1)
        self.assertEqual(list(cache._entries), ["new"])

    def test_entries_that_are_still_good_survive_a_sweep(self):
        cache = TtlCache(seconds=10)
        for i in range(ttl_cache.SWEEP_AT):
            cache.put(i, i)
        cache.put("new", 1)
        self.assertEqual((cache.get(0), cache.get("new")), (0, 1))

    def test_threads_may_use_it_together(self):
        cache = TtlCache()

        def work(n):
            for i in range(500):
                cache.put((n, i % 20), i)
                cache.get((n, (i + 1) % 20))
        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(cache._entries), 8 * 20)


class ClockTests(unittest.TestCase):
    def test_a_cache_goes_by_the_clock_it_is_given(self):
        now = [100.0]
        cache = TtlCache(5, clock=lambda: now[0])
        cache.put("a", 1)
        now[0] = 104.9
        self.assertEqual(cache.get("a"), 1)
        now[0] = 105.0
        self.assertIsNone(cache.get("a"))


if __name__ == "__main__":
    unittest.main()
