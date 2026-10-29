"""The text of the message boxes that say how a publish and a send ended."""

from typing import List

from .job_state import JobState
from .runner import ITEM_REQUEST, SENT, PublishRun
from .sender import CUT_OFF, SendRun
from .states import CANCELLED, ERROR
from .writer import OK

MAX_LISTED = 5   # failed items named in a message box; the Job Queue lists them all
DETAIL_CHARS = 160   # of a failure's reason shown beside its item


def _requests(run: PublishRun, method: str) -> int:
    """How many items the run wrote a request of this kind for (POST creates an item, PATCH updates one)."""
    artifact = SENT if run.sends else ITEM_REQUEST
    return sum(1 for entry in list(run.folder.entries)
               if entry["artifact"] == artifact and entry["status"] == OK and entry["detail"].startswith(method + " "))


def _count(run: JobState, status: str) -> int:
    return sum(1 for row in run.rows if row["status"] == status)


def _listed(names: List[str]) -> List[str]:
    """``names`` one to a line, as many as a message box names, and how many more there are."""
    lines = [f"  - {name}" for name in names[:MAX_LISTED]]
    if len(names) > MAX_LISTED:
        lines.append(f"  - and {len(names) - MAX_LISTED} more")
    return lines


def _failures(run: JobState) -> List[str]:
    """The failed steps of a run, each on a line with its reason."""
    return _listed([f"{row['item']}: {(row['detail'] or 'Failed.')[:DETAIL_CHARS]}" for row in run.rows if row["status"] == ERROR])


def cut_off(run: JobState) -> List[str]:
    """The steps a cancel ended while they were being sent: Fusion Manage may or may not have done them."""
    return [row["item"] for row in run.rows if row["detail"] == CUT_OFF]


def _cancelled_report(run: JobState, what: str) -> str:
    """The message box for a run that was cancelled: how far it got, and the requests that were cut off and may have been done."""
    lines = [f"{what} {run.name} was cancelled.", "", f"Steps completed before it stopped: {run.done} of {run.total}."]
    cut = cut_off(run)
    if cut:
        lines += ["", "These were being sent when it stopped. Fusion Manage may or may not have done them:", *_listed(cut), "",
                  "Use Retry on the job to send the rest: it checks what was done first, and sends only what was not."]
    return "\n".join(lines)


def _reason(run: JobState) -> str:
    return run.message or "no reason was given"


def publish_report(run: PublishRun) -> str:
    """The text of the message box for a run that ended: how many items it processed, created and updated, and what failed."""
    if run.phase == ERROR:
        return f"Publish of {run.name} could not be completed.\n\nReason: {_reason(run)}"
    if run.phase == CANCELLED:
        return _cancelled_report(run, "Publish of")
    failed = _count(run, ERROR)
    headline = f"Publish of {run.name} completed with errors: {failed} step(s) failed." if failed else f"Publish of {run.name} completed successfully."
    lines = [headline, "", *_failures(run), *([""] if failed else []),
             f"Total Items Processed: {run.done}",
             f"Total Items Created: {_requests(run, 'POST')}",
             f"Total Items Updated: {_requests(run, 'PATCH')}", ""]
    if run.sends:
        if failed:   # a run that went through has its files removed: only a failed one keeps them, for Retry
            lines.append(f"The files are in {run.folder.path}")
            lines.append("Open the Job Queue for the reason of each failure. Use Retry on the job to send the failed requests again: what was accepted is skipped.")
    else:
        lines.append("The requests were written for review. Nothing has been sent to Fusion Manage yet.")
        if failed:
            lines.append("Open the Job Queue for the full reason of each failure.")
    return "\n".join(lines)


def send_report(run: SendRun) -> str:
    """The text of the message box for a send that ended."""
    if run.phase == ERROR:
        return f"Sending {run.name} could not be completed.\n\nReason: {_reason(run)}"
    if run.phase == CANCELLED:
        return _cancelled_report(run, "Sending")
    failed = _count(run, ERROR)
    if not failed:
        return f"{run.name} was sent to Fusion Manage.\n\nSteps completed: {run.done} of {run.total}"
    return "\n".join([f"Sending {run.name} finished with errors: {failed} of {run.total} step(s) failed.", "", *_failures(run), "",
                      "Use Retry on the job to send them again: what Fusion Manage accepted is skipped."])
