"""Whether the file attached in Fusion Manage is as recent as what is open in Fusion.

The attached file was made from a saved version of the design (or drawing); if a version was saved after the file was uploaded, the
file no longer shows the latest design. This compares the two times and says so in words for the Export window. It holds no Fusion
objects: Fusion's side is read by ``design_history`` and passed in as a ``source``.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

CURRENT, STALE, UNSAVED, UNKNOWN = "current", "stale", "unsaved", "unknown"   # the states an attachment can be in
_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z")


def parse_stamp(text: Any) -> Optional[datetime]:
    """The moment ``text`` (an ISO 8601 stamp, as Fusion Manage writes them) names, in UTC; None when it names none. No zone means UTC."""
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = raw[:-1] + "+0000" if raw.endswith(("Z", "z")) else raw
    for form in _FORMATS:
        try:
            parsed = datetime.strptime(raw, form)
        except ValueError:
            continue
        return parsed.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _when(moment: datetime) -> str:
    """A moment as the user's computer writes it: "13 Oct 2026 14:05"."""
    return moment.astimezone().strftime("%d %b %Y %H:%M")


def compare(uploaded: Any, source: Dict[str, Any]) -> Dict[str, str]:
    """Whether a file uploaded at ``uploaded`` (a stamp) is as recent as ``source``: ``saved`` (when the latest version was saved, as a Unix
    time, or None) in ``saved_in`` (which document: "The design Universal Joint"), ``unsaved`` (changes were made since) in ``unsaved_in`` and
    ``reason`` (why ``saved`` is None). The answer is a ``state``, a ``message`` and, when the last save is known, ``modified`` (when, as an ISO stamp).

    A file uploaded after the latest save is current: an upload always follows the save it was made from, so no allowance is made for clocks.
    """
    if source.get("unsaved"):
        return {"state": UNSAVED, "message": f"{source.get('unsaved_in') or 'The open document'} has changes that are not saved, so this export may differ from the attached file."}
    saved, what = source.get("saved"), source.get("saved_in") or "The document"
    if saved is None:
        return {"state": UNKNOWN, "message": source.get("reason") or "When the document was last saved could not be read."}
    uploaded_at = parse_stamp(uploaded)
    if uploaded_at is None:
        return {"state": UNKNOWN, "message": "When the attached file was uploaded could not be read."}
    saved_at = datetime.fromtimestamp(saved, timezone.utc)
    if uploaded_at >= saved_at:
        return {"state": CURRENT, "modified": saved_at.isoformat(), "message": f"Uploaded {_when(uploaded_at)}, after the last save of {what[:1].lower() + what[1:]} on {_when(saved_at)}."}
    return {"state": STALE, "modified": saved_at.isoformat(), "message": f"{what} was saved {_when(saved_at)}, after this file was uploaded on {_when(uploaded_at)}."}
