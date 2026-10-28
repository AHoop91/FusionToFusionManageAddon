"""The states a job passes through, shared by the publish run and the send run."""

QUEUED, RUNNING, DONE, ERROR, CANCELLED = "queued", "running", "done", "error", "cancelled"
FINISHED = (DONE, ERROR, CANCELLED)

