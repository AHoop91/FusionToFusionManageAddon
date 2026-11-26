# Testing publishing

Publishing changes manufacturing data in Fusion Manage, so its tests go further than the usual unit test. This note says which test answers which question, how to use the fake Fusion Manage, and what the tests do not prove.

Run everything with `uv run python -m unittest discover -s tests -t .` (the `-s tests -t .` form keeps the tests out of the real add-in log).

## Which test answers what

| Question | File |
| --- | --- |
| Is each request built right (line bodies, blank and zero values, section links, markers)? | `test_regressions.py`, `test_bom_*`, `test_item_*`, `test_publish_*` |
| Whichever single write fails, however it fails, does a resend leave Fusion Manage as a clean send would, with nothing made twice? | `test_publish_failures.py` |
| Does cancelling at any write, then sending again, give the clean result? | `test_publish_failures.py`, `test_publish_end_to_end.py` |
| What if someone else changes Fusion Manage during a send (revised item, taken number, removed line, deleted parent)? | `test_publish_failures.py` |
| Do many requests in flight at once keep their order, their ids and their bounds? | `test_publish_concurrency.py` |
| Does what the Publish panel plans (`mbom-plan.js`, run with Node) work when the sender sends it? | `test_planner_to_tenant.py`, with `tests/js/emit_plans.js` |
| Do the user's journeys work from the palette action to the end state (first publish, republish, changed structure, partial failure and retry, cancel and retry, shared numbers)? | `test_publish_end_to_end.py` |
| Very wide, deep, shared, empty and oddly numbered structures | `test_large_and_unusual_boms.py`, `test_bom_tree.py` |

## The fake Fusion Manage (`tests/fake_manage.py`)

`FakeManage` is an in-memory tenant: items with an id, a number, a version and their fields, and the Bill of Materials lines of each. It stands in for `core.http.open_url`, below `FmClient`, so the real client runs on it: its retries, `Retry-After`, `outcome_unknown` and the reading of `Location` are the real ones.

```python
tenant = FakeManage()
parent = tenant.add_item("A")
with tenant.serving():                       # routes FmClient to the tenant
    run = SendRun(folder, load_plan(folder), tenant.client())
    run.work()
tenant.lines_of("A")                         # [(child number, line number, quantity)]
```

Faults: `tenant.fail(match, error, nth=, after=, times=, writes_only=)` makes the nth request whose `"METHOD path"` contains `match` fail. `after=False` is a request that never arrived; `after=True` is a request the server did, whose answer was lost. `tenant.on_request` and `tenant.on_done` are called before the server does the work and after it did: use them to change the tenant (another user's edit), to cancel a run at a chosen write, or to slow requests so they overlap. Assert on what the tenant holds (`end_state`, `lines_of`, `count_of`), not on how often a mock was called.

`tests/publish_helpers.py` builds publish folders from BOM operations through the production `bom_requests`, so the request shapes are the real ones.

## What the fake is, and is not

It answers the requests a publish makes, in the shapes the code reads (see the Seen and Assumed marks in the other notes). It is not Fusion Manage, and it proves nothing about what the real service accepts. One rule in it is an assumption: an item version that is not current is refused with a 409. (It does not refuse a duplicate BOM line number: a real tenant allows two lines at one number.) Change the fake, not the production code, if a real answer shows either to be wrong. A shape not yet seen in a real log must be marked Assumed where it is described.

## Known bugs the tests hold

A test marked `@unittest.expectedFailure` states what should be true and fails today. Each says why in its docstring. Remove the marker in the commit that fixes the bug; the suite fails ("unexpected success") if a fix is made and the marker is left.
