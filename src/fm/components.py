"""Find the Components workspace item that stands for a part, to fill an item's component linking field.

The field is a picklist whose options are the items of the Components workspace (``CUSTOM_LOOKUP_WS_COMPONENTS_...``),
so the lookup is asked for the options whose text matches the item number. The option's ``link`` is what the field takes.
"""

import re
from typing import Dict, List, Tuple
from urllib.parse import quote

from ..core.logging_setup import get_logger
from .client import LOOKUPS, WORKSPACES, FmClient, last_segment

log = get_logger("fm.components")

_URN = re.compile(r"\.(\d+)\.(\d+)\s*$")   # urn:adsk.plm:tenant.workspace.item:TENANT.<workspace>.<item>
_URL = re.compile(r"workspaces/(\d+)/items/(\d+)")
CANDIDATES = 25   # options asked for when searching by number


def _matches(title: str, number: str) -> bool:
    """The option is the number alone, or starts with it and then a separator (``PN-1 - Axle``), not a longer number (``PN-10``)."""
    title, number = title.strip().casefold(), number.strip().casefold()
    return title == number or bool(re.match(re.escape(number) + r"(?![0-9a-z])", title))


def manage_link(urn: str, url: str) -> str:
    """The API link ``/api/v3/workspaces/<workspace>/items/<item>`` of the item a Data Model component is linked to ("" if neither says)."""
    match = _URN.search(urn) or _URL.search(url)
    if not match:
        return ""
    first, second = match.groups()
    return f"{WORKSPACES}/{first}/items/{second}"


class ComponentService:
    """Finds components in the picklist of the component linking field."""

    def __init__(self, client: FmClient) -> None:
        self._client = client

    def find(self, lookup: str, number: str) -> Tuple[str, str]:
        """``(link, "")`` of the one option for this item number, else ``("", reason)``."""
        if not number:
            return "", "The item has no number to look up."
        data = self._client.get_json(f"{LOOKUPS}/{lookup}?offset=0&limit={CANDIDATES}&filter={quote(number)}&asc=&desc=")
        rows = data.get("items") if isinstance(data, dict) else None
        options: List[Dict[str, str]] = [{"link": str(r["link"]), "title": str(r.get("title") or ""), "version": str(r.get("version") or "")}
                                         for r in rows if isinstance(r, dict) and r.get("link")] if isinstance(rows, list) else []
        hits = [o for o in options if _matches(o["title"], number)]
        log.debug("Component options for %s: %s", number, [o["title"] for o in options])
        if len(hits) == 1:
            return hits[0]["link"], ""
        if not hits:
            return "", f"No component matching {number} in {lookup} ({len(options)} option(s) came back for it)."
        return "", f"{len(hits)} components match {number}: " + ", ".join(f"{o['title']} {o['version']} ({last_segment(o['link'])})" for o in hits[:5]) + " - the Data Model has to say which"
