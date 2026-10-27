"""The queue of publish runs: one worker thread takes them in order, so Publish returns at once.

Runs only use the network and the disk (see ``runner``), so the queue never blocks Fusion and the
user keeps working, even in another design. The worker thread starts when a run is added and ends
when none is waiting.
"""

import threading
from typing import Any, Callable, Dict, List, Optional

from ..core.logging_setup import get_logger
from .job_state import JobState
from .run_files import remove_run
from .states import DONE, ERROR, FINISHED, QUEUED, RUNNING

log = get_logger("publish_queue")


class JobQueue:
    """Publish runs in the order they were added; finished ones stay listed until cleared."""

    def __init__(self, on_change: Optional[Callable[[], None]] = None,
                 on_finished: Optional[Callable[[JobState], None]] = None, files_root: Optional[str] = None) -> None:
        self._files_root = files_root   # the only folder whose run folders may be removed (see ``run_files``); None removes nothing
        self._on_change = on_change   # called (from any thread) whenever the state of the queue may have changed
        self._on_finished = on_finished   # called on the worker thread when a run has ended
        self._runs: List[JobState] = []
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None

    def add(self, run: JobState) -> None:
        with self._lock:
            self._runs = [r for r in self._runs if not self._clean(r)]   # the runs that ended clean were kept for the panel that queued them
            self._runs.append(run)
            if self._worker is None:
                self._worker = threading.Thread(target=self._loop, name="MfgToFm_PublishQueue", daemon=True)
                self._worker.start()
        log.info("Publish run %s queued: %s", run.id, run.name)
        self._changed()

    def replace(self, old: JobState, new: JobState) -> None:
        """Queue ``new`` in place of the finished run ``old`` (a retry), so the failure is not listed twice."""
        with self._lock:
            if old in self._runs:
                self._runs.remove(old)
        self.add(new)

    def get(self, run_id: str) -> Optional[JobState]:
        with self._lock:
            return next((r for r in self._runs if r.id == run_id), None)

    def cancel(self, run_id: str) -> None:
        run = self.get(run_id)
        if run:
            run.cancel()
            self._changed()

    def clear_finished(self) -> None:
        """Forget the finished runs, and remove their files: a run that is no longer listed cannot be retried."""
        with self._lock:
            cleared = [r for r in self._runs if r.phase in FINISHED]
            self._runs = [r for r in self._runs if r.phase not in FINISHED]
        for run in cleared:
            self._remove_files(run)
        self._changed()

    def state(self) -> str:
        """'running' while a run waits or works, else 'error' while a listed run failed, else 'idle'."""
        with self._lock:
            runs = list(self._runs)
        if any(r.phase in (QUEUED, RUNNING) for r in runs):
            return "running"
        failed = any(r.phase == ERROR or any(row["status"] == "error" for row in r.rows) for r in runs if not r.unlisted)
        return "error" if failed else "idle"

    def snapshots(self) -> List[Dict[str, Any]]:
        """Every run, oldest first; a waiting run also says its place in the queue."""
        with self._lock:
            runs = list(self._runs)
        place = 0
        result = []
        for run in runs:
            snap = run.snapshot()
            if snap["phase"] == QUEUED:
                place += 1
                snap["place"] = place
            result.append(snap)
        return result

    def _loop(self) -> None:
        while True:
            with self._lock:
                run = next((r for r in self._runs if r.phase == QUEUED), None)
                if run is None:
                    self._worker = None
                    return
            self._changed()
            try:
                run.work()
            except Exception:   # work reports its own failures; this only keeps the queue alive
                log.exception("Publish run %s crashed", run.id)
            self._finished(run)
            self._changed()

    def _finished(self, run: JobState) -> None:
        if self._on_finished:
            try:
                self._on_finished(run)
            except Exception:   # a failed notification must not stop the queue
                log.exception("Reporting run %s failed", run.id)
        if self._clean(run):   # everything was sent: no retry will want its files. A failed or cancelled run keeps them until it is cleared
            self._remove_files(run)

    def _remove_files(self, run: JobState) -> None:
        """Remove the folder of a run, if it is a run folder inside the files root."""
        if run.path and remove_run(self._files_root, run.path):
            log.info("Removed the files of run %s", run.id)

    def _changed(self) -> None:
        if self._on_change:
            try:
                self._on_change()
            except Exception:   # a failed notification must not stop the queue
                log.exception("Reporting the state of the queue failed")

    @staticmethod
    def _clean(run: JobState) -> bool:
        """A run that finished with every item done, or that stopped before writing anything, has nothing left to show once the panel has seen how it ended; failed or cancelled ones stay until cleared.

        It is forgotten when the next run is added, not when it ends: the panel that queued it is still reading its last state."""
        return run.unlisted or (run.phase == DONE and not any(row["status"] != "done" for row in run.rows))
