"""How long to wait before trying a request again.

A server that is busy or throttling is not helped by clients that all come back at the same moment, so the wait grows with each
attempt and is spread at random (jitter). When the server says how long to wait (a ``Retry-After`` header, usually with a 429 or a 503),
that is the wait, since only it knows when it will be ready.
"""

import random
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Mapping, Optional

BASE_SECONDS = 1.0   # the wait before the second try, before jitter; it doubles for each try after
CAP_SECONDS = 20.0   # the wait never grows past this
MAX_RETRY_AFTER_SECONDS = 30.0   # a server that asks for longer than this is not waited for: the person using the add-in would be left waiting
AFTER_JITTER_SECONDS = 1.0   # added to a wait the server asked for, so clients it throttled together do not return together


def retry_after(headers: Optional[Mapping[str, str]], now: Optional[datetime] = None) -> Optional[float]:
    """Seconds the ``Retry-After`` header asks for: whole seconds, or an HTTP date (RFC 9110). None when there is none or it is not either."""
    value = next((v for k, v in (headers or {}).items() if k.lower() == "retry-after"), "").strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


def delay(attempt: int, asked: Optional[float] = None) -> Optional[float]:
    """Seconds to wait after try number ``attempt`` (1 for the first) failed, or None when the server asked (``asked``) for longer than
    ``MAX_RETRY_AFTER_SECONDS``, which is a reason to give up rather than wait.

    Without a request from the server the wait is exponential with jitter: half of it fixed, half random, so it is never near zero.
    """
    if asked is not None:
        return None if asked > MAX_RETRY_AFTER_SECONDS else asked + random.uniform(0, AFTER_JITTER_SECONDS)
    ceiling = min(CAP_SECONDS, BASE_SECONDS * 2 ** (attempt - 1))
    return ceiling / 2 + random.uniform(0, ceiling / 2)
