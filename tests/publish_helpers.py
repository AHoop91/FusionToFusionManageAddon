"""Publish folders and runs for tests that send to the fake tenant (``fake_manage``).

The requests of a folder are made by the production code (``bom_requests``) from operations, as the panel resolves them, so a test
exercises the real request shapes and markers, not hand-written ones. Only item requests are written here: a body with the item number as
``n``, which is what the fake tenant reads (the real field mapping is the runner's, and is covered by its own tests).
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from src.fm.client import FmClient
from src.publish.bom_requests import bom_requests
from src.publish.sender import SendRun, load_plan
from tests.fake_manage import WORKSPACE, FakeManage


def create(number: str) -> Dict[str, Any]:
    return {"method": "POST", "url": f"/api/v3/workspaces/{WORKSPACE}/items", "body": {"sections": [], "n": number}}


def update(item_id: str) -> Dict[str, Any]:
    return {"method": "PATCH", "url": f"/api/v3/workspaces/{WORKSPACE}/items/{item_id}", "body": {"sections": []}}


def add(parent: str, number: str, sequence: int, quantity: str = "1") -> Dict[str, Any]:
    return {"op": "add", "parent": parent, "number": number, "sequence": sequence, "quantity": quantity}


def remove(parent: str, number: str, sequence: int, edge: str = "") -> Dict[str, Any]:
    return {"op": "remove", "parent": parent, "number": number, "sequence": sequence, "edge": edge}


def renumber(parent: str, number: str, from_sequence: int, sequence: int, edge: str = "") -> Dict[str, Any]:
    return {"op": "renumber", "parent": parent, "number": number, "from_sequence": from_sequence, "sequence": sequence, "edge": edge}


def requantify(parent: str, number: str, sequence: int, quantity: str, edge: str = "") -> Dict[str, Any]:
    return {"op": "update", "parent": parent, "number": number, "sequence": sequence, "quantity": quantity, "edge": edge}


def write_folder(root: str, items: Dict[str, Dict[str, Any]], operations: List[Dict[str, Any]], known_ids: Optional[Dict[str, str]] = None,
                 workspace_id: str = WORKSPACE) -> None:
    """A publish folder as a run leaves it: ``items`` is number -> its request; ``operations`` become each parent's requests."""
    manifest: Dict[str, Any] = {"root": next(iter(items), "R"), "workspace_id": workspace_id, "tenant": "acme", "items": {}}
    for number, request in items.items():
        relative = os.path.join("items", f"i{len(manifest['items'])}", "item.request.json")
        os.makedirs(os.path.join(root, os.path.dirname(relative)), exist_ok=True)
        with open(os.path.join(root, relative), "w", encoding="utf-8") as handle:
            json.dump(request, handle)
        manifest["items"][number] = {"id": (known_ids or {}).get(number, ""), "state": "new", "request": relative}
    os.makedirs(os.path.join(root, "bom"), exist_ok=True)
    for index, (parent, requests) in enumerate(bom_requests(workspace_id, operations).items()):
        with open(os.path.join(root, "bom", f"p{index}.bom.request.json"), "w", encoding="utf-8") as handle:
            json.dump({"parent": parent, "requests": requests}, handle)
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)


def send(root: str, tenant: FakeManage, client: Optional[FmClient] = None) -> SendRun:
    """Send the folder as the Job Queue's retry does, to the fake tenant, and return the finished run."""
    with tenant.serving():
        run = SendRun(root, load_plan(root), client or tenant.client())
        run.work()
    return run


def end_state(tenant: FakeManage) -> Dict[str, Any]:
    """What a person would see in Fusion Manage: every item number with how many items carry it, and each parent's lines."""
    numbers: Dict[str, int] = {}
    for item in tenant.items.values():
        numbers[item["number"]] = numbers.get(item["number"], 0) + 1
    lines = {item["number"]: tenant.lines_of(item["number"]) for item in tenant.items.values() if numbers[item["number"]] == 1}
    return {"numbers": numbers, "lines": lines}


def edges_of(tenant: FakeManage, parent: str) -> Dict[Tuple[str, int], str]:
    """``(child number, sequence)`` -> edge id of the lines under a parent, to name them in operations the way a BOM read does."""
    parent_id = tenant.id_of(parent)
    return {(tenant.items[l["item"]]["number"], l["sequence"]): l["edge"] for l in tenant.bom[parent_id]}
