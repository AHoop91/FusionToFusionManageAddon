"""What the panels poll of a job: what the steps came to."""

import unittest

from unittest import mock

from src.core.cancel import ADDIN, Cancelled, CancelToken
from src.publish.job_state import JobState, JobStopped
from src.publish.states import CANCELLED, DONE, ERROR, QUEUED, RUNNING


class Job(JobState):
    def _counts(self):
        return {"update": 2}


class Ending(JobState):
    """A job that notes how it was ended, as a subclass records its own."""

    def __init__(self):
        super().__init__("PN-1", "folder")
        self.ended = []
        self.rows = [self.row("A", ""), self.row("B", "")]

    def _finish(self, phase, message):
        self.ended.append((phase, message))
        self._end(phase, message)


class JobStateTests(unittest.TestCase):
    def test_a_waiting_job_that_is_cancelled_ends_cancelled_and_never_starts(self):
        job = Ending()
        job.cancel()
        self.assertEqual(job.ended, [(CANCELLED, "Cancelled.")])
        self.assertFalse(job._start())
        self.assertEqual({r["status"] for r in job.rows}, {CANCELLED})
        self.assertEqual({r["detail"] for r in job.rows}, {"Cancelled."})

    def test_a_running_job_that_is_cancelled_is_only_flagged_for_its_worker_to_stop(self):
        job = Ending()
        self.assertTrue(job._start())
        job.cancel()
        self.assertEqual((job.phase, job.cancelled, job.ended), (RUNNING, True, []))

    def test_cancelling_a_job_ends_the_reads_it_has_under_way(self):
        for waiting in (True, False):
            with self.subTest(waiting=waiting):
                job = Ending()
                if not waiting:
                    job._start()
                self.assertFalse(job.token.cancelled)
                job.cancel()
                self.assertTrue(job.token.cancelled)

    def test_a_job_has_a_token_of_its_own_unless_given_one_and_the_add_in_stopping_ends_it(self):
        own, other = Ending(), Ending()
        self.assertIsNot(own.token, other.token)
        own.token.cancel()
        self.assertFalse(other.token.cancelled)
        given = CancelToken()
        self.assertIs(Job("PN-1", "folder", given).token, given)
        child = Ending()
        ADDIN.cancel()
        try:
            self.assertTrue(child.token.cancelled)
        finally:
            ADDIN.reset()

    def test_cancelling_a_job_that_has_ended_leaves_its_token_alone(self):
        job = Ending()
        job._start()
        job._finish(DONE, "")
        job.cancel()
        self.assertFalse(job.token.cancelled)

    def test_cancelling_a_job_that_has_ended_changes_nothing(self):
        job = Ending()
        job._start()
        job._finish(DONE, "")
        job.cancel()
        self.assertEqual((job.phase, job.cancelled, job.ended), (DONE, False, [(DONE, "")]))

    def test_attributes_are_set_together_and_a_misspelt_one_is_refused(self):
        job = Ending()
        job._set(stage="bom", message="m")
        self.assertEqual((job.stage, job.message), ("bom", "m"))
        with self.assertRaises(AttributeError):
            job._set(stge="x", message="n")
        self.assertEqual(job.message, "m")   # nothing was set

    def test_ending_also_marks_a_row_still_running_cut_short(self):
        job = Ending()
        job.rows[0]["status"] = RUNNING
        job._start()
        job._finish(ERROR, "broke")
        self.assertEqual([r["status"] for r in job.rows], [CANCELLED, CANCELLED])
        self.assertEqual(job.rows[0]["detail"], job.unreached)

    def outcome(self, **steps):
        job = Ending()
        with mock.patch.object(Ending, "_steps", create=True, **steps):
            return job._outcome()

    def test_steps_that_finish_end_the_job_done(self):
        self.assertEqual(self.outcome(), (DONE, ""))

    def test_a_job_cancelled_between_steps_ends_cancelled(self):
        job = Ending()
        job.cancelled = True
        with mock.patch.object(Ending, "_steps", create=True):
            self.assertEqual(job._outcome(), (CANCELLED, "Cancelled."))

    def test_a_request_the_cancel_ended_ends_the_job_cancelled(self):
        self.assertEqual(self.outcome(side_effect=Cancelled()), (CANCELLED, "Cancelled."))

    def test_a_stop_the_job_expects_ends_it_with_its_reason_as_an_error(self):
        self.assertEqual(self.outcome(side_effect=JobStopped("Nothing was sent.")), (ERROR, "Nothing was sent."))

    def test_any_other_failure_ends_the_job_with_its_message_or_its_type(self):
        self.assertEqual(self.outcome(side_effect=ValueError("bad")), (ERROR, "bad"))
        self.assertEqual(self.outcome(side_effect=KeyError()), (ERROR, "KeyError"))

    def test_work_ends_the_job_as_the_steps_went_and_a_job_cancelled_while_waiting_never_starts(self):
        job = Ending()
        with mock.patch.object(Ending, "_steps", create=True, side_effect=JobStopped("why")):
            job.work()
        self.assertEqual((job.phase, job.message, job.ended), (ERROR, "why", [(ERROR, "why")]))
        waiting = Ending()
        waiting.cancel()
        with mock.patch.object(Ending, "_steps", create=True) as steps:
            waiting.work()
        steps.assert_not_called()

    def test_a_job_with_no_steps_of_its_own_says_so(self):
        with self.assertRaises(NotImplementedError):
            Job("PN-1", "folder")._steps()

    def test_a_job_is_started_once(self):
        job = Ending()
        self.assertEqual((job._start(), job._start()), (True, False))

    def test_ending_marks_the_rows_never_reached_and_says_why(self):
        job = Ending()
        job.rows[0]["status"] = DONE
        job._start()
        job._finish(ERROR, "broke")
        self.assertEqual([r["status"] for r in job.rows], [DONE, CANCELLED])
        self.assertEqual(job.rows[1]["detail"], job.unreached)
        self.assertEqual((job.phase, job.message), (ERROR, "broke"))
        self.assertGreater(job.finished_at, 0)

    def test_a_snapshot_is_a_copy_the_job_can_change_under(self):
        job = Ending()
        snapshot = job.snapshot()
        job.rows[0]["status"] = DONE
        self.assertEqual(snapshot["rows"][0]["status"], QUEUED)
        self.assertEqual((snapshot["phase"], snapshot["id"]), (QUEUED, job.id))

    def test_a_job_fails_when_it_or_a_step_ended_in_error(self):
        job = Ending()
        self.assertFalse(job.failed)
        job.rows[0]["status"] = ERROR
        self.assertTrue(job.failed)
        other = Ending()
        other._finish(ERROR, "x")
        self.assertTrue(other.failed)

    def test_a_crash_ends_a_job_that_had_not_and_leaves_one_that_had(self):
        job = Ending()
        job.crashed("boom")
        job.crashed("again")
        self.assertEqual(job.ended, [(ERROR, "boom")])

    def test_a_job_that_cannot_end_itself_is_still_ended_by_a_crash(self):
        job = Job("PN-1", "folder")   # no ``_finish``
        job.crashed("boom")
        self.assertEqual((job.phase, job.message), (ERROR, "boom"))

    def test_the_snapshot_carries_what_the_steps_came_to(self):
        job = Job("PN-1", "folder")
        job.rows = [job.row("A", "")]
        snapshot = job.snapshot()
        self.assertEqual(snapshot["counts"], {"update": 2})
        self.assertEqual([r["item"] for r in snapshot["rows"]], ["A"])


if __name__ == "__main__":
    unittest.main()
