"""The Fusion Manage tenant: what a valid one looks like, and how to find it from a linked item.

The tenant decides which host the access token is sent to, so it is only ever used as a plain host name label.
"""

import re
from urllib.parse import urlparse

FM_HOST_SUFFIX = ".autodeskplm360.net"
_TENANT = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_URN_TENANT = re.compile(r"[:.]([^.:]+)\.\d+\.\d+$")   # urn:adsk.plm:tenant.workspace.item:TENANT.<workspace>.<item>


def tenant_code(name: object) -> str:
    """The tenant ``name`` stands for, lower case ("" when it is not a plain host name label, so it cannot redirect a request)."""
    text = str(name or "").strip().lower()
    return text if _TENANT.fullmatch(text) else ""


def tenant_of_link(urn: str, url: str) -> str:
    """The tenant of a Fusion Manage item from its address (``https://TENANT.autodeskplm360.net/...``) or, failing that, its urn."""
    host = (urlparse(url).hostname or "").lower() if url else ""
    if host.endswith(FM_HOST_SUFFIX):
        return tenant_code(host[:-len(FM_HOST_SUFFIX)])
    found = _URN_TENANT.search(urn or "")
    return tenant_code(found.group(1)) if found else ""
