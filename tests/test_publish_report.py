"""The message boxes that say how a publish and a send ended."""

import unittest
from types import SimpleNamespace

from src.publish.reports import DETAIL_CHARS, MAX_LISTED, cut_off, publish_report, send_report
from src.publish.sender import CUT_OFF


def run(rows=(), phase="done", sends=True, entries=(), details=None, message="boom"):
    return SimpleNamespace(name="PN-1", phase=phase, message=message, sends=sends, done=3, total=3,
                           rows=[{"item": f"PN-{n}", "status": status, "detail": (details or {}).get(n, "no")} for n, status in enumerate(rows)],
                           folder=SimpleNamespace(path="C:/out", entries=list(entries)))


def entry(artifact, detail):
    return {"artifact": artifact, "status": "ok", "detail": detail}


class ReportTests(unittest.TestCase):
    def test_a_clean_publish_counts_what_was_created_and_updated(self):
        text = publish_report(run(entries=[entry("sent to Fusion Manage", "POST 201"), entry("sent to Fusion Manage", "PATCH 200"),
                                    entry("sent to Fusion Manage", "PATCH 200")]))
        self.assertTrue(text.startswith("Publish of PN-1 completed successfully.\n\nTotal Items Processed: 3\n"))
        self.assertIn("Total Items Created: 1\nTotal Items Updated: 2", text)
        self.assertNotIn("The files are in", text)   # a run that went through has its files removed

    def test_a_run_that_only_wrote_requests_says_nothing_was_sent(self):
        text = publish_report(run(sends=False, entries=[entry("item request", "POST /x")]))
        self.assertIn("Total Items Created: 1", text)
        self.assertTrue(text.endswith("Nothing has been sent to Fusion Manage yet."))

    def test_failures_are_named_up_to_a_limit_and_point_to_the_retry(self):
        text = publish_report(run(rows=["error"] * (MAX_LISTED + 2)))
        self.assertIn("completed with errors: 7 step(s) failed.", text)
        self.assertEqual(text.count("  - PN-"), MAX_LISTED)
        self.assertIn("  - and 2 more", text)
        self.assertIn("Use Retry on the job", text)
        self.assertIn("The files are in C:/out", text)   # a failed run keeps them, for Retry

    def test_a_failed_run_gives_its_reason(self):
        self.assertEqual(publish_report(run(phase="error")), "Publish of PN-1 could not be completed.\n\nReason: boom")

    def test_a_failed_run_with_no_reason_says_so(self):
        self.assertEqual(publish_report(run(phase="error", message="")), "Publish of PN-1 could not be completed.\n\nReason: no reason was given")
        self.assertTrue(send_report(run(phase="error", message="")).endswith("Reason: no reason was given"))

    def test_a_long_reason_is_cut_to_what_a_message_box_shows(self):
        text = publish_report(run(rows=["error"], details={0: "x" * 500}))
        self.assertIn("  - PN-0: " + "x" * DETAIL_CHARS + "\n", text)

    def test_a_step_that_failed_with_no_reason_says_failed(self):
        self.assertIn("  - PN-0: Failed.", publish_report(run(rows=["error"], details={0: ""})))

    def test_a_cancelled_run_says_how_far_it_got_and_names_what_was_cut_off(self):
        text = publish_report(run(phase="cancelled", rows=["done", "cancelled", "cancelled"], details={1: CUT_OFF}))
        self.assertTrue(text.startswith("Publish of PN-1 was cancelled.\n\nSteps completed before it stopped: 3 of 3."))
        self.assertIn("  - PN-1\n", text + "\n")
        self.assertNotIn("PN-2", text)   # cancelled before it started: not in doubt
        self.assertIn("Use Retry on the job", text)
        self.assertEqual(cut_off(run(rows=["done", "cancelled"], details={1: CUT_OFF})), ["PN-1"])

    def test_a_cancelled_run_with_nothing_cut_off_says_only_that_it_was_cancelled(self):
        for report, start in ((publish_report, "Publish of PN-1"), (send_report, "Sending PN-1")):
            text = report(run(phase="cancelled", rows=["done", "cancelled"]))
            self.assertEqual(text, f"{start} was cancelled.\n\nSteps completed before it stopped: 3 of 3.")

    def test_a_send_says_how_many_steps_failed(self):
        self.assertEqual(send_report(run()), "PN-1 was sent to Fusion Manage.\n\nSteps completed: 3 of 3")
        text = send_report(run(rows=["done", "error"]))
        self.assertTrue(text.startswith("Sending PN-1 finished with errors: 1 of 3 step(s) failed.\n\n  - PN-1: no\n"))
        self.assertTrue(text.endswith("what Fusion Manage accepted is skipped."))


if __name__ == "__main__":
    unittest.main()
