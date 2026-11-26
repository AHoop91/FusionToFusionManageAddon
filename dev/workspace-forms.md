# Workspace forms

How a Fusion Manage workspace becomes a form in a panel, from the API read to the control on screen. The Python side works for any workspace id. The JavaScript side is the controls in `src/ui/web/shared/js/form-controls.js` (`ns.formControls`, shared) and the layout in `src/ui/web/products/js/products-page.js` (see [Reusing it](#reusing-it)).

The exact keys of every answer mentioned here are in "What Fusion Manage answers" below.

## The flow

1. The page calls `ask('products_form', {})`. `ProductReads.form` in `src/ui/actions/product_actions.py` runs `WorkspaceFormService(client).form(workspace, automatic)` on a worker thread, and the page polls `products_status` for the answer.
2. `WorkspaceFormService.form` (`src/fm/workspace_form.py`) reads two things at once: `GET /api/v3/workspaces/{id}/fields` and the sections (`SectionService.layouts(workspace_id, True)`, read fresh). It then reads the options of every fixed picklist the fields use (`_options`, four at a time) and calls `parse_form`.
3. `parse_form` walks the sections in order. For each one it builds the field specs (`_FieldSpecs.spec`) and the matrices (`_matrix`). A section with nothing to fill in is left out, and a field that two sections name stays in the first.
4. The page draws the answer with `paintForm`: a card per section, a line per field, a table per matrix.

An edit of an existing product also calls `products_item` (`ProductService.read`, a `{field id: value}` map) and fills each control with `setFieldValue`.

## Sections (`src/fm/sections.py`)

| Piece | What it does |
| --- | --- |
| `SectionService.layouts(workspace_id, fresh=False)` | `{section id: section}` as the workspace lays it out: its `fields`, its `matrices`, its title and `collapsed`. Reads `/sections` once, asking for the bulk list (`BULK`), which holds every section with its fields and matrices. Kept for a few minutes (`TtlCache`) unless `fresh`. |
| `SectionService.field_sections(workspace_id)` | `{field id: section link}`, for the write side (`item_request` groups values by section). Fields inside matrices count. The first section to name a field wins. Raises `FmApiError` when no section holds any field. |

## Field specs (`_FieldSpecs.spec`, `_kind`)

`_FieldSpecs.spec` (through `_describe`, `_info_spec` and `_control_spec`) returns `None` (the field is not on the form) when the field is missing from the fields answer, was already placed, is hidden (`not_shown` in `src/fm/item_view.py`), or is computed (`is_computed` in `src/fm/workspace.py`: `formulaField` or `derived` is true). A field with `editability` of `NEVER` becomes an `info` field if it has a `description` (Fusion Manage shows the item number this way), else it is left out. A field with no control (`_kind` gives `None`) is left out, added to `left_out` and written to the log.

`_kind` chooses the control in this order:

1. Has `picklistFieldDefinition` and a picklist: `links` if the type title contains "multi", else `link`.
2. Its picklist was read (is a key of `options`): `radio` if the type title contains "radio", else `select`.
3. Type title contains "image": `image`.
4. The first match of the type title (lower case) in `_KINDS`: paragraph gives `textarea`; check gives `checkbox`; integer gives `integer`; float, currency, decimal and number give `number`; date gives `date`; text, alpha, url, email and phone give `text`.

A fixed picklist that could not be read is missing from `options`, so a "Single Selection" field falls through to step 4 and is left out. `WorkspaceService.options` answers an empty list on any error, so that failure is logged but not raised.

The spec the JavaScript receives:

| Key | Type | Meaning |
| --- | --- | --- |
| `id` | string | Field id (`TITLE`). The key of the value the form sends. |
| `title` | string | The field's `name`, else its id. |
| `kind` | string | One of `text`, `textarea`, `integer`, `number`, `date`, `checkbox`, `radio`, `select`, `link`, `links`, `image`, `auto`, `info`. |
| `required` | boolean | A validator named `required` (any case) is in `fieldValidators`. Always false for `auto` and `info`. |
| `description` | string | The field's `description`. For `auto` it is the text "Filled in automatically when the product is assigned." |
| `options` | list | `[{value, title}]` for `select` and `radio` (`value` is the option's link); else empty. |
| `lookup` | string | The picklist name (the last segment of `picklist`) for `link` and `links`; else empty. The page searches it through `products_options`. |
| `max_length` | number | For `text` and `textarea`: the smaller positive of the `maxlength` validator and `fieldLength`; 0 means no limit. |
| `validators` | list | `[{name, variables}]` for the browser to check: every validator except `required` and `maxlength`, with variables as strings. See [validation.md](validation.md). |

A section is `{title, fields: [spec], matrices: [matrix], collapsed}`; `title` is the section's `title`, else its `name`. A matrix (`_matrix`) is `{columns: [string], labels: [string], rows: [[spec or null]]}`. A row or column with nothing to fill in is dropped. The column names come from the layout (`COLUMN_KEYS` in `item_view.py`) when it names every column, else from the titles of the first filled field in each column. The row labels come from `ROW_KEYS`, else they are empty. `parse_form` returns `{sections, left_out}`.

## Automatic fields

`form(workspace_id, automatic)` takes a set of field ids the add-in fills in itself. `_automatic` is applied inside `_FieldSpecs.spec` and turns the spec of each into `kind: "auto"` with nothing required, no options and no validators. The page shows a disabled box with the description and never sends a value. The Assign Product panel passes the Primary Component field (`ProductReads._automatic`, from `cfg.component_field`). A field is only turned automatic if it first survives `_describe`, so a hidden or computed id in the set has no effect.

## The Grid tab (`grid_form`)

`WorkspaceFormService.grid_form(workspace_id, link_column)` builds `{fields: [spec]}` from `GET /api/v3/workspaces/{id}/views/13/fields` (`GRID_VIEW` in `workspace.py`). Differences from `form`:

- A grid column's `validators` is a link and its `fieldValidators` is null, so `_with_validators` reads each link (four at a time) and puts the answer into `fieldValidators` before `_FieldSpecs.spec` runs.
- `link_column` (the column that links the row to its component) is left out, and `info` fields are dropped from the result.
- There are no sections and no `automatic`.

`ProductReads.variant_form` registers it as `products_variant_form`.

## What `src/fm/workspace.py` gives a form

| Function | Use |
| --- | --- |
| `WorkspaceService.options(lookup)` | All options of a fixed picklist (100 per call, at most 2000, ordered by title), as `[{value, title}]`. An item of a workspace carries its version after its title (`[REV:w]`). |
| `WorkspaceService.options_page(lookup, offset, limit, text)` | One page of a picklist, narrowed by text: `{options, total, raw}`. Serves the `link` and `links` pickers (`PickerReads.options`, 50 per page). |
| `WorkspaceService.fields(base, path)` and `_field` | The field list shaped for the Settings mapping picker (`link_lookup` is the lookup of a link field). The form does not use it; it reads the raw rows. |
| `is_computed(row)`, `GRID_VIEW` | Used by `workspace_form.py`. |

## The controls (`control(field)` in `shared/js/form-controls.js`)

`ns.formControls.make({ask, failure, openLightbox, actions})` answers one form's worth of controls (a page makes one: `products-page.js` calls it `fc`). `ask(action, payload, done)` sends a request to Python, `failure(answer)` words a refusal, `openLightbox(src)` shows a picture large, and `actions` (optional) renames the two requests the controls make (`options`, default `products_options`; `picture`, default `products_picture`). What it gives back:

| Name | Use |
| --- | --- |
| `control(spec)` | The input for one spec (see the table). |
| `fieldLine(spec)` | `{row, label, value}`: the line, its label (starred when `required`) and the box for the control. A tall control (`textarea`, `radio`, `image`, `links`) aligns to the top. |
| `makeRecord(spec, wrap, lookup)`, `addField(spec, wrap)` | A record `{id, title, kind, required, validators, input, wrap, error, lookup}`; `addField` also keeps it in `fields`, checks it on focus out and again as it is edited. |
| `fillLine(line, record)` | Puts the control and its error line in the line and points the label at the control. |
| `valueOf(record)`, `setFieldValue(record, raw, wanted)` | Read the value out (below) and put a held value in. `wanted()` says whether a picture answer is still wanted. |
| `showState(record)`, `collect()`, `showRefusals(messages)`, `readiness()` | Check one field and show the message under it; check all and answer `{values, first}` (blanks left out); show a refusal `{field id: text}` under each field and answer the first; count what is required, empty or wrong without marking. |
| `lookupField(id)`, `fields`, `reset()` | The other field a check looks at; the records; forget them. |
| `autoBox`, `infoIcon`, `aimable`, `watchFocus` | The disabled box of an `auto` field; the round "i"; whether a label can point at the control; the check on focus out. |

The texts come from the existing `products.*` keys.

| `kind` | Control | Value the form reads (`valueOf`) |
| --- | --- | --- |
| `text` | `input` type text | Trimmed string |
| `textarea` | `textarea`, two rows | Trimmed string |
| `integer`, `number` | `input` type number (step 1, step any) | Trimmed string |
| `date` | `input` type date | `YYYY-MM-DD` string |
| `checkbox` | `input` checkbox | `true`, or `''` when unticked |
| `radio` | Radio group, all options in view | The chosen option's `value`, else `''` |
| `select` | `selectPicker`: the shared picker, searchable from 8 options, first entry clears | The option's `value`, else `''` |
| `link` | `linkPicker`: the shared picker with a `source` that asks `products_options` | `{link}`, else `''` |
| `links` | `linkPicker` with `multi` (chips) | `[{link}]`, else `''` |
| `image` | `imagePicker`: drop zone, preview, 5 MB limit | Data URL. A picture the product already holds is shown but not sent again. |
| `auto` | `autoBox`: disabled box with the description | None (not a record) |
| `info` | The line with an info icon | None |

A control with `max_length` is wrapped by `counted`, which sets `maxLength` and shows a count of characters used against the limit. Every picker is `ns.picker.make` (see [pickers.md](pickers.md)); do not write another.

`paintForm` (still in `products-page.js`) marks required fields with a star in the label (`fieldLine`), and in a matrix cell with a tooltip. Textarea, radio, image and links lines align to the top. A `description` shows as an info icon beside the field. A section whose `collapsed` is true starts folded. The search box and "required only" tick above the form hide fields through `applyFormFilters`.

Each field becomes a record (`makeRecord`): `{id, title, kind, required, validators, input, wrap, error, lookup}`. `formFields` holds them all, and `lookupField(id)` lets one validator see the value of another.

Checking and the live footer:

- `showState(record)` runs `ns.validators.check` and shows the message under the field. It runs when a non-empty field loses focus, as an invalid field is edited, and for every field on Save.
- `readiness()` looks at the whole form without marking fields: required fields still empty, plus fields whose value fails a check. `refreshFooter` shows the count, and enables Save only when it is zero and nothing is being sent. The footer button opens the checklist (`paintChecklist`), whose entries jump to the field (`goTo`).
- `create` collects `valueOf` for each field (blanks are left out), and sends `products_create`, or `products_update` when editing. `refused(answer)` shows what Fusion Manage said (see [validation.md](validation.md)).

## The wizard Details step

The Assign Product wizard asks for the columns of the Variants grid when a row is added. `loadVariantFields` asks `products_variant_form` once and keeps the specs in `variantSpecs`. `paintVariantFields` builds each line with the same `fieldLine`, `makeRecord` and `fillLine` as the form, so a column gets the same controls, star, counter and checks. Differences: `auto` and `info` fields are skipped, the lookup is `noOtherField` (a grid column has no other field to compare with), and the footer is replaced by `syncAssign`, which enables the Next button when every column passes `ns.validators.check` (or is blank and not required). `confirmAssign` sends the non-blank values as `row`.

## What Fusion Manage answers

**Seen** means the key is in a real answer written to the add-in log (`%LOCALAPPDATA%\MfgToFm\logs\MfgToFm.log` and its `.1`, `.2` and `.3` rotations, read on 2026-11-17, workspace 343 "Products" and workspace 57). **Assumed** means the code or a test relies on it but no logged answer shows it; treat it as a guess until it is seen. Do not add a key you have not seen. Where the code accepts an answer as a list or as an object holding the list, it goes through `rows_in(data, key)` (`src/core/shapes.py`).

### Fields of a workspace and of its Grid tab

`GET /api/v3/workspaces/{id}/fields` and `GET /api/v3/workspaces/{id}/views/13/fields` (`WorkspaceFormService.form`, `grid_form`). The Grid answer is seen as an object `{__self__, fields: [...]}`. For `/fields` the log keeps only the rows, so whether it is an object or a bare list is not known; the code accepts both.

| Key | Meaning | Status |
| --- | --- | --- |
| `fields[].__self__` | `/api/v3/workspaces/343/views/1/fields/NUMBER` (the Grid's are `views/13/fields/...`); the field id is its last segment | Seen |
| `name` | The field's label | Seen |
| `description` | Text about the field; a non-editable field with one is shown (`info`) | Seen (`"The item number will automatically be assigned"`) |
| `type.title` | `Single Line Text`, `Paragraph`, `Date`, `Image`... `_kind` matches words in it. Only `Single Line Text`, `Paragraph` and `Date` are in the log. | Seen for those three; others (`Integer`, `Float`, `Check Box`, `Radio Button`, `Single Selection`, `Pick List`, `Multiple Selection`) Assumed from the tests |
| `fieldLength` | Number or null | Seen |
| `editability` | `ALWAYS` or `NEVER` | Seen |
| `visibility` | `ALWAYS` in every logged row; `not_shown` also treats other values as hidden | `ALWAYS` Seen; others Assumed |
| `derived` | Boolean (`False` in every logged row) | Seen |
| `formulaField` | `is_computed` reads it as well as `derived`. It is seen on view columns, not on these rows. | Assumed on these rows |
| `picklist` | Null, or a link such as `/api/v3/lookups/CUSTOM_LOOKUP_WS_COMPONENTS_ALL_INCLUDING_WORKING`; the lookup name is its last segment | Seen |
| `picklistFieldDefinition` | Null, or a link string (`/api/v3/workspaces/57/views/1/fields/DESCRIPTOR`) for a field whose items are another workspace's. The code only tests that it is truthy. | Seen |
| `validators` | On a Grid column: a link (`/api/v3/workspaces/343/views/13/fields/TITLE/validators`) or null. On the workspace's own rows it is the same link or null. | Seen |
| `fieldValidators` | On the workspace's rows: a list (`[]` or `[{validatorName, variables, __self__, urn}]`). On a Grid column: null. | Seen |
| `fieldValidators[].validatorName` | `required`, `maxlength` seen; `date` seen on a Grid column | Seen |
| `fieldValidators[].variables` | `{}` or `{"maxlength": "10000"}` (values are strings) | Seen |
| `required` (a boolean on the field) | Not read. A test puts it on a row; no real row in the log has it. | Not seen |
| `displayOrder`, `displayLength`, `unitOfMeasure`, `fieldPrecision`, `defaultValue`, `visibleOnPreview`, `label`, `gridFieldAggregationInfo` | Not read | Seen |

The validators link of a Grid column answers a **bare list** (seen, in an older version of the code's log): `[{"__self__": ".../validators/2284", "urn": ..., "validatorName": "required", "variables": {}}]`. `_with_validators` reads it with `dict_rows`.

### Picklist options

`GET /api/v3/lookups/{name}?offset=&limit=&filter=&asc=title&desc=` (`WorkspaceService.options`, `options_page`).

| Key | Meaning | Status |
| --- | --- | --- |
| `items[].link` | The option; sent back as `{link}` | Assumed |
| `items[].title` | The option's label | Assumed |
| `items[].version` | For items of a workspace: `[REV:w]` and the like, put after the title | Assumed (a value of it is in `item.version` of a Grid row, see below) |
| `totalCount` | Count of all options; a page is read until it is reached or comes back empty | Assumed |

### Sections of a workspace

`GET /api/v3/workspaces/{id}/sections` with `Accept: application/vnd.autodesk.plm.sections.bulk+json` (`SectionService._details`) answers every section with its fields and matrices in one list. Without that header the same path lists only each section's `link`, `urn` and `title`, so it is never asked without it. Seen in a real answer (workspace 242, Items): the keys below, marked **Seen**.

| Key | Meaning |
| --- | --- |
| List | **Seen**: a bare list of sections, each with its fields and matrices |
| `__self__` | **Seen**: the section's link; its last segment is the section id. (`urn` is there too.) |
| `name` | **Seen**: the section's title. `description`, `type`, `sectionType`, `displayOrder` are there too. |
| `fields[]` | **Seen**: references `{link, urn, title, type}`, `type` being `FIELD`; the field id is the last segment of `link`. A matrix is listed here too, as `{link, urn, type: "MATRIX"}` with no title. |
| `matrices[]` | **Seen**: `{__self__, width, height, columnNames, rowNames, fields}` |
| `matrices[].fields` | **Seen**: rows of field references, one list for each row |
| `matrices[].columnNames`, `rowNames` | **Seen**: plain strings. `item_view.py` also tries other key names (`COLUMN_KEYS`, `ROW_KEYS`), which this answer does not need. |
| `collapsed` | **Seen**: a section starts folded only when it is `true` |

### Rows of a Grid tab of an item

`GET /api/v3/workspaces/{id}/items/{item}/views/13/rows` (`ProductService`). Seen as an object.

| Key | Meaning | Status |
| --- | --- | --- |
| `rows[].rowData[]` | The cells of a row | Seen |
| `rowData[].__self__` | For the row id cell: `.../views/13/rows/2` (its `title` is `Row Id`, `value` is `2`). For a column: `.../items/17150/views/13/fields/SKU`. | Seen |
| `rowData[].title`, `type.title`, `value` | A column's label, type and value. A link column's value is `{link, title, version, urn, deleted}` (`version` is `[REV:w]`). | Seen |

Writing a row: `POST /api/v3/workspaces/{id}/items/{item}/views/13/rows` (and `PUT .../rows/{row}`) with the JSON **object** `{"rowData": [{"__self__": "/api/v3/workspaces/343/views/13/fields/BOM", "value": {"link": "/api/v3/workspaces/57/items/15722"}}]}`. A successful `POST` answered 201 with no body (seen).

### Lessons

| Lesson | Evidence |
| --- | --- |
| A row is posted as an object `{"rowData": [...]}`. The same row wrapped in a list (`[{"rowData": [...]}]`) is refused with `GEN_INVALID_INPUT_SCHEMA` and `Incorrect payload`; as an object it passes the schema and is checked for required columns (here `Title`). | Seen: at 16:52 on 2026-11-17 the log holds two POSTs about 0.4 s apart. The first body was the object and got the validation refusal; the second was the list and got `GEN_INVALID_INPUT_SCHEMA`. The 19:28 entry is the same pair; the 13:28 entry has only the list body, refused the same way. The code now sends once. |

## Reusing it

A new feature that needs a form for another workspace:

1. In Python, subclass `PickerReads` as `ProductReads` does. Add a method that calls `self._start(token, lambda client: WorkspaceFormService(client).form(workspace_id, automatic))`, and register it with `bridge.register("<name>_form", reads.form)` in a `register_*_actions` function that `src/ui/actions/__init__.py` calls. Register `<name>_options` (inherited `PickerReads.options`) and `<name>_status` too, or the pickers and polling have nothing to ask. `automatic` is a set of field ids, empty if none.
2. Write with `ProductService.create(workspace_id, values)` and `update(workspace_id, item_id, values)` in `src/publish/products.py`. They take the workspace id and `{field id: value}`, group values by section and turn a refusal into an `FmRefused`.
3. In JavaScript, load `shared/js/picker.js`, `validators.js` and `form-controls.js` (in that order, after `dom.js` and `i18n.js`) and call `ns.formControls.make(...)`; do not copy `control`, `makeRecord`, `showState`, `readiness` or `valueOf`. `paintForm`, the matrix tables, the filters above the form and the checklist are still private to `products-page.js`; share them the same way when a second page needs them.

The Items workspace's form is read the same way for the dialog of the structure viewer (`publish/js/item-panel.js`, the second user of `ns.formControls`; see [publish-item-flow.md](publish-item-flow.md)). The Publish page loads `picker.js`, `validators.js` and `form-controls.js` and the sheet `shared/css/form-controls.css` (the control styles moved there from `products-page.css`, which still lays the controls out for its own form; the dialog stacks every line, label over control). It makes `ns.formControls.make({ask, failure, openLightbox: no-op, actions: {options: 'search_options'}})`: the panel's `ask` polls `items_status` for `items_*` and `bought_*` requests and `search_status` for `search_options`. `search_options` is `PickerReads.options` (`search_actions.py`): it reads a picklist by its name (`/api/v3/lookups/{name}`), not by workspace, so it is not tied to the Portfolio or the Items workspace and serves the Items form's pickers as it does the Add Items picker's. The bridge keeps one listener for an action, and `add-items.js` already owns the `search_*` ones, so it asks `ns.pubItemPanel.claims` first and the panel takes the answers whose token it made. The panel needs no `picture` action: a picture field is taken out of the Items form by `without`. A matrix of the form is laid out row by row as stacked fields. A copied value is put in with `setFieldValue`; an option comes from Python as its link text, so the panel gives the control `{link}` as Fusion Manage holds it; a linked item has no title in `values`, so a picker shows its link until the answer carries one.

On the Python side: `ItemCreateReads` (`src/ui/actions/item_create_actions.py`) is a `WorkspaceReads` of the Items kind, and `BoughtItems` (`src/publish/bought_items.py`) reads the form with `WorkspaceFormService.form` and writes with `ProductService.create`. It changes the form in two ways: the item number field, which Fusion Manage describes as given when the item is saved (`info`), is made a required `text` field (the add-in writes the number itself when it publishes; **not seen live**), and the fields the add-in sets (Make or buy, the source link, the number, the component link, pictures) are taken out with `without`. A value copied from an item is turned into what the form sends by `form_value`: text and date as text (a date must be `YYYY-MM-DD`), a number as text, a tick as `true`, an option as its link, a linked item as `{link}`, several as `[{link}]`, a blank as nothing; any other shape raises, it is not guessed.

Extend rather than copy:

| To add | Extend |
| --- | --- |
| A kind of field | `_KINDS` or `_kind` in `workspace_form.py`, `control` and `valueOf` in `form-controls.js`, and a row in the tables above |
| A check Fusion Manage makes | `checks` in `shared/js/validators.js` |
| A field filled in by the add-in | The `automatic` set |
| Another grid | A `grid_form`-style method; `GRID_VIEW` is the Grid tab's view id |
