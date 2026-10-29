"""The states a job passes through, shared by the publish run and the send run.

A job's phase and each of its rows (one per step) use the same words: waiting, working, then how it ended. The panels read the words as
they are written here (``publish-jobs.js``), so they are not changed without changing it.
"""

QUEUED, RUNNING, DONE, ERROR, CANCELLED = "queued", "running", "done", "error", "cancelled"
ACTIVE = (QUEUED, RUNNING)   # not ended yet
FINISHED = (DONE, ERROR, CANCELLED)   # the ways it can end

