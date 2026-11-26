"""A stateful stand-in for Fusion Manage, placed below ``FmClient`` (at ``open_url``), for tests of publishing.

What it is: an in-memory tenant with items (id, number, version) and the Bill of Materials lines of each, that answers the
requests a publish makes in the shapes the code reads (search results, ``Location`` on a create, the item's ``urn`` and ``version``). The
real ``FmClient`` runs on top of it, so retries, ``Retry-After``, ``outcome_unknown`` and header parsing are the real ones.

What it is not: Fusion Manage. The shapes are the ones the production code reads, taken from the other tests and ``dev/`` notes, not
checked against a live tenant. Nothing here proves a request is accepted by the real service.

Faults are injected per request: ``fail(match, ...)`` makes the Nth request that matches fail before or after the server did the work, so
a test can model a lost answer (done, but no answer) and a lost request (not done). ``on_request`` lets a test change the tenant between
two requests, which is how another user's edit is modelled, and make requests meet at a barrier to force an interleaving.
"""

import io
import json
import re
import threading
import urllib.error
import urllib.parse
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from unittest import mock

from src.config.models import ConnectionSettings
from src.core.cancel import CancelToken
from src.fm import client as client_module
from src.fm.client import FmClient
from src.fm.items import collect_values

WORKSPACE = "57"
TENANT = "ACME"
NUMBER_FIELD = "NUMBER"   # the field the tests map the item number to
SECTION = f"/api/v3/workspaces/57/sections/1"
ITEMS = re.compile(rf"^/api/v3/workspaces/{WORKSPACE}/items$")
ITEM = re.compile(rf"^/api/v3/workspaces/{WORKSPACE}/items/(\d+)$")
BOM_ITEMS = re.compile(rf"^/api/v3/workspaces/{WORKSPACE}/items/(\d+)/bom-items$")
BOM_ITEM = re.compile(rf"^/api/v3/workspaces/{WORKSPACE}/items/(\d+)/bom-items/(\d+)$")
ITEM_NUMBER_IN_QUERY = re.compile(r'itemDescriptor="([^"]*)"')
ITEM_IN_LINK = re.compile(r"/items/(\d+)")


class Answer:
    """What ``open_url`` gives: a response that is a context manager."""

    def __init__(self, status: int = 200, body: Any = None, headers: Optional[Dict[str, str]] = None) -> None:
        self.status = status
        self._body = b"" if body is None else json.dumps(body).encode("utf-8")
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "Answer":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


def refusal(code: int, body: str = "", headers: Optional[Dict[str, str]] = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "refused", headers or {}, io.BytesIO(body.encode("utf-8")))


class Fault:
    """One fault: the ``nth`` request (1 is the first) whose ``method`` and path contain ``match`` fails.

    ``after`` False: the request is lost on the way, the server did nothing. True: the server did the work and the answer was lost.
    ``error`` is raised to the client: an ``OSError`` for no answer, or an ``HTTPError`` for a refusal.
    """

    def __init__(self, match: str, error: BaseException, nth: int = 1, after: bool = False, times: int = 1, writes_only: bool = False) -> None:
        self.match, self.error, self.after, self.nth, self.times, self.writes_only = match, error, after, nth, times, writes_only
        self.seen = 0

    def hits(self, text: str) -> bool:
        if self.match not in text or (self.writes_only and text.startswith("GET ")):
            return False
        self.seen += 1
        return self.nth <= self.seen < self.nth + self.times


