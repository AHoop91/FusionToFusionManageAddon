# Finding items

How the add-in finds items and components in Fusion Manage, and where the item number it searches for comes from. Read this before you add another search, because there are already several and each has its own reason. The Manufacturing Data Model side is in [manufacturing-data-model.md](manufacturing-data-model.md).

## Where the number comes from

Fusion's API gives a component only its part number, and a part number need not equal the item number Fusion Manage knows it by. The item number is read from the Data Model:

- `ItemNumbers.resolve(ref, part_number)` in `src/ui/item_numbers.py` returns a `Subject(item_number, part_number)`. The design's own number is in its summary; a component below it is found in the design's BOM by part number. Both are cached (`DesignReads`, and a file of found numbers).
- A component with no item number has not been published and raises `NoItemNumber`.

Everything below starts from that number. Never search Fusion Manage by part number.

## Finders

All v3 search code is in one file, `src/fm/v3_search.py`: the query building, the paths, reading the rows, choosing among hits and the searches themselves. All finders are `GET /api/v3/search-results` unless noted, and all scope the query to one workspace with `workspaceId=<id>` so an OR can never reach another workspace.

| Finder | Code | Query | Revision | Returns | Used by |
| --- | --- | --- | --- | --- | --- |
| One number | `ItemFinder.search(ws, number)` in `src/fm/v3_search.py` | `itemDescriptor="<number>" AND (workspaceId=<ws>)`, 50 results | `WORKING` by default | `[{id, descriptor}]` | Item panel, `bom_levels` (`search_design`, `compare_level`), `attachment_upload`, `Dispatcher._created_before`, `BoughtItems._source_id` (an EBOM line's bought version) |
| Many numbers | `ItemFinder.find_many(ws, numbers)` | `(itemDescriptor="a" OR itemDescriptor="b") AND (workspaceId=<ws>)`, 50 a page, asks for the bulk media type so each hit carries its fields | `WORKING` | `{number key: [{id, descriptor, values}]}` | `ReadAhead` in publish, 10 numbers a search, 2 searches at once |
| Add Items picker | `ItemSearchService.page` in `src/fm/v3_search.py`, query from `search_path` | Free text and filter groups, built by `build_query`; oldest first; 25 a page | `LATEST` by default | `{total, raw, items[]}` with a linkable row | `PickerReads.items` (`search_actions.py`), `add-items.js` |
| A component's record | Not a search: the Data Model says which record a part is linked to (`ItemNumbers.record_link`, see [manufacturing-data-model.md](manufacturing-data-model.md)) | n/a | n/a | the record's API link | `attachment_upload`, View product portfolio |
| A component in a picklist | `ComponentService.matching(lookup, number)` | `GET /api/v3/lookups/<lookup>?filter=<number>`, 25 options | all revisions | the options (one for each revision of a component) | The Assign Product wizard (`ProductService._options_of` in `products.py`) |
| Rows of a view | `TableauService.rows` | Not a search: a saved view of a workspace | n/a | rows | Products page, see [tableaus.md](tableaus.md) |

### Choosing among several matches

`resolve_hits(hits, number, chosen)` in `v3_search.py` picks the item to use: the hits whose descriptor starts exactly with the number (`number_key` splits at ` - `), else all hits. One is used as it is; several are a choice for the user. `ItemChoices` remembers the choice by workspace and number for as long as the add-in runs, and is shared by the Item panel and the uploads that start from it, so they cannot disagree. The BOM compare does not guess: several items with one number set `shared` and nothing is compared (`bom_levels.compare_design_bom`).

### Revisions

The search's `revision` filter: 1 the latest version of each item (a working version included), 2 every revision, 3 the working version only. The add-in changes only the working version (a released one cannot be changed), so what a publish, export or panel compares uses `WORKING`. The Add Items picker lists `LATEST`. `v3_search` holds `LATEST` and `WORKING`; do not write the numbers elsewhere.

## Building a query

- Go through `src/fm/v3_search.py`: `clean_value` removes the characters the search reads as operators, `term` quotes a value with spaces, `field_id` makes a field id as the search wants it, `encode` produces what follows `query=`.
- `quoted` quotes an item number and drops a quote or backslash, which would end the term early.
- Never put text from the page or the design into a query without one of these.
- A number is compared as `number_key`: trimmed, lower case.

## Adding a search

1. Check the table first. If the answer is "the item with this number in this workspace", call `ItemFinder.search` or `find_many`.
2. If a new search is needed, put it in `v3_search.py`, build the query with its helpers, scope it by workspace and say which revision it wants.
3. Run it on a worker thread. A failed search raises; do not turn a failure into "not found".

## What the v3 search cannot do

The v3 search reads the search index, not the database (Autodesk's Advanced search reference). Only the Item Details tab (without classification data) and attachment names, titles and descriptions are indexed, and the answer's fields cannot be chosen. It cannot search the Grid tab, bills of materials, sourcing or other tabs. Use the v1 search for the Grid.

What the help pages document, and the code relies on:

- `revision` 1 latest, 2 every revision, 3 working. `sort` takes `score`, `lastModifiedOn`, `createdOn` or `itemDescriptor` with `asc` or `desc` (the add-in sorts `createdOn asc`). A bulk request (`ITEMS_BULK`) holds at most 100 items a page.
- `AND` and `OR` are upper case and combined with brackets; an unquoted space means `OR`; `AND` between two workspace ids finds nothing; quotes match whole words in order. The characters `` ` ( ) : < > = \ / ] [ { } `` are not allowed inside a term (`clean_value` removes them).
- Archived items are left out unless the query says `isDeleted=TRUE`.

## Searching the Grid: the v1 search

`src/fm/v1_search.py` posts a search definition to `POST /api/rest/v1/workspaces/<id>/items/search`. Fields, filters and sort each name the tab they live on (`fieldTypeID`; the Grid is `GRIDVIEW`, 2). Use `build_definition` with `Field`, `Filter` and `Sort`, then `V1SearchService.page` (one page) or `rows` (every row). A single filter must be sent with `OR`; `build_definition` does that. Its users are `BoughtItems` (`_refuse_if_made` for one source, `existing` for the whole EBOM: the source link field and the number field of the Items workspace, the number field CONTAINS a text; **not seen live**) and `ProductService.usage` (the portfolio check of where the open design is used): it reads the Primary Component field and the Variants link column of every product, keeps every entry of a row (`V1Row.entries`, since a Grid column may come once for each grid row), and compares them with `number_matches` here, not in the search. What the first live call showed (log of 2026-11-18, workspace 343 "Products"):

- The add-in's v3 bearer token is accepted: the call was answered, not refused with 401. (The help page documents a session cookie; it is not needed.)
- A search must name a sort. A definition with `"sort": []` is refused with 400 and `{"httpStatusCode":400,"error":[{"message":"sortFieldsList is not specified"}]}`. `build_definition` raises when it is given no sort, so a caller names one (`ProductService.usage` sorts on the Primary Component field).
- The answer is not wrapped (`reportResult` is absent) and keeps the casing of the help page's example: `rowId` and `dmsId`, as below.
- A picklist cell holds its text in both `value` and `label`; `formattedValue` was not seen on one.
- A row has no entry for a field it leaves blank. The Variants Grid column was asked for and the row came back with no entry for it, so how v1 answers a Grid column that has rows is still **Assumed** (`V1Row.entries` keeps every entry, in case it comes once for each grid row).
- A search that matches nothing is answered `204` with no body (log of 2026-11-19, workspace 242, a filter on the derived fields `COMPONENT_LINEAGE_URN` and `COMPONENT_ASSET_URN`), not with a `totalResultCount` of 0. `V1SearchService.page` reads it as no rows. The same search on `COMPONENT_LINEAGE_URN` alone with the filter `IS` (15) answered 200 with the three items made from the design.

## What Fusion Manage answers

The v1 answer below is **Seen**. No v3 search answer is in the add-in log, so every other key is **Assumed** from the code and tests (`tests/test_items_search.py`, `tests/test_item_search.py`, `tests/test_search_query.py` (all of `v3_search.py`), `tests/test_components.py`).

| Answer | Keys read |
| --- | --- |
| `search-results` | `items[]`, and in each: `descriptor`, `version` (`[REV:w]`), `__self__` or a link key (`LINK_KEYS`), `itemDescriptor`/`title` as a descriptor fallback; `totalCount` (or `totalHits`) |
| `search-results` with the bulk media type | The same rows, each holding the item's fields as `.../fields/<ID>` entries with `value` (`collect_values`) |
| v1 `workspaces/<id>/items/search` (**Seen**) | `totalResultCount`; `columnKey[].{value, label}`; `row[].{rowId, dmsId, fields.entry[].{key, fieldData.{value, label, dataType}}}`; an error is `{httpStatusCode, error[].message}` |
| `lookups/<name>` | `items[].link`, `title`, `version` |
| `workspaces` list (to find Components) | `items[].title` or `name`, `link` or `__self__` |
| BOM members (`.../items/<id>/bom`) | `nodes[].item.link`, `item.title` |

## Known duplication

Listed for a decision; nothing has been changed. The constants, the search path and the item link pattern that used to be written in several files are now in `v3_search.py` and `pages.py`.

- `find_many` leaves out a number with no hit and says the caller must ask again, and `read_ahead.found` returns `None` for the item to look for itself. That is a fallback to a second path.
