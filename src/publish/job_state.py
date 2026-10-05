"""What a publish run and a send run share: their state, cancelling, and the snapshot the panels poll."""

import threading
import uuid
from typing import Any, Dict, List

from .states import CANCELLED, QUEUED, RUNNING, time_now


class JobState:
    """State of one job in the ``JobQueue``. Subclasses fill ``rows`` and ``total``, and define ``work`` and ``_finish``."""

    kind = "job"
    sends = False   # does the job send to Fusion Manage
    stage = "items"
    unreached = "Not finished: the job failed."   # detail of a row the job never got to

    def __init__(self, name: str, folder: str) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.name, self.path = name, folder
        self._lock = threading.Lock()
        self.phase = QUEUED   # queued -> running -> done | error | cancelled
        self.cancelled = False
        self.message = ""
        self.current = ""
        self.done = 0
        self.total = 0
        self.rows: List[Dict[str, Any]] = []   # one per step, for the Jobs window: queued -> running -> done | error | cancelled
        self.queued_at, self.started_at, self.finished_at = time_now(), 0.0, 0.0

    @staticmethod
    def row(item: str, description: str, root: bool = False) -> Dict[str, Any]:
        return {"item": item, "description": description, "root": root, "status": QUEUED, "detail": ""}

    def _start(self) -> bool:
        """Move to running; False if the job was cancelled while it waited."""
        with self._lock:
            if self.phase != QUEUED:
                return False
            self.phase = RUNNING
            self.started_at = time_now()
        return True

    def cancel(self) -> None:
        """Stop: a waiting job never starts, a running one stops after the step in flight."""
        with self._lock:
            self.cancelled = True
            waiting = self.phase == QUEUED
        if waiting:
            self._finish(CANCELLED, "Cancelled.")

    def _set(self, **changes: Any) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(self, name, value)

    def _end(self, phase: str, message: str) -> None:
        """Mark the rows never reached, then the phase."""
        with self._lock:
            for row in self.rows:
                if row["status"] == QUEUED:
                    row["status"], row["detail"] = CANCELLED, "Cancelled." if self.cancelled else self.unreached
        self._set(phase=phase, message=message, current="", finished_at=time_now())

    def _finish(self, phase: str, message: str) -> None:
        raise NotImplementedError

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"id": self.id, "kind": self.kind, "name": self.name, "phase": self.phase, "message": self.message,
                    "current": self.current, "done": self.done, "total": self.total, "queued_at": self.queued_at,
                    "started_at": self.started_at, "finished_at": self.finished_at, "folder": self.path,
                    "counts": self._counts(), "sends": self.sends, "stage": self.stage, "rows": [dict(r) for r in self.rows]}

    def _counts(self) -> Dict[str, int]:
        return {}
