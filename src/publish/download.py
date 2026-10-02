"""Download of a signed url (the thumbnails)."""

import urllib.request


def download(url: str, timeout: int = 30) -> bytes:
    """GET a signed url (it carries its own access, so no authorisation header is sent)."""
    if not url.lower().startswith("https://"):
        raise ValueError("The thumbnail address is not https.")
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - https checked above
        return response.read()
