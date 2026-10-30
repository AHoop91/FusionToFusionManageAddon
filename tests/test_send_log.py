"""The log of what a send did: what is accepted, what is in doubt, and a log that is always written whole."""

import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from src.core.atomic import REPLACE_TRIES
from src.publish import send_log
from src.publish.send_log import SEND_LOG, FolderError, LogWriteError, SendLog


def logged(folder):
    with open(os.path.join(folder, SEND_LOG), encoding="utf-8") as handle:
        return json.load(handle)


class SendLogTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = self.dir.name

    def test_a_request_is_done_once_accepted_and_is_on_disk_at_once(self):
        sends = SendLog(self.folder)
        self.assertFalse(sends.done("item:A"))
        sends.accept("item:A", {"id": "7"})
        self.assertTrue(sends.done("item:A"))
        self.assertEqual(sends.entry("item:A"), {"id": "7"})
        self.assertEqual(logged(self.folder), {"item:A": {"id": "7"}})

    def test_a_request_that_was_cut_off_is_in_doubt_and_not_done(self):
        sends = SendLog(self.folder)
        sends.doubt("item:A", "was cancelled")
        self.assertEqual((sends.done("item:A"), sends.in_doubt("item:A")), (False, True))
        self.assertEqual(logged(self.folder), {"item:A": {"in_doubt": True}})

    def test_a_request_that_was_never_sent_is_neither(self):
        sends = SendLog(self.folder)
        self.assertEqual((sends.done("x"), sends.in_doubt("x"), sends.entry("x")), (False, False, {}))

    def test_a_request_accepted_after_it_was_in_doubt_is_done(self):
        sends = SendLog(self.folder)
        sends.doubt("item:A", "was cancelled")
        sends.accept("item:A", {"id": "7"})
        self.assertEqual((sends.done("item:A"), sends.in_doubt("item:A")), (True, False))

    def test_an_earlier_send_is_remembered_by_the_next_log_of_the_folder(self):
        SendLog(self.folder).accept("item:A", {"id": "7"})
        again = SendLog(self.folder)
        self.assertTrue(again.done("item:A"))
        self.assertEqual(again.entry("item:A"), {"id": "7"})

    def test_a_log_that_cannot_be_read_is_an_error_not_an_empty_log(self):
        with open(os.path.join(self.folder, SEND_LOG), "w", encoding="utf-8") as handle:
            handle.write("{broken")
        with self.assertRaisesRegex(FolderError, "could create items twice"):
            SendLog(self.folder)

    def test_an_entry_that_is_not_an_object_reads_as_empty(self):
        with open(os.path.join(self.folder, SEND_LOG), "w", encoding="utf-8") as handle:
            json.dump({"item:A": "text"}, handle)
        sends = SendLog(self.folder)
        self.assertEqual((sends.done("item:A"), sends.entry("item:A")), (True, {}))

    def test_a_log_refused_for_a_moment_is_replaced_when_it_is_not(self):
        real, refusals = os.replace, [PermissionError("in use"), PermissionError("in use")]

        def replace(source, target):
            if refusals:
                raise refusals.pop()
            real(source, target)

        with mock.patch("src.core.atomic.os.replace", replace), mock.patch("src.core.atomic.time.sleep"):
            SendLog(self.folder).accept("item:A", {"id": "1"})
        self.assertEqual(logged(self.folder), {"item:A": {"id": "1"}})

    def test_a_log_that_stays_refused_is_raised_saying_what_it_means_not_hidden(self):
        with mock.patch("src.core.atomic.os.replace", side_effect=PermissionError("in use")) as replace, \
                mock.patch("src.core.atomic.time.sleep"):
            with self.assertRaises(LogWriteError) as caught:
                SendLog(self.folder).accept("item:A", {"id": "1"})
        self.assertEqual(replace.call_count, REPLACE_TRIES)
        self.assertIsInstance(caught.exception.__cause__, PermissionError)
        self.assertIn("may be sent twice", str(caught.exception))

    def test_a_log_that_cannot_be_written_at_all_is_the_same_error_and_the_entry_is_kept_in_memory(self):
        sends = SendLog(os.path.join(self.folder, "missing"))   # no folder to write in
        with self.assertRaises(LogWriteError):
            sends.accept("item:A", {"id": "1"})
        self.assertTrue(sends.done("item:A"))   # it was accepted: this run does not send it again

    def test_many_records_in_a_row_all_reach_the_log(self):
        sends = SendLog(self.folder)
        for i in range(300):
            sends.accept(f"bom:A:{i}", {})
        self.assertEqual(len(logged(self.folder)), 300)
        self.assertFalse(os.path.exists(os.path.join(self.folder, SEND_LOG + ".tmp")))


class SharedWriteTests(unittest.TestCase):
    """Requests sent together are logged together: a write made while another is under way is carried by the next one."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = self.dir.name
        self.writes = []
        real = send_log.write_atomically

        def slow(path, data):
            self.writes.append(1)
            time.sleep(0.03)   # storage that takes a while, or a scanner holding the file
            real(path, data)

        patch = mock.patch.object(send_log, "write_atomically", slow)
        patch.start()
        self.addCleanup(patch.stop)

    def log_together(self, sends, count=20):
        on_disk, errors = {}, []

        def log(i):
            key = f"item:{i}"
            try:
                sends.accept(key, {"id": str(i)})
                on_disk[key] = key in logged(self.folder)   # on disk when accept returns, though another thread may have written it
            except LogWriteError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=log, args=(i,)) for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return on_disk, errors

    def test_requests_logged_together_share_writes_and_all_reach_the_log(self):
        on_disk, errors = self.log_together(SendLog(self.folder))
        self.assertEqual(errors, [])
        self.assertEqual(len(logged(self.folder)), 20)
        self.assertLess(len(self.writes), 20)

    def test_each_request_is_on_disk_when_its_accept_returns(self):
        on_disk, _errors = self.log_together(SendLog(self.folder))
        self.assertEqual(len(on_disk), 20)
        self.assertTrue(all(on_disk.values()))

    def test_a_write_that_fails_is_raised_to_the_thread_that_made_it_and_the_next_carries_what_was_missed(self):
        sends = SendLog(self.folder)
        real = send_log.write_atomically
        failing = [True]

        def flaky(path, data):
            if failing:
                failing.pop()
                raise OSError("disk full")
            real(path, data)

        with mock.patch.object(send_log, "write_atomically", flaky):
            with self.assertRaises(LogWriteError):
                sends.accept("item:A", {"id": "1"})
            sends.accept("item:B", {"id": "2"})
        self.assertEqual(sorted(logged(self.folder)), ["item:A", "item:B"])   # A was not lost: the write that worked held it too

    def test_what_was_taken_back_is_gone_from_the_log(self):
        sends = SendLog(self.folder)
        sends.intend("item:A")
        sends.forget("item:A")
        self.assertEqual(logged(self.folder), {})
        self.assertFalse(sends.in_doubt("item:A"))

    def test_taking_back_what_cannot_be_written_is_not_an_error(self):
        sends = SendLog(self.folder)
        sends.intend("item:A")
        with mock.patch.object(send_log, "write_atomically", side_effect=OSError("disk full")):
            sends.forget("item:A")   # it stays on disk as in doubt, which only costs the next send a look
        self.assertEqual(logged(self.folder), {"item:A": {"in_doubt": True}})


if __name__ == "__main__":
    unittest.main()
