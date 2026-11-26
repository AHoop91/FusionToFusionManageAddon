"""How long to wait before a request is tried again: the server's Retry-After first, else a growing wait spread at random."""

import unittest
from datetime import datetime, timezone
from unittest import mock

from src.core import backoff

NOW = datetime(2026, 11, 26, 12, 0, 0, tzinfo=timezone.utc)


class RetryAfterTests(unittest.TestCase):
    def test_whole_seconds(self):
        self.assertEqual(backoff.retry_after({"Retry-After": "12"}), 12.0)

    def test_the_header_name_is_not_case_sensitive(self):
        self.assertEqual(backoff.retry_after({"retry-after": "5"}), 5.0)

    def test_an_http_date_is_the_seconds_until_then(self):
        self.assertEqual(backoff.retry_after({"Retry-After": "Thu, 26 Nov 2026 12:00:30 GMT"}, NOW), 30.0)

    def test_a_date_already_past_is_no_wait(self):
        self.assertEqual(backoff.retry_after({"Retry-After": "Thu, 26 Nov 2026 11:00:00 GMT"}, NOW), 0.0)

    def test_none_or_something_else_is_none(self):
        for headers in (None, {}, {"Retry-After": ""}, {"Retry-After": "soon"}, {"Retry-After": "-3"}):
            self.assertIsNone(backoff.retry_after(headers), headers)


class DelayTests(unittest.TestCase):
    def test_the_wait_grows_with_each_try_up_to_a_cap(self):
        with mock.patch.object(backoff.random, "uniform", side_effect=lambda low, high: high):   # the longest the jitter allows
            waits = [backoff.delay(attempt) for attempt in (1, 2, 3, 4, 10)]
        self.assertEqual(waits, [1.0, 2.0, 4.0, 8.0, backoff.CAP_SECONDS])

    def test_the_wait_is_spread_and_never_near_zero(self):
        for attempt in (1, 2, 3):
            ceiling = backoff.BASE_SECONDS * 2 ** (attempt - 1)
            waits = {backoff.delay(attempt) for _ in range(50)}
            self.assertGreater(len(waits), 1)
            self.assertTrue(all(ceiling / 2 <= w <= ceiling for w in waits))

    def test_what_the_server_asks_is_the_least_waited(self):
        for _ in range(20):
            self.assertTrue(10 <= backoff.delay(1, 10) <= 10 + backoff.AFTER_JITTER_SECONDS)

    def test_a_request_for_too_long_a_wait_is_a_reason_to_give_up(self):
        self.assertIsNone(backoff.delay(1, backoff.MAX_RETRY_AFTER_SECONDS + 1))


if __name__ == "__main__":
    unittest.main()
