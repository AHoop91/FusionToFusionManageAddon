"""Download of a signed url (the thumbnails)."""

from typing import Optional

from ..core.cancel import CancelToken
from ..core.http import open_url


def download(url: str, timeout: int = 30, cancel: Optional[CancelToken] = None) -> bytes:
    """GET a signed url (it carries its own access, so no authorisation header is sent). ``cancel`` ends it (see ``core.cancel``)."""
    if not url.lower().startswith("https://"):
        raise ValueError("The thumbnail address is not https.")
    with open_url(url, timeout, cancel) as response:
        return response.read()
