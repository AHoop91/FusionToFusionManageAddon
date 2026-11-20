# Publish Item: order of operations

This note follows one design through the Publish Item panel, from opening it to the last request sent to Fusion Manage. It says what the code does now, in the order it does it. The last section lists where the order is uneven, as a starting point for clean-up.

Files: the panel is `src/ui/web/publish/js/publish.js` (loading), `publish-mbom.js` (the MBOM dropdown), `publish-bom.js` (the Bill of Materials and the Publish button) and `publish-jobs.js` (the progress dialog and the Jobs window). Python is `src/publish/panel_sections.py` (the sections), `src/ui/actions/publish_run_actions.py` (starting a run), `src/publish/runner.py` (a run) and `src/publish/sender.py` (the sending).

## 1. Opening the panel: the sections, in order

The panel asks Python for one section at a time (`load_publish_section`) and polls `load_publish_section_status` until it is no longer pending. A section is a slot in `PublishSections`; a slot is read again only when the design, the settings stamp (hub, tenant, workspace), the target or the target id changed, or when the panel forces it.

| Step | Section | What it does | Starts when |
| --- | --- | --- | --- |
| 1 | `summary` | Checks the user may publish (`publish_denial`), then reads the design from the Data Model: component id, lineage, item number, file name, description, composition. A design with no item number is refused: it was never published. | The panel opens, another design is open, or Refresh is clicked |
| 2a | `thumbnail` | The design's picture. | The summary is in |
| 2b | `mbom` | Reads the design's record in the Components workspace for its link and asset id, then searches the Items workspace (v1 search) for the items with that lineage id and asset id that are the working version. Each hit is `{id, number, descriptor}`. | The summary is in |
| 3 | The MBOM is chosen | The dropdown shows the descriptors. The panel keeps the chosen number as `target` and the item's id as `target_id` (empty for a new number). It keeps the number it had chosen before when that is still listed, else the first. | The `mbom` answer is in |
| 4 | `structure` | Reads the first level of the Bill of Materials from the Data Model and compares it with the BOM of the target item. With a `target_id` the item is read by id; with none the item is searched for by its number while the Data Model is read. | The MBOM is chosen. If the lookup failed, nothing else is asked: the panel shows why, with a retry. |
| 5 | `properties` | Reads the design's own properties and compares them with the target item (by id when known, else by number). It is shown in the Details Panel and counts for the up-to-date check. | The first level is in, so it never slows the BOM |

Other things the panel asks for later:

- A new MBOM: the "+" button or the last entry of the dropdown opens a form with the design's item number and a hyphen. `mbom_number` asks whether any item of the workspace already has the number (v3 search on the descriptor, any version). If none, the number is added to the list as a local entry with no id and is chosen. Nothing is made in Fusion Manage until Publish.
- Choosing another MBOM: the Bill of Materials and the properties are cleared and read again for the new target (steps 4 and 5). The thumbnail and the MBOM lookup are kept.
- Opening an assembly in the table: `children:<id>` reads and compares that level, matching by item number (there is no id for a child).
- Details Panel: `component:<id>` and `thumbnail:<id>` for one row.
- `tree`: the whole tree, read the same way as step 4. It runs when Publish is clicked and levels are still unread, or on Expand all.

## 2. Clicking Publish (panel)

1. If levels of the tree are not read, `tree` loads them first and the click goes on afterwards.
2. If any line still needs a choice (for example several Fusion Manage items share a number), a message says so and nothing is sent.
3. The panel builds the job from what it shows: `summary` (with the target's item number in place of the design's), `root_number`, `items` (one for each component to publish, the design as `root`) and `operations` (the Bill of Materials changes, from `bomPlan.publishPlan`). The ids of the items found by lineage are not part of the job.
4. `start_publish` carries the job and the settings stamp.

## 3. Starting the run (Python, Fusion's thread, then a worker)

1. Fusion's thread: `HubContexts.attempt` (hub, tenant, connection, workspace, sign-in together). It refuses when no Items workspace is set, when the stamp is not the one now active (settings changed since the design was read), or when no model id is open.
2. A worker thread: the permission check again (a page may have been open while permissions changed).
3. `PublishFolder` is made in the temp folder, `PublishRun` is created with `send=True` and put on the `JobQueue`. The panel opens its progress dialog on the run and polls `list_publish_jobs`.

