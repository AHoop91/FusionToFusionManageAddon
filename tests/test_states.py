"""The words a job and its rows are in: the panels read them, so they are pinned here."""

import re
import unittest
from pathlib import Path

from src.publish import states
from src.publish.job_queue import FAILED, IDLE, WORKING

ROOT = Path(__file__).resolve().parent.parent
JOBS_JS = ROOT / "src" / "ui" / "web" / "publish" / "js" / "publish-jobs.js"


class StatesTests(unittest.TestCase):
    def test_the_words_are_the_ones_the_panels_read(self):
        self.assertEqual((states.QUEUED, states.RUNNING, states.DONE, states.ERROR, states.CANCELLED),
                         ("queued", "running", "done", "error", "cancelled"))

    def test_a_state_is_active_or_ended_and_never_both(self):
        every = {states.QUEUED, states.RUNNING, states.DONE, states.ERROR, states.CANCELLED}
        self.assertEqual(set(states.ACTIVE) | set(states.FINISHED), every)
        self.assertEqual(set(states.ACTIVE) & set(states.FINISHED), set())

    def test_the_queues_own_words_are_the_ones_the_ribbon_button_looks_up(self):
        self.assertEqual((IDLE, WORKING, FAILED), ("idle", "running", "error"))

    def test_the_jobs_panel_names_every_word_that_a_job_can_be_in(self):
        source = JOBS_JS.read_text(encoding="utf-8")
        for word in (states.QUEUED, states.RUNNING, states.DONE, states.ERROR, states.CANCELLED):
            with self.subTest(word=word):
                self.assertRegex(source, r"""['"]""" + re.escape(word) + r"""['"]""")


if __name__ == "__main__":
    unittest.main()
