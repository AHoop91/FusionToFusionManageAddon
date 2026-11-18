# Finding items

How the add-in finds items and components in Fusion Manage, and where the item number it searches for comes from. Read this before you add another search, because there are already several and each has its own reason. The Manufacturing Data Model side is in [manufacturing-data-model.md](manufacturing-data-model.md).

## Where the number comes from

Fusion's API gives a component only its part number, and a part number need not equal the item number Fusion Manage knows it by. The item number is read from the Data Model:

- `ItemNumbers.resolve(ref, part_number)` in `src/ui/item_numbers.py` returns a `Subject(item_number, part_number)`. The design's own number is in its summary; a component below it is found in the design's BOM by part number. Both are cached (`DesignReads`, and a file of found numbers).
- A component with no item number has not been published and raises `NoItemNumber`.

Everything below starts from that number. Never search Fusion Manage by part number.

## Finders

All are `GET /api/v3/search-results` unless noted, and all scope the query to one workspace with `workspaceId=<id>` so an OR can never reach another workspace.

| Finder | Code | Query | Revision | Returns | Used by |
| --- | --- | --- | --- | --- | --- |
| One number | `ItemService.search(ws, number)` in `src/fm/items.py` | `itemDescriptor="<number>" AND (workspaceId=<ws>)`, 50 results | `WORKING` by default | `[{id, descriptor}]` | Item panel, `bom_levels` (`search_design`, `compare_level`), `attachment_upload`, `Dispatcher._created_before` |
| Many numbers | `ItemService.find_many(ws, numbers)` | `(itemDescriptor="a" OR itemDescriptor="b") AND (workspaceId=<ws>)`, 50 a page, asks for the bulk media type so each hit carries its fields | `WORKING` | `{number key: [{id, descriptor, values}]}` | `ReadAhead` in publish, 10 numbers a search, 2 searches at once |
| Add Items picker | `ItemSearchService.page` in `src/fm/item_search.py`, query from `search_path` in `src/fm/search_query.py` | Free text and filter groups, built by `build_query`; oldest first; 25 a page | `LATEST` by default | `{total, raw, items[]}` with a linkable row | `PickerReads.items` (`search_actions.py`), `add-items.js` |
| A component's working record | `ComponentService.find_working(number)` in `src/fm/components.py` | `<number> AND (workspaceId=<Components workspace>)`, `isFullQuery=true`, 50 results; keeps a title that is the number or starts with it and a separator | `WORKING` | `(link, "")` or `("", reason)` | `attachment_upload` |
| A component in a picklist | `ComponentService.matching` and `find(lookup, number)` | `GET /api/v3/lookups/<lookup>?filter=<number>`, 25 options | all revisions | the options (one for each revision of a component) | Publish (`runner.py`) and the Assign Product wizard (`ProductService._options_of` in `products.py`) |
| Rows of a view | `TableauService.rows` | Not a search: a saved view of a workspace | n/a | rows | Products page, see [tableaus.md](tableaus.md) |

### Choosing among several matches

`resolve_hits(hits, number, chosen)` in `items.py` picks the item to use: the hits whose descriptor starts exactly with the number (`number_key` splits at ` - `), else all hits. One is used as it is; several are a choice for the user. `ItemChoices` remembers the choice by workspace and number for as long as the add-in runs, and is shared by the Item panel and the uploads that start from it, so they cannot disagree. The BOM compare does not guess: several items with one number set `shared` and nothing is compared (`bom_levels.compare_design_bom`).

### Revisions

The search's `revision` filter: 1 the latest version of each item (a working version included), 2 every revision, 3 the working version only. The add-in changes only the working version (a released one cannot be changed), so what a publish, export or panel compares uses `WORKING`. The Add Items picker lists `LATEST`. `search_query` holds `LATEST` and `WORKING`; do not write the numbers elsewhere.

## Building a query

- Go through `src/fm/search_query.py`: `clean_value` removes the characters the search reads as operators, `term` quotes a value with spaces, `field_id` makes a field id as the search wants it, `encode` produces what follows `query=`.
- `items._quoted` quotes an item number and drops a quote or backslash, which would end the term early.
- Never put text from the page or the design into a query without one of these.
- A number is compared as `number_key`: trimmed, lower case.

## Adding a search

1. Check the table first. If the answer is "the item with this number in this workspace", call `ItemService.search` or `find_many`.
2. If a new search is needed, put it next to the related one, build the query through `search_query`, scope it by workspace and say which revision it wants.
3. Run it on a worker thread. A failed search raises; do not turn a failure into "not found".

## What Fusion Manage answers

No search answer is in the add-in log, so every key is **Assumed** from the code and tests (`tests/test_items_search.py`, `tests/test_item_search.py`, `tests/test_search_query.py`, `tests/test_components.py`).

| Answer | Keys read |
| --- | --- |
| `search-results` | `items[]`, and in each: `descriptor`, `version` (`[REV:w]`), `__self__` or a link key (`LINK_KEYS`), `itemDescriptor`/`title` as a descriptor fallback; `totalCount` (or `totalHits`) |
| `search-results` with the bulk media type | The same rows, each holding the item's fields as `.../fields/<ID>` entries with `value` (`collect_values`) |
| `lookups/<name>` | `items[].link`, `title`, `version` |
| `workspaces` list (to find Components) | `items[].title` or `name`, `link` or `__self__` |
| BOM members (`.../items/<id>/bom`) | `nodes[].item.link`, `item.title` |

## Known duplication

Listed for a decision; nothing has been changed.

- `SEARCH_RESULTS` and `SEARCH_LIMIT` are defined in both `items.py` and `components.py`, and `item_search.py` writes the search path again by hand.
- The `/items/(\d+)` pattern is written three times (`items.py`, `item_search.py`, and `ITEM_LINK` in `pages.py` that `components.py` uses), and the descriptor keys are read in `items.py` and `item_search.py` separately.
- `find_working` searches by free text and `ItemService.search` by `itemDescriptor`; both are workspace-scoped searches by item number. `find_working` could probably call `ItemService(client, WORKING).search` on the Components workspace and keep its own title check. That would need a live check, because the two query forms may not return the same hits.
- `find_many` leaves out a number with no hit and says the caller must ask again, and `read_ahead.found` returns `None` for the item to look for itself. That is a fallback to a second path.