## 4. The run (the queue's worker thread)

The run uses clients tied to its cancel token, so Cancel ends a request at once. `PublishRun._steps` does the following, by stage.

**Validating**

1. Items whose item number is shared (`shared_numbers`, from the panel's summary of components) are taken out as unpublishable.
2. `ReadAhead` starts, for the rest of the items: the Data Model reads (several components to a request, 3 in flight) and the Fusion Manage searches by item number (v3, working version, 10 numbers to a search, 2 in flight).
3. The sections of the workspace's fields are read in the background.
4. `_require_unique_numbers` waits for every search. If a number is carried by several Fusion Manage items, the whole run fails with nothing written (`SharedItemNumbers`). A failed search fails the run too.

**Items** (5 at a time)

For each item (`_prepare`, then `_item`):

1. Skipped if it has no number or its number is shared.
2. `_compare`: the lookup (`lookup_item`, from the shared search hits) and the Data Model read run together, then `compare_with_item` gives the state (`new`, `found`, `multiple`, `unknown`) and the rows.
3. `_component`: the Components item to link, from the Data Model's link. A component the Data Model does not link is recorded as failed (no search of the picklist), and the item is sent without the link. With a link, the pivot of the linking field is read for the linked item (`GET /api/v3/workspaces/<items ws>/views/1/pivots/<field>?pivotItemId=<id>`, `PivotService`): the derived fields it lists (`COMPONENT_ASSET_URN`, `COMPONENT_LINEAGE_URN`) are sent with the link, each in the section the pivot names. Fusion Manage refuses a create without them. A pivot that cannot be read fails the link.
4. `_option_rows`: picklist text becomes option links, numbers are fitted to the field's digits. A value with no option is left out and recorded.
5. `_request`: the thumbnail is downloaded (a fresh signed url is asked for if it expired) and `item_request` makes a POST (new) or PATCH (found) request. Nothing is made for a found item that already matches, except the thumbnail.
6. The request is written to the item's folder, and the item's state and id go to the manifest.
7. The dispatcher learns the item's id, then `send_item` sends the request: skipped if the send log says it was done, a create that was cut off is looked up by number first, a create is logged as intended before it is sent, and a refusal is logged. At most 5 writes are in flight across everything.

A failure in one item never stops the others.

**Bill of Materials**

1. `_write_boms` writes each parent's requests to `bom/<parent>.bom.request.json`.
2. After every item is sent, `_send_boms` sends each parent's requests, 5 parents at a time. For a parent, the removals and updates go first, then the additions, 5 requests at a time. Each request holds markers for item ids, versions and the tenant. The dispatcher fills them: an id it learned, else a search by item number (`WORKING`), which must find exactly one. A parent whose create failed is not sent. A failed request ends its step; the other parents go on.
3. A duplicate line is not an error, nor is a line already gone after a cut-off send.

**End**

The manifest is saved (`root`, workspace, tenant, model, cancelled) and the phase becomes `done`, `error` or `cancelled`. A run with failed rows is announced with a message box unless a progress dialog is following it. A failed run is retried from its folder (`SendRun`): it sends the written requests again, skips what the send log holds, and refuses when the tenant is not the one it was made for.

## 5. Where the order is uneven

These are facts from reading the code, not decisions.

1. **Two ways of finding the item.** The panel finds the target by lineage and asset id (`mbom`) and reads it by id. The run does not carry the id: it finds each item again by item number (`ReadAhead`, `lookup_item`, `Dispatcher._item_id`, `_created_before`). An item renumbered in Fusion Manage is compared correctly in the panel, but Publish searches for the old number and treats the item as new or fails to find it.
2. **The same search twice.** Step 4 (`structure`, or `tree`) searches Fusion Manage for the design's number when there is no id, and the run's `ReadAhead` searches for it again. The panel's result is not handed to the run.
3. **The new-number check is not the run's.** `mbom_number` asks whether the number is free when the form is submitted. The run checks uniqueness only as "not more than one", so a number taken after the check is treated as an existing item and updated.
4. **Children are matched by number only.** `children:<id>` and the run's items for child assemblies have no lineage or asset search.
5. **A design with no MBOM found.** `mbom` answers with an empty list, no target is set, and the panel compares and publishes under the design's own item number, searched by number. That is the old behaviour, kept beside the lineage search: a design whose item has no lineage or asset id filled in is found only this way.
