# Tableaus: views and rows

How the add-in reads a workspace's views (Fusion Manage calls them tableaus) and their rows, and how the Assign Product window shows them. The exact keys of each answer, and which were seen in a real answer, are in "What Fusion Manage answers" below.

## Python: `TableauService` (`src/fm/tableaus.py`)

Every method takes a workspace id (and a view id, which must be digits: `_view_path` refuses anything else because the id goes into the address). Each raises `FmApiError` when Fusion Manage refuses. Every answer is written to the log up to `LOG_CHARS` (20000).

| Method | Answers | Reads or writes |
| --- | --- | --- |
| `views(workspace_id)` | `{views: [{id, name}]}`. Views of one name get their id added, `All (713)`. | `GET /tableaus`. Also re-reads the field titles. |
| `columns(workspace_id, view_id)` | `{columns: [column]}` in the view's display order, before any rows are read | `GET /tableaus/{view}` with the `META` type |
| `available(workspace_id)` | `{fields: [{key, title, group, multiple, filters}]}`: every field a view of the workspace can show or filter by, grouped by section | `GET /tableaus` with the `META` type (kept, see below) |
| `save_view_filters(workspace_id, view_id, changes, columns=None)` | `{columns}` as the view now holds them | Reads the view fresh, changes the `appliedFilters` of the named columns, optionally rearranges the columns, then `PUT`s the whole view back with the `META` type |
| `create_view(workspace_id, name, columns)` | `{id}` | `POST /tableaus` with the `META` type. The id is read from the `Location` header. The view starts sorted by its first column and without filters. |
| `rename_view(workspace_id, view_id, name)` | `{id, name}` | Reads the view, changes `name`, `PUT`s it back |
| `delete_view(workspace_id, view_id)` | `{id}` | `DELETE /tableaus/{view}` |
| `rows(workspace_id, view_id, page, size)` | One page, see below | `GET /tableaus/{view}?page=&size=` |
| `image(workspace_id, item_id, field, number)` | `{image: data URI}` ("" if unreadable) | A picture of a row |
| `picture(workspace_id, link)` | `{image: data URI}` | A picture an item gave a link for. Only a link of an item in this workspace is read. |

A view is shared, so a save, rename or delete changes it for everyone. The Save of the filters panel says so.

Shapes the methods build:

| Name | Shape |
| --- | --- |
| column (`parse_columns`) | `{id, key, title, multiple, filters: [{id, name, takes_value, kind}], applied: {match, filters: [{type, value}]}}`. `id` is the bare field id, `key` is `views/1/fields/TITLE` (two sections can both have a `TITLE`). A filter's `id` is its link (`/api/v3/filter-types/2`). |
| page of rows (`parse_rows`) | `{columns: [{id, title, kind}], rows: [{id, cells: {column id: text}, html: {column id: markup}}], total, raw, page, size}`. `id` is the item id from the row's `item.link`. `raw` is how many rows the page held; `total` is the answer's count (0 if it gave none). `kind` is `image` or `text`. |

Details worth knowing:

- Rows name their fields by id only. Titles come from the `META` list of fields (`_field_titles`), which `_fields_meta` keeps per tenant and workspace (`TtlCache`). `views` re-reads it, so a renamed field shows after the views are read again.
- A cell whose type title is `Image` has the picture number as its text. A cell that holds HTML (formula badges and bars arrive escaped) is unescaped; if it has tags, the tag-stripped text goes in `cells` and the markup in `html`.
- `rows` limits: `DEFAULT_SIZE` 50, `MAX_SIZE` 200, page at least 1.
- Limits on writes: a view name is 1 to `MAX_VIEW_NAME` (30) characters; at most `MAX_COLUMNS` (100) columns and `MAX_FILTERS` (20) filters per column; a filter value is cut at `MAX_FILTER_VALUE` (500). A column takes more than one filter only when its `allowMultipleFilters` says so. `_chosen_filters` checks each filter type against the column's `applicableFilters` and demands a value where `allowValue` is true.
- `save_view_filters` takes `changes` as `[{column, match: "ALL"|"ANY", filters: [{type, value}]}]`; an empty `filters` clears the column. `column` is a key (`views/1/fields/TITLE`) or a bare id. A field the view does not show yet joins it as its last column. With `columns` (a list of keys) the view shows exactly those, in that order, in the same save; a sorted view stays sorted, by its first column if the sorted one went (`_arrange_columns`).
- The view's content type matters. A view definition is sent back with the `META` content type it was read with. The tests simulate a 415 on it (`tests/test_tableaus.py`, `refuse_meta`); no real 415 is in the log.