class FakeManage:
    """The tenant. Every method that changes it holds one lock, so concurrent requests are as safe as a real server's."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.items: Dict[str, Dict[str, Any]] = {}   # id -> {"number", "version"}
        self.bom: Dict[str, List[Dict[str, Any]]] = {}   # parent id -> [{"edge", "item", "sequence", "quantity"}]
        self.log: List[Tuple[str, str, Any]] = []   # every request that reached the server (method, path, body), in order
        self.faults: List[Fault] = []
        self.on_request: Optional[Callable[[str, str, Any], None]] = None   # called before the server does the work of a request
        self.on_done: Optional[Callable[[str, str, Any], None]] = None   # called after it did, before the answer is given
        self._next_item = 1000
        self._next_edge = 5000
        self._creating = threading.Lock()

    # ---- Setting up and reading the end state ---------------------------------------------------------------

    def add_item(self, number: str, version: str = "[REV:w]") -> str:
        with self.lock:
            self._next_item += 1
            item_id = str(self._next_item)
            self.items[item_id] = {"number": number, "version": version, "fields": {NUMBER_FIELD: number}}
            self.bom[item_id] = []
            return item_id

    def id_of(self, number: str) -> str:
        found = [i for i, item in self.items.items() if item["number"].casefold() == number.casefold()]
        assert len(found) == 1, f"{number!r} is on {len(found)} items"
        return found[0]

    def count_of(self, number: str) -> int:
        return sum(1 for item in self.items.values() if item["number"].casefold() == number.casefold())

    def add_line(self, parent: str, child: str, sequence: int, quantity: str = "1") -> str:
        with self.lock:
            self._next_edge += 1
            edge = str(self._next_edge)
            self.bom[parent].append({"edge": edge, "item": child, "sequence": sequence, "quantity": quantity})
            return edge

    def lines_of(self, number: str) -> List[Tuple[str, int, str]]:
        """``(child number, sequence, quantity)`` of the lines under an item, in sequence order: what a person sees in the BOM tab."""
        with self.lock:
            rows = self.bom[self.id_of(number)]
            return sorted(((self.items[r["item"]]["number"], r["sequence"], r["quantity"]) for r in rows), key=lambda r: (r[1], r[0]))

    def requests(self, method: str = "", containing: str = "") -> List[Tuple[str, str, Any]]:
        return [r for r in self.log if (not method or r[0] == method) and containing in r[1]]

    def writes(self) -> List[Tuple[str, str, Any]]:
        return [r for r in self.log if r[0] != "GET"]

    def fail(self, match: str, error: BaseException, nth: int = 1, after: bool = False, times: int = 1, writes_only: bool = False) -> Fault:
        fault = Fault(match, error, nth, after, times, writes_only)
        self.faults.append(fault)
        return fault

    # ---- The client below which this sits ------------------------------------------------------------------------

    def open_url(self, request: Any, _timeout: float, cancel: Optional[CancelToken] = None) -> Answer:
        """Stands in for ``core.http.open_url``: answers, or raises as the network would."""
        token = cancel or CancelToken()
        token.check()
        parsed = urllib.parse.urlparse(request.full_url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        method = request.get_method()
        body = json.loads(request.data) if request.data else None
        with self.lock:
            faults = [f for f in self.faults if f.hits(f"{method} {path}")]
        before = next((f for f in faults if not f.after), None)
        after = next((f for f in faults if f.after), None)
        if before:
            raise before.error
        if self.on_request:
            self.on_request(method, path, body)
        token.check()   # cancelled before the server did anything: nothing was done
        with self.lock:
            self.log.append((method, path, body))
            answer = self._answer(method, parsed.path, parsed.query, body)
        if self.on_done:
            self.on_done(method, path, body)
        token.check()   # cancelled after the server did the work: it was done, and the answer is lost
        if after:
            raise after.error
        return answer

    @contextmanager
    def serving(self) -> Iterator["FakeManage"]:
        """Route ``FmClient`` to this tenant, and make a wait between tries no wait at all."""
        with mock.patch.object(client_module, "open_url", self.open_url), mock.patch.object(CancelToken, "wait", lambda *_: False):
            yield self

    @staticmethod
    def client(token: Optional[CancelToken] = None) -> FmClient:
        auth = mock.Mock()
        auth.get_access_token.return_value = "token"
        return FmClient(ConnectionSettings(tenant="acme"), auth, token)

    # ---- The tenant's answers ----------------------------------------------------------------------------------

    def _answer(self, method: str, path: str, query: str, body: Any) -> Answer:
        if method == "GET" and path == "/api/v3/search-results":
            return self._search(urllib.parse.parse_qs(query).get("query", [""])[0])
        if method == "GET" and path == f"/api/v3/workspaces/{WORKSPACE}/sections":
            return Answer(200, [{"__self__": SECTION, "fields": [{"__self__": f"/api/v3/workspaces/{WORKSPACE}/fields/{NUMBER_FIELD}"}]}])
        if method == "GET" and path == f"/api/v3/workspaces/{WORKSPACE}/fields":
            return Answer(200, {"fields": []})
        if method == "GET" and (found := ITEM.match(path)):
            return self._read_item(found.group(1))
        if method == "POST" and ITEMS.match(path):
            return self._create_item(body)
        if method == "PATCH" and (found := ITEM.match(path)):
            return self._update_item(found.group(1), body)
        if (found := BOM_ITEMS.match(path)) and method == "POST":
            return self._add_line(found.group(1), body)
        if (found := BOM_ITEM.match(path)) and method in ("PATCH", "DELETE"):
            return self._change_line(method, found.group(1), found.group(2), body)
        raise refusal(404, f"no such resource {method} {path}")

    def _search(self, query: str) -> Answer:
        wanted = ITEM_NUMBER_IN_QUERY.findall(query)
        rows = [{"link": f"/api/v3/workspaces/{WORKSPACE}/items/{i}", "descriptor": f"{item['number']} - name", "sections": self._sections_of(item)}
                for i, item in self.items.items() if item["number"].casefold() in {w.casefold() for w in wanted}]
        return Answer(200, {"items": rows, "totalCount": len(rows)}) if rows else Answer(204)

    @staticmethod
    def _sections_of(item: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [{"link": SECTION, "fields": [{"__self__": f"/api/v3/workspaces/{WORKSPACE}/views/1/fields/{field}", "value": value}
                                              for field, value in item["fields"].items()]}]

    def _read_item(self, item_id: str) -> Answer:
        item = self.items.get(item_id)
        if not item:
            raise refusal(404, "no such item")
        return Answer(200, {"urn": f"urn:adsk.plm:tenant.workspace.item:{TENANT}.{WORKSPACE}.{item_id}", "version": item["version"],
                            "descriptor": f"{item['number']} - name", "sections": self._sections_of(item)})

    def _create_item(self, body: Any) -> Answer:
        """The number is the value of the number field of the request, or ``n`` in the short bodies some tests write."""
        number = str((body or {}).get("n") or collect_values(body).get(NUMBER_FIELD) or "")
        if not number:
            raise refusal(400, "error.item.number.required")
        item_id = self.add_item(number)
        self.items[item_id]["fields"].update({k: v for k, v in collect_values(body).items()})
        return Answer(201, None, {"Location": f"https://acme.autodeskplm360.net/api/v3/workspaces/{WORKSPACE}/items/{item_id}"})

    def _update_item(self, item_id: str, body: Any) -> Answer:
        if item_id not in self.items:
            raise refusal(404, "no such item")
        self.items[item_id]["fields"].update(collect_values(body))
        if NUMBER_FIELD in collect_values(body):
            self.items[item_id]["number"] = str(collect_values(body)[NUMBER_FIELD])
        return Answer(200, {})

    def _add_line(self, parent: str, body: Any) -> Answer:
        if parent not in self.items:
            raise refusal(404, "no such parent")
        item = ((body or {}).get("item") or {})
        match = ITEM_IN_LINK.search(str(item.get("link") or ""))
        child = match.group(1) if match else ""
        if child not in self.items:
            raise refusal(400, "error.bom.item.missing")
        if self.items[child]["version"] != item.get("version"):
            raise refusal(409, "error.bom.version.stale")
        if any(line["item"] == child for line in self.bom[parent]):
            raise refusal(400, "error.bom.duplicate")
        sequence = (body or {}).get("itemNumber")   # a line number may be held by several lines: seen in a real tenant (two lines at 1.4)
        edge = self.add_line(parent, child, sequence, str((body or {}).get("quantity") or "1"))
        return Answer(201, None, {"Location": f"/api/v3/workspaces/{WORKSPACE}/items/{parent}/bom-items/{edge}"})

    def _change_line(self, method: str, parent: str, edge: str, body: Any) -> Answer:
        line = next((l for l in self.bom.get(parent, []) if l["edge"] == edge), None)
        if line is None:
            raise refusal(404, "no such line")
        if method == "DELETE":
            self.bom[parent].remove(line)
            return Answer(204)
        new = (body or {}).get("itemNumber", line["sequence"])
        line["sequence"] = new
        line["quantity"] = str((body or {}).get("quantity", line["quantity"]))
        return Answer(200, {})
