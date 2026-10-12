"""The Data Model client tries a read again when the service was busy, and not when the query was wrong."""

import unittest
from unittest import mock

from src.fusion_mfg import graphql_client
from src.fusion_mfg.graphql_client import MfgApiError, MfgGraphQlClient


def client(outcomes):
    """A client whose requests give ``outcomes`` in turn: an exception is raised, anything else returned."""
    made = MfgGraphQlClient(None, None)
    calls = iter(outcomes)

    def once(text, variables, label=""):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    made._query_once = once
    return made


class RetryTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(graphql_client.time, "sleep")
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_busy_service_is_tried_again(self):
        self.assertEqual(client([MfgApiError("503", transient=True), {"ok": 1}]).query("q"), {"ok": 1})

    def test_a_wrong_query_is_not(self):
        with self.assertRaises(MfgApiError):
            client([MfgApiError("bad field"), {"ok": 1}]).query("q")

    def test_it_gives_up_after_three_tries(self):
        with self.assertRaises(MfgApiError):
            client([MfgApiError("503", transient=True)] * 3).query("q")


if __name__ == "__main__":
    unittest.main()