## Screens

The View product portfolio window has three screens, one shown at a time by `showScreen('usage' | 'list' | 'form')`: the usage screen (where the open design is used, shown first and again after an assign or when the palette is opened), the list of products (reached by Assign to product, with Back to return) and the form of a product. `openList` loads the views the first time the list is shown.

## Actions (`src/ui/actions/product_actions.py`)

Each `ProductReads` method wraps one `TableauService` call in `_in_workspace`, which answers at once if the Portfolio workspace is off or not set up, and otherwise runs the read on a worker thread.

| Action | Method | Payload |
| --- | --- | --- |
| `products_views` | `views` (adds `can_create` from the user's permission) | none |
| `products_columns` | `columns` | `view` |
| `products_fields` | `fields` (calls `available`) | none |
| `products_filter` | `save_filters` | `view`, `changes`, optional `columns` |
| `products_create_view`, `products_rename_view`, `products_delete_view` | `create_view`, `rename_view`, `delete_view` | `name` and `columns`; `view` and `name`; `view` |
| `products_rows` | `rows` | `view`, `page`, `size` |
| `products_image`, `products_picture` | `image`, `picture` (run `alongside`, so they do not queue behind the one-at-a-time lock) | `item`, `field`, `number`; `link` |
| `products_usage` | `usage`: where the open design is the Primary Component of a product or a variant (`ProductService.usage`, the v1 search). A design with no item number answers `{unpublished, message}`. | none |
| `products_design` | `design`: the open design's name, number and thumbnail url (`ItemNumbers.describe`) with the revision and state of its Components item. Blank details, not an error, when the design is not saved or the item is not found. | none |
| `products_design_file`, `products_open_file` | `design_file` reads the lineage id of a component item (worker thread); `open_design_file` opens it in Fusion (Fusion's thread, no token). Not offered on the usage screen (see [manufacturing-data-model.md](manufacturing-data-model.md)). | `link`; `file` |

`products_usage` returns each product as `{id, number, name, url, picture, component}` (and `rows` for a variant): `number` and `name` are its descriptor split by `bom.split_title`, `url` is its page in Fusion Manage, `picture` the link of the first picture it holds and `component` the link of its Primary Component item. The search is sorted on the Primary Component field, since the v1 search needs a sort. A page reads every product it names once, one after another.

## JavaScript

All of it is in `src/ui/web/products/js/`.

| Piece | File and functions |
| --- | --- |
| Views | `products-page.js`: `loadViews` reads the list and chooses the view (the last one used, kept in `localStorage`, else the first). `makeViewPicker` is the shared picker with rename and delete buttons on each view and a footer to create one. `product-views.js` (`ns.productViews.init(host)`) draws the rename, delete and create dialogs and gives back `askRename`, `askDelete`, `openNew` and `closeFront`; the page lends it `ask`, `failure`, `setAlert`, `isBusy`, `columns`, `reload`, `deleted` and `created`. |
| Rows | `loadRows(page)` asks `products_rows` (50 a page, `PAGE_SIZE`) and, for page 1, `readColumns` asks `products_columns` so the header shows while rows are still on the way. `rowsToken` and `columnsToken` drop an answer that arrives after a newer request. `drawRows` paints the body, and `more` is true when `total` says there is another page (or, with no total, the page was full). |
| Table | `paintHeader` (a title per column, plus a funnel button when the column has filters), `cellOf` (markup through `ns.safeHtml.render`, a picture, or text), a radio column that picks one row. The first column is styled as the product itself (`products-primary`). |
| Column widths | `applyWidths` and `startResize`: the first drag fixes every column at the width it has, then only the dragged column moves (minimum 60 px). |
| Usage screen | `loadUsage` asks `products_usage` and `products_design` together (`usageSeq` and `designSeq` drop an answer that is late). `showDesign` paints the head: thumbnail, name, number, revision and state chips. A card asks for its picture (`products_picture`) only once it is on screen in the usage view (`whenSeen`, an `IntersectionObserver`), so a card below the fold or on a tab that is not shown is not read. `showUsage` paints the two groups, "Primary component of" and "Variant of", as two tabs, Primary Components and Variants (`usageTabs`; it opens on the tab chosen last, else the first with cards), each over a grid of cards (`usageGroup`, `usageCard`). A group shows `USAGE_PAGE` (25) cards and a Load more button adds the next 25, and the tab says how many are shown of how many there are ("Variants (25 of 80)"); this pages what the check has read, not the read itself, which still covers every product. A design used nowhere shows one centred message with an icon (`pu-empty-state`). While a read is on its way `showDesign(null)` and `usageSkeleton` show grey sweeping blocks. |
| Card menu | `usageMenu(entries)` is the three dots and the menu they open (`[{label, run}]`), made with the page's own `menu(button, list)` (arrow keys, Escape, one open at a time) and the `products-menu` classes; `forgetMenus` drops the menus of cards that are replaced. A card offers Open in Fusion Manage (`open_url`). Every action the page asks for must be in the `bridge.on` list near the end of `products-page.js`: `tests/test_products.py` checks it. |
| Pictures | `cellOf` puts a shimmering block in the cell and queues the picture. `pumpPictures` asks `products_image` for at most 8 at once. `pictureCache` (`'item:field'` to data URI) stops a picture being asked for twice. |
| Filters | `filters.js`, below. |
| Sorting | `sortable.js` is drag to reorder, not row sorting: `ns.sortable.start(event, {row, list, rowSelector, onDrop})` moves a row of a list by its grip. It is used for the columns lists (the Columns tab and the new view dialog). The table does not sort rows; a view's own `sort` is kept when it is saved. |

### `filters.js`

`ns.filters.init(host)` wires two pieces to the page. `host` is `{ask, fail, definition, apply}`: `ask(action, payload, done)` for requests, `fail(answer)` to show a refusal, `definition()` for the columns of the view shown, `apply(changes, columns)` to save.

- The pop-up under a column (`openColumn(column, anchor)`): a list of filter lines (a `dropdown` of the column's `filters` and a value box when `takes_value`), with an And or Or choice (disabled when the column takes one filter). Save calls `host.apply([change])`.
- The panel at the top right, with two tabs. Filters: a card per field that has filters, and a search box over `products_fields`, listed by section. Columns: the shown columns (drag by the grip, or Alt with the arrow keys; untick to hide, but a view keeps at least one) and the sections of fields not shown yet. Save calls `host.apply(changes, columns)` once, so filters and columns reach the view in one `PUT`.
- `preload` reads `products_fields` once; the page calls it when the view's columns arrive.

`applyFilterChanges` in `products-page.js` sends `products_filter`, replaces `definition` with the columns answered, and calls `loadRows(1, true)`.

## What Fusion Manage answers

**Seen** means the key is in a real answer written to the add-in log (`%LOCALAPPDATA%\MfgToFm\logs\MfgToFm.log` and its `.1`, `.2` and `.3` rotations, read on 2026-11-17, workspace 343 "Products" and workspace 57). **Assumed** means the code or a test relies on it but no logged answer shows it; treat it as a guess until it is seen. Do not add a key you have not seen. Where the code accepts an answer as a list or as an object holding the list, it goes through `rows_in(data, key)` (`src/core/shapes.py`).

### Views of a workspace

`GET /api/v3/workspaces/{id}/tableaus` (`parse_views`). Seen as an object.

| Key | Meaning | Status |
| --- | --- | --- |
| `tableaus` | The list of views | Seen |
| `tableaus[].link` | `/api/v3/workspaces/343/tableaus/713`; the view id is its last segment (`id_of` tries `__self__`, `link`, `urn`, then `id`) | Seen |
| `tableaus[].title` | The view's name | Seen |
| `tableaus[].urn`, `deleted`, `type` (`DEFAULT` on the default view only) | Not read | Seen |
| A bare list instead of an object | Accepted by `rows_in` | Assumed |

### Fields a view can show or filter by

`GET /api/v3/workspaces/{id}/tableaus` with `Accept: application/vnd.autodesk.plm.meta+json` (`META`). Seen as a **bare list**, not an object (`parse_available`, `parse_titles`).

| Key | Meaning | Status |
| --- | --- | --- |
| `[].field.__self__` | `/api/v3/workspaces/343/views/1/fields/NUMBER`. `field_key` takes the tail `views/1/fields/NUMBER`, because two sections can both have a `TITLE`. | Seen |
| `[].field.title` | The field's title in views | Seen |
| `[].field.type.title`, `type.link`, `value`, `defaultValue`, `isSystemField` | Not read (`type.title` is `Alpha Numeric` for the descriptor) | Seen |
| `[].group.displayName`, `group.name`, `group.displayOrder` | Section name (`displayName` first) and the order sections are shown in | Seen |
| `[].group.label`, `group.section` | Not read | Seen |
| `[].allowMultipleFilters` | Whether the column takes more than one filter | Seen |
| `[].applicableFilters[]` | `link` (`/api/v3/filter-types/2`), `name`, `allowValue` (boolean), `valueType` (`STRING`, absent when `allowValue` is false), `label` (not read) | Seen |

### One view (META)

`GET /api/v3/workspaces/{id}/tableaus/{view}` with the `META` type (`parse_columns`, `save_view_filters`, `rename_view`). Seen as an object. The same object is `PUT` back to save.

| Key | Meaning | Status |
| --- | --- | --- |
| `name` | The view's name (the list calls it `title`). `rename_view` changes it. | Seen |
| `isDefault`, `description`, `createdDate`, `modifiedDate`, `showOnlyDeletedRecords`, `owner`, `workspace`, `urn`, `__self__` | Sent back unchanged | Seen |
| `columns[]` | The view's columns | Seen |
| `columns[].field`, `group`, `allowMultipleFilters`, `applicableFilters` | As in the list above | Seen |
| `columns[].displayOrder` | Order of the columns, ascending | Seen |
| `columns[].sort` | `{order, direction}`, `direction` `DESCENDING` seen. `_arrange_columns` writes `ASCENDING`. | Seen (`DESCENDING`); `ASCENDING` Assumed |
| `columns[].appliedFilters` | `{matchRule: "ALL", filters: [{type: "/api/v3/filter-types/2", value: "24"}]}`. Absent when the column has no filter. `matchRule` `ANY` is read. | Seen (`ALL`); `ANY` Assumed |
| `columns[].visible` | Written (`true`) by `create_view` and `_arrange_columns` | Assumed |
| Answer to the `PUT` | Status 204, no body | Seen |

### Rows of a view

`GET /api/v3/workspaces/{id}/tableaus/{view}?page=1&size=50` (`parse_rows`). Seen as an object.

| Key | Meaning | Status |
| --- | --- | --- |
| `items` | The rows of this page | Seen |
| `items[].item.link` | `/api/v3/workspaces/343/items/17150`; the item id is the number after `/items/` (`item_id_of`) | Seen |
| `items[].fields[].id` | The field id (`PRIORITY`). Rows name fields by id only; titles come from the META list above. | Seen |
| `items[].fields[].value` | A string. An image field holds the picture number as a string (`"1283"`). A formula field holds HTML, escaped (`&lt;span ...`). A picklist or link value as an object with `title` is handled by `display_text`. | String forms Seen; object form Assumed (not in this log) |
| `items[].fields[].type.title` | `Image` marks a picture cell; `Single Line Text`, `Alpha Numeric` also seen | Seen |
| `total` | Count of all rows of the view | Seen |
| `pageNumber`, `pageSize` | Not read. In every logged answer `pageSize` was 1 with `total` 1 (a one-row view), so do not rely on `pageSize`. | Seen |
| `items[].item.urn`, `deleted`; `fields[].urn`, `isSystemField`, `systemField` | Not read | Seen |

### Lessons

| Lesson | Evidence |
| --- | --- |
| A view definition is read and written with the `META` content type, and the view is sent back whole. A `415` answer to it is treated as an error and not retried. | Assumed: the code (`send_json(..., content_type)`) and `tests/test_tableaus.py` (`refuse_meta` answers 415). No real 415 is in the log; the real `PUT` answered 204. |
| Some lists come back as an object holding the list, others as a bare list (the `META` list of fields, the validators link). Use `rows_in` and do not guess the shape. | Seen, as in the tables above |

## Reusing it

To show another workspace's rows:

1. In Python, write a `PickerReads` subclass like `ProductReads` whose workspace comes from its own settings, and register actions that call `TableauService(client).views`, `.columns` and `.rows` (plus `.image` for pictures). Do not add a second reader of `/tableaus`: put new reads in `tableaus.py`.
2. In JavaScript, the table code (`drawRows`, `paintHeader`, `cellOf`, `pumpPictures`, column widths) is private to the `products-page.js` closure, and `filters.js` looks up the ids of the Products page (`products-view-panel` and others). Move the table into a shared module and give `filters.js` its elements as parameters; do not paste them into a second page.
3. Keep the contracts the table depends on: `{columns, rows: [{id, cells, html}], total, raw}` for rows, and `{id, key, title, filters, applied}` for the header.

To change what a view shows or filters, call `save_view_filters`; do not `PUT` a view yourself, because the definition has to be read fresh and sent back whole.
