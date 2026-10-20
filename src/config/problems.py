"""A problem found in the settings, with where it is in the settings panel."""

from typing import Any, Dict, List


class Problem(str):
    """The text of a problem. It is a string, so it joins and compares as one; ``where`` tells the panel which field to mark.

    ``where`` is ``{"input": id}`` for a field of the Connection tab, or ``{"workspace": kind, "area": ..., "row": n, "part": ...}`` for
    a workspace's settings: ``area`` is ``id``, ``mapping``, ``static``, ``component`` or ``mappings`` (the list as a whole), ``row`` counts
    from 0 within its list and ``part`` is ``source`` or ``field``.
    """

    where: Dict[str, Any]

    def __new__(cls, message: str, **where: Any) -> "Problem":
        problem = super().__new__(cls, message)
        problem.where = where
        return problem


def problem_payload(problems: List[str]) -> List[Dict[str, Any]]:
    """The problems as the panel receives them: the message and where it is (empty for a problem with no place)."""
    return [{"message": str(p), "where": getattr(p, "where", {})} for p in problems]
