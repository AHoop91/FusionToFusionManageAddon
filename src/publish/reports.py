"""The text of the message boxes that say how a publish and a send ended."""

from typing import Any, List

from .runner import SENT, PublishRun
from .states import ERROR

MAX_LISTED = 5   # failed items named in a message box; the Job Queue lists them all


def _requests(run: PublishRun, method: str) -> int:
    """How many items the run wrote a request of this kind for (POST creates an item, PATCH updates one)."""
    artifact = SENT if run.sends else "item request"
    return sum(1 for entry in list(run.folder.entries)
               if entry["artifact"] == artifact and entry["status"] == "ok" and entry["detail"].startswith(method + " "))


def _failures(run: Any) -> List[str]:
    """The failed steps of a run, each on a line, as many as a message box names."""
    failed = [row for row in run.rows if row["status"] == "error"]
    lines = [f"  - {row['item']}: {(row['detail'] or 'Failed.')[:160]}" for row in failed[:MAX_LISTED]]
    if len(failed) > MAX_LISTED:
        lines.append(f"  - and {len(failed) - MAX_LISTED} more")
    return lines


def publish_report(run: PublishRun) -> str:
    """The text of the message box for a run that ended: how many items it processed, created and updated, and what failed."""
    if run.phase == ERROR:
        return f"Publish of {run.name} could not be completed.\n\nReason: {run.message}"
    failed = sum(1 for row in run.rows if row["status"] == "error")
    lines = [f"Publish of {run.name} completed with errors: {failed} step(s) failed." if failed else f"Publish of {run.name} completed successfully.", "",
             *_failures(run), *([""] if failed else []),
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


def send_report(run: Any) -> str:
    """The text of the message box for a send that ended."""
    if run.phase == ERROR:
        return f"Sending {run.name} could not be completed.\n\nReason: {run.message}"
    failed = sum(1 for row in run.rows if row["status"] == "error")
    if not failed:
        return f"{run.name} was sent to Fusion Manage.\n\nSteps completed: {run.done} of {run.total}"
    return "\n".join([f"Sending {run.name} finished with errors: {failed} of {run.total} step(s) failed.", "", *_failures(run), "",
                      "Use Retry on the job to send them again: what Fusion Manage accepted is skipped."])
