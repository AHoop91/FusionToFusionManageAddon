"""The text of the message boxes that say how a publish and a send ended."""

from typing import List

from ..core.i18n import t
from .job_state import JobState
from .runner import ITEM_REQUEST, SENT, PublishRun
from .sender import SendRun, cut_off_text
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
        lines.append(t("run.report_more", count=len(names) - MAX_LISTED))
    return lines


def _failures(run: JobState) -> List[str]:
    """The failed steps of a run, each on a line with its reason."""
    return _listed([f"{row['item']}: {(row['detail'] or t('run.report_failed'))[:DETAIL_CHARS]}" for row in run.rows if row["status"] == ERROR])


def cut_off(run: JobState) -> List[str]:
    """The steps a cancel ended while they were being sent: Fusion Manage may or may not have done them."""
    return [row["item"] for row in run.rows if row["detail"] == cut_off_text()]


def _cancelled_report(run: JobState, headline: str) -> str:
    """The message box for a run that was cancelled: how far it got, and the requests that were cut off and may have been done."""
    lines = [headline, "", t("run.report_steps_before_stop", done=run.done, total=run.total)]
    cut = cut_off(run)
    if cut:
        lines += ["", t("run.report_cut_off"), *_listed(cut), "", t("run.report_retry_rest")]
    return "\n".join(lines)


def _reason(run: JobState) -> str:
    return run.message or t("run.report_no_reason")


def publish_report(run: PublishRun) -> str:
    """The text of the message box for a run that ended: how many items it processed, created and updated, and what failed."""
    if run.phase == ERROR:
        return t("run.report_publish_error", name=run.name) + "\n\n" + t("run.report_reason", reason=_reason(run))
    if run.phase == CANCELLED:
        return _cancelled_report(run, t("run.report_publish_cancelled", name=run.name))
    failed = _count(run, ERROR)
    headline = (t("run.report_publish_errors", name=run.name, failed=failed) if failed
                else t("run.report_publish_success", name=run.name))
    lines = [headline, "", *_failures(run), *([""] if failed else []),
             t("run.report_total_processed", count=run.done),
             t("run.report_total_created", count=_requests(run, "POST")),
             t("run.report_total_updated", count=_requests(run, "PATCH")), ""]
    if run.sends:
        if failed:   # a run that went through has its files removed: only a failed one keeps them, for Retry
            lines.append(t("run.report_files_in", path=run.folder.path))
            lines.append(t("run.report_send_failed_hint"))
    else:
        lines.append(t("run.report_written_for_review"))
        if failed:
            lines.append(t("run.report_full_reason_hint"))
    return "\n".join(lines)


def send_report(run: SendRun) -> str:
    """The text of the message box for a send that ended."""
    if run.phase == ERROR:
        return t("run.report_send_error", name=run.name) + "\n\n" + t("run.report_reason", reason=_reason(run))
    if run.phase == CANCELLED:
        return _cancelled_report(run, t("run.report_send_cancelled", name=run.name))
    failed = _count(run, ERROR)
    if not failed:
        return t("run.report_sent", name=run.name) + "\n\n" + t("run.report_steps_completed", done=run.done, total=run.total)
    return "\n".join([t("run.report_send_errors", name=run.name, failed=failed, total=run.total), "", *_failures(run), "",
                      t("run.report_retry_failed")])
