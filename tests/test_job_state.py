"""What the panels poll of a job: what the steps came to."""

import unittest

from src.publish.job_state import JobState


class Job(JobState):
    def _counts(self):
        return {"update": 2}


class JobStateTests(unittest.TestCase):
    def test_the_snapshot_carries_what_the_steps_came_to(self):
        job = Job("PN-1", "folder")
        job.rows = [job.row("A", "")]
        snapshot = job.snapshot()
        self.assertEqual(snapshot["counts"], {"update": 2})
        self.assertEqual([r["item"] for r in snapshot["rows"]], ["A"])


if __name__ == "__main__":
    unittest.main()
