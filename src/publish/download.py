"""Download of a signed url (the thumbnails)."""

from ..core.http import OPENER


def download(url: str, timeout: int = 30) -> bytes:
    """GET a signed url (it carries its own access, so no authorisation header is sent)."""
    if not url.lower().startswith("https://"):
        raise ValueError("The thumbnail address is not https.")
    with OPENER.open(url, timeout=timeout) as response:
        return response.read()
