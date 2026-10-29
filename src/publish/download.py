"""Download of a signed url (the thumbnails)."""

from typing import Optional

from ..core.cancel import CancelToken
from ..core.http import open_url

TIMEOUT = 30   # seconds a thumbnail may take
MAX_BYTES = 20 * 1024 * 1024   # a thumbnail is a small picture: anything bigger than this is not one, and is not read into memory


def download(url: str, timeout: float = TIMEOUT, cancel: Optional[CancelToken] = None) -> bytes:
    """GET a signed url (it carries its own access, so no authorisation header is sent).

    Raises ``ValueError`` for an address that is not https or an answer bigger than ``MAX_BYTES``, ``Cancelled`` when ``cancel`` (the add-in's
    own when not given) is cancelled; a network or HTTP failure is raised as ``open_url`` raises it."""
    if not isinstance(url, str) or not url.lower().startswith("https://"):
        raise ValueError("The thumbnail address is not https.")
    with open_url(url, timeout, cancel) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"The thumbnail is bigger than {MAX_BYTES // (1024 * 1024)} MB.")
    return data
