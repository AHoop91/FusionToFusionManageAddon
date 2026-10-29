"""Cancelling a publish run ends its reads, and is not a failure; what it writes is not cut short."""

import shutil
import tempfile
import unittest
from unittest import mock

from src.core.cancel import Cancelled
from src.publish import runner
from src.publish.runner import PublishRun
from src.publish.states import CANCELLED, DONE, ERROR
from src.publish.writer import PublishFolder


class Client:
    """A client that makes the one it is asked for under another token, and notes it."""

    def __init__(self, name):
        self.name, self.token, self.tenant = name, None, "acme"

    def with_cancel(self, token):
        other = Client(self.name + " under a token")
        other.token = token
        return other


def cfg():
    return mock.Mock(workspace_id="", static_values=[], mappings=[], maps_physical=lambda: False)


class PublishRunCancelTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        self.folder = PublishFolder(root, "R")

    def run_of(self, items=(), send=False):
        job = {"summary": {}, "items": list(items), "operations": [], "root_number": "R"}
        return PublishRun(self.folder, job, cfg(), Client("graphql"), Client("fm"), "m1", "t1", send=send)

    def test_every_request_is_made_under_the_runs_token_the_writes_too(self):
        run = self.run_of(send=True)
        self.assertIs(run._client.token, run.token)
        self.assertIs(run._fm.token, run.token)
        self.assertIs(run._dispatcher._fm, run._fm)

    def test_a_read_ended_by_the_cancel_ends_the_run_as_cancelled_not_as_an_error(self):
        run = self.run_of()
        with mock.patch.object(PublishRun, "_require_unique_numbers", side_effect=Cancelled()):
            run.work()
        self.assertEqual((run.phase, run.message), (CANCELLED, "Cancelled."))

    def test_an_item_whose_read_was_ended_is_cancelled_not_failed(self):
        item = {"item_number": "PN-1", "id": "c1"}
        run = self.run_of([item])
        with mock.patch.object(PublishRun, "_item", side_effect=Cancelled()):
            run._prepare(item)
        row = run.rows[0]
        self.assertEqual((row["status"], row["detail"]), (CANCELLED, "Cancelled."))
        self.assertEqual(self.folder.entries_of("PN-1"), [])   # nothing recorded as failed

    def test_a_thumbnail_download_ended_by_the_cancel_is_not_tried_again_or_recorded_as_failed(self):
        run = self.run_of()
        with mock.patch.object(runner, "download", side_effect=Cancelled()) as download, \
                mock.patch.object(runner, "read_thumbnail_url") as fresh:
            with self.assertRaises(Cancelled):
                run._thumbnail("PN-1", self.folder.path, "c1", "https://x.example/t.png")
        fresh.assert_not_called()
        self.assertIs(download.call_args.kwargs["cancel"], run.token)
        self.assertEqual(self.folder.entries_of("PN-1"), [])

    def test_a_download_that_fails_otherwise_asks_for_a_fresh_address_under_the_token(self):
        run = self.run_of()
        with mock.patch.object(runner, "download", side_effect=[ValueError("expired"), b"png"]) as download, \
                mock.patch.object(runner, "read_thumbnail_url", return_value="https://x.example/new.png"):
            self.assertEqual(run._download_thumbnail("c1", "https://x.example/old.png"), b"png")
        self.assertEqual([c.args[0] for c in download.call_args_list], ["https://x.example/old.png", "https://x.example/new.png"])
        self.assertTrue(all(c.kwargs["cancel"] is run.token for c in download.call_args_list))

    def test_a_run_nothing_cancels_finishes(self):
        run = self.run_of()
        run.work()
        self.assertEqual(run.phase, DONE)
        self.assertNotEqual(run.phase, ERROR)

    def test_cancelling_the_run_cancels_its_token(self):
        run = self.run_of()
        run.cancel()
        self.assertTrue(run.token.cancelled)


if __name__ == "__main__":
    unittest.main()
