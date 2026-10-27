"""The message boxes that say how a publish and a send ended."""

import unittest
from types import SimpleNamespace

from src.publish.reports import MAX_LISTED, publish_report, send_report


def run(rows=(), phase="done", sends=True, entries=()):
    return SimpleNamespace(name="PN-1", phase=phase, message="boom", sends=sends, done=3, total=3,
                           rows=[{"item": f"PN-{n}", "status": status, "detail": "no"} for n, status in enumerate(rows)],
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

    def test_a_send_says_how_many_steps_failed(self):
        self.assertEqual(send_report(run()), "PN-1 was sent to Fusion Manage.\n\nSteps completed: 3 of 3")
        text = send_report(run(rows=["done", "error"]))
        self.assertTrue(text.startswith("Sending PN-1 finished with errors: 1 of 3 step(s) failed.\n\n  - PN-1: no\n"))
        self.assertTrue(text.endswith("what Fusion Manage accepted is skipped."))


if __name__ == "__main__":
    unittest.main()
