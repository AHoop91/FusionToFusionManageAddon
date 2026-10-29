"""What a publish run and a send run share: their state, cancelling, and the snapshot the panels poll."""

import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..core.cancel import ADDIN, Cancelled, CancelToken
from ..core.logging_setup import get_logger
from .states import CANCELLED, DONE, ERROR, FINISHED, QUEUED, RUNNING

log = get_logger("publish_job")


class JobStopped(Exception):
    """A job's steps stop early for a reason the job expects, not a failure of its own: the message says why, and is what the job ends with."""


class JobState:
    """State of one job in the ``JobQueue``. Subclasses fill ``rows`` and ``total``, and define ``_steps`` and ``_finish``.

    ``work`` runs on the queue's worker thread; the panels read ``snapshot`` and call ``cancel`` from others, so what they share is changed
    under ``_lock`` (``done`` and ``total`` are counted by the subclass, which takes it for that).
    """

    kind = "job"
    sends = False   # does the job send to Fusion Manage
    stage = "items"   # what the job is on now, for the panel's progress text
    unreached = "Not finished: the job failed."   # detail of a row the job never got to

    def __init__(self, name: str, folder: str, token: Optional[CancelToken] = None) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.name, self.path = name, folder
        self.token = token or ADDIN.child(f"the {self.kind} run of {name}")   # what the job's reads are made under: ``cancel`` ends them
        self._lock = threading.Lock()
        self.phase = QUEUED   # queued -> running -> done | error | cancelled
        self.cancelled = False   # asked to stop: the worker reads it between steps, without the lock (a flag that only ever goes True)
        self.message = ""
        self.done = 0
        self.total = 0
        self.rows: List[Dict[str, Any]] = []   # one per step, for the Jobs window: queued -> running -> done | error | cancelled
        self.queued_at, self.started_at, self.finished_at = time.time(), 0.0, 0.0

    @staticmethod
    def row(item: str, description: str, root: bool = False) -> Dict[str, Any]:
        """A row of the Jobs window for one step, waiting its turn."""
        return {"item": item, "description": description, "root": root, "status": QUEUED, "detail": ""}

    @property
    def unlisted(self) -> bool:
        """Whether the job is left out of what the queue shows and counts (it stopped before it wrote anything, so there is nothing to look at,
        retry or clear). The panel that queued it still reads how it ended."""
        return False

    @property
    def failed(self) -> bool:
        """Did the job end in error, or has any of its steps?"""
        with self._lock:
            return self.phase == ERROR or any(row["status"] == ERROR for row in self.rows)

    def _start(self) -> bool:
        """Move to running; False if the job was cancelled while it waited."""
        with self._lock:
            if self.phase != QUEUED:
                return False
            self.phase = RUNNING
            self.started_at = time.time()
        return True

    def cancel(self) -> None:
        """Stop: a waiting job never starts, a running one stops after the step in flight, and the reads it has under way are ended (see ``token``).
        A job that has ended is left as it ended."""
        with self._lock:
            if self.phase in FINISHED:
                return
            self.cancelled = True
            waiting = self.phase == QUEUED
            if waiting:
                self.phase = CANCELLED   # in the same step as the look, so the worker cannot start it in between (``_start`` takes only a queued job)
        self.token.cancel()
        if waiting:
            self._finish(CANCELLED, "Cancelled.")

    def _set(self, **changes: Any) -> None:
        """Change attributes of the job together, under the lock. A name the job does not have is an error, not a new attribute."""
        with self._lock:
            unknown = [name for name in changes if not hasattr(self, name)]
            if unknown:
                raise AttributeError(f"{type(self).__name__} has no {', '.join(unknown)} to set")
            for name, value in changes.items():
                setattr(self, name, value)

    def _end(self, phase: str, message: str) -> None:
        """Mark the rows never reached or left unfinished, and the phase, together: a snapshot never shows the one without the other.
        Nothing is working once a job ends, so a row still ``running`` was cut short by what ended it."""
        with self._lock:
            for row in self.rows:
                if row["status"] in (QUEUED, RUNNING):
                    row["status"], row["detail"] = CANCELLED, "Cancelled." if self.cancelled else self.unreached
            self.phase, self.message, self.finished_at = phase, message, time.time()

    def _finish(self, phase: str, message: str) -> None:
        """End the job in ``phase`` with ``message``: whatever the subclass records of it, then ``_end``."""
        raise NotImplementedError

    def work(self) -> None:
        """Run the job, on the queue's worker thread: start it, do its steps, end it as they went."""
        if not self._start():   # cancelled while it waited
            return
        self._finish(*self._outcome())

    def _steps(self) -> None:
        """What the job does. Raises ``JobStopped`` to end early with a reason; a cancel ends it as cancelled, any other failure as an error."""
        raise NotImplementedError

    def _outcome(self) -> Tuple[str, str]:
        """Do the steps, and say how the job ended: ``(phase, message)``."""
        try:
            self._steps()
        except JobStopped as exc:
            return ERROR, str(exc)
        except Cancelled:   # a request the cancel ended (the add-in stopping does it too, with ``cancelled`` not set)
            return CANCELLED, "Cancelled."
        except Exception as exc:
            log.exception("The %s run %s failed", self.kind, self.id)
            return ERROR, str(exc) or type(exc).__name__
        return (CANCELLED, "Cancelled.") if self.cancelled else (DONE, "")

    def crashed(self, message: str) -> None:
        """End a job whose ``work`` raised, as an error, unless it had ended: a job left queued or running would be listed for ever, and a
        queued one would be taken again and again."""
        with self._lock:
            ended = self.phase in FINISHED
        if ended:
            return
        try:
            self._finish(ERROR, message)
        except Exception:   # the job's own ending failed (a manifest that cannot be written): it must still end, or the queue stops
            self._end(ERROR, message)

    def snapshot(self) -> Dict[str, Any]:
        """The job's state as the panels poll it: a copy, so the worker can go on changing the job."""
        with self._lock:
            return {"id": self.id, "kind": self.kind, "name": self.name, "phase": self.phase, "message": self.message,
                    "done": self.done, "total": self.total, "queued_at": self.queued_at,
                    "started_at": self.started_at, "finished_at": self.finished_at, "folder": self.path,
                    "counts": self._counts(), "sends": self.sends, "stage": self.stage, "rows": [dict(r) for r in self.rows]}

    def _counts(self) -> Dict[str, int]:
        """What the job's steps came to, by outcome (read with the lock held, so it must not take it)."""
        return {}
