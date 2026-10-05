"""The states a job passes through, shared by the publish run and the send run."""

import time

QUEUED, RUNNING, DONE, ERROR, CANCELLED = "queued", "running", "done", "error", "cancelled"
FINISHED = (DONE, ERROR, CANCELLED)


def time_now() -> float:
    return time.time()
