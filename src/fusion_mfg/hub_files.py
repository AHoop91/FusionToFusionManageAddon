"""What browsing a Fusion hub's projects and folders gives back: the listing of a place, and the error a read can end in."""

from typing import Dict, List, NamedTuple


class HubFilesError(Exception):
    """A browse or read failed; the message is safe to show to the user."""


class Listing(NamedTuple):
    """What is inside a place in the hub: its folders and its files, each as ``{"id", "name"}``, by name."""

    folders: List[Dict[str, str]]
    files: List[Dict[str, str]]


def by_name(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """``entries`` sorted by name, ignoring case."""
    return sorted(entries, key=lambda e: e["name"].lower())
