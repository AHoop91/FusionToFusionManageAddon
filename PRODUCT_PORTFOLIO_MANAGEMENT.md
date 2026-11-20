# Product Portfolio Management: how it works

This document describes everything the Product Portfolio Management feature does on the branch `feature/product-portfolio-management`, as the code stands now. Nothing here is committed yet. Where something is untested or undecided, it says so in the last section.

## 1. What the feature is for

A designer has a design open in Fusion. In Fusion Manage, a **product** is an item in the Portfolio Management workspace. That workspace is not hard-coded: it is whichever workspace the administrator chooses in the settings (see section 2). The feature lets the designer, without leaving Fusion:

1. Browse the products in the portfolio workspace, using the same views, columns and filters as Fusion Manage.
2. Create a new product, using a form built from the workspace's own sections and fields.
3. Edit an existing product.
4. Assign the open design to a product, as the product's **Primary Component** or as a **variant** in its Variants grid.
5. Manage the shared views (create, rename, delete) and each view's filters and columns.

The entry point is an **Assign Product** button in the merged item panel of the ribbon, in the Design and Drawing workspaces. It opens a 1100 by 720 palette.

## 2. Settings and gating

### Settings tab

There is a **Portfolio Management** tab in the add-in settings (`src/ui/web/settings`, built by `workspaces.js`). It is laid out like the Items tab. It holds:

| Setting | What it does |
|---|---|
| On/off switch | Turns the whole feature off. Everything else on the tab is greyed out while it is off. |
| Workspace | The Fusion Manage workspace that holds products. It is picked by id only, with no field mapping and no default values. Any workspace of the tenant is offered, not just revision-controlled ones. |
| Primary component field | The field of a product that links to the component (for example `CUSTOM_LOOKUP_WS_COMPONENTS_...`). It is the field Assign sets. |
| Variants linking column | The column of the product's Grid tab that links each row to a component. |

**Where the values come from.** Nothing about the workspace is hard-coded in the add-in. The workspace id, the Primary component field and the Variants linking column are all saved in the add-in configuration from this tab (or from the Shared Configuration, when one is in use). At runtime:

| Value | Saved as | Read by |
|---|---|---|
| Workspace id | `workspaces["portfolio"].workspace_id` | `ProductReads._workspace()` in `product_actions.py`. Every action goes through `_in_workspace`, which answers "not set up" if it is empty. |
| Primary component field | `workspaces["portfolio"].component_field` | `assign` in `product_actions.py`, passed to `ProductService.assign`. It is also the field the form shows as disabled. |
| Variants linking column | `workspaces["portfolio"].variants.link_column` | `assign` in `product_actions.py`, passed to `ProductService._add_variant`. |
| On/off | `workspaces["portfolio"].enabled` | `_in_workspace`, and `portfolio_setup_problem()` for the ribbon gate. |

Different tenants have different workspace ids, so the same add-in works in each once the administrator picks the workspace. The component picklist a field links to is found by its name, which starts with `CUSTOM_LOOKUP_WS_COMPONENTS` (`COMPONENT_LOOKUPS` in `workspace_models.py`).

A busy overlay ("Validating workspace...") shows while the workspace is checked. The settings can be locked by the Shared Configuration, in which case they cannot be changed in the tab.

Code: `WorkspaceKind("portfolio", ...)` in `src/config/workspace_models.py`, `VariantsConfig` (the link column), and `WorkspaceConfig.enabled`. The Python side reads the settings with `portfolio_setup_problem()` in `config_service.py`.

### When the button works

`SetupGate` greys out the ribbon command (`needs_portfolio=True`) until:

- the feature is turned on, and
- a workspace is chosen and valid.

If it is off, the reason shown is "Product Portfolio Management is turned off in the settings." If no workspace is chosen, it is "The Portfolio Management workspace is not set up. Choose it in Preferences."

The Items workspace is not needed to use it.

### Workspace layout check

`src/fm/workspace_schema.py` can check that a workspace has the tabs and fields a kind needs (`WorkspaceSchema` and `FieldNeed`). The Portfolio kind has **no schema right now**, so nothing is checked beyond the workspace id. To add a check, give the kind a `WorkspaceSchema` in `WORKSPACE_KINDS`; the add-in then logs the layout of the workspace ("Layout of workspace ...") when it validates one, so the required fields can be taken from the log.

## 3. The Assign Product panel

The panel is a palette (`src/ui/web/products/index.html`) driven by `products-page.js`, `filters.js`, `validators.js` and `sortable.js`. It signs in first, and shows the sign-in screen if needed.

### The list

- A header with a **Create New Product** button, a **view dropdown**, a **Refresh** button, a **Filters** button and a **Columns** button.
- The table of rows for the chosen view. It reads 50 rows at a time, with Previous and Next, and a line like "N out of M total records in this view being displayed."
- The view you used last is remembered for the next opening.
- A **Compact rows** switch shrinks the row height. The choice is remembered. In compact rows, pointing at a picture shows it larger beside the pointer, and a click opens it large.
- Columns can be dragged wider.
- Picture cells load one at a time (`products_image`), so the table fills in before the pictures arrive.
- Cells can show formula text (HTML put through a sanitiser), pictures or plain text.
- The first column is the product's own name.
- Choosing a row works like a radio button. Choosing the chosen row again lets it go.
- While rows load, three bouncing balls show in the middle of the table. Errors and empty views show as a message in the table.

### Views

Views are the Fusion Manage tableaus of the workspace. **They are shared:** creating, renaming, deleting or saving filters changes the view for everyone who uses it, and the panel says so.

- **Create new view:** pick a name (30 characters at most, with a counter) and columns. Chosen columns are on the left (drag to reorder, or Alt+Up and Alt+Down, or Delete to remove). Available fields are on the right, with a search box. Created with `POST .../tableaus`.
- **Rename view:** a dialog, `PUT` of the view description with the new name.
- **Delete view:** a confirm dialog, `DELETE`. The products in it are not affected.

### Filters and columns panel

The Filters button and the Columns button both open one side panel with two tabs, **Filters** and **Columns**. Pressing the button for the tab already in view closes the panel.

- **Filters tab:** a card for each field that has a filter. A search box lists every field the view can be filtered by, grouped by section. Each card has a match rule (And/Or) and filter rows (type and value). Some columns take one filter only. A "Show column" tick makes the field a column of the view.
- **Columns tab:** the shown columns (drag to reorder, untick to hide, at least one stays) and the available columns (a searchable, grouped list). A column that has a filter on it shows a small green funnel on the right of its row. Clicking it goes to the Filters tab.
- **Save** writes the filters and the column order into the view with one `PUT` of the view description. **Cancel** or Escape closes the panel and discards the changes.
- A funnel in a column header opens a small pop-up under that column, to filter that one column.
- A green funnel next to a section or field in the Filters search list marks one that already has a filter.

### The product form

Used for both **Create New Product** and **Edit**.

- Built from the workspace's own sections and fields (`WorkspaceFormService`, `src/fm/workspace_form.py`). A field is left out when:
  - it is computed by Fusion Manage;
  - nobody can edit it;
  - it is hidden from the form; or
  - it is a kind of field the form has no control for, such as a grid of values.
- The Primary Component field is shown as disabled with a message, because the add-in fills it in when a product is assigned.
- Controls by field type:
  - text boxes, with a character counter where there is a limit;
  - picklists;
  - checkboxes;
  - link pickers, which open a searchable list that loads in batches (`products_options`) and shows the choice as a button, or as chips for several;
  - an image picker, which is a drop zone with a preview and a size limit, sent as a data URL;
  - matrix fields.
- An info icon appears beside a field that has something to say about itself.
- **Checks made before anything is sent** (`validators.js`): the `fieldValidators` that have a plain meaning are checked, such as required, email, integer and float, min and max length, range, mask, and ones that depend on another field. The rest, such as uniqueness, are left to Fusion Manage.
- **The footer** says "Loading the form...", "Ready to save." or "N to fix before you can save." Save is available only when nothing is left to fix. A checklist dialog lists every required field and everything entered that is not right, and each item jumps to its field.
- **Filters above the form** hide fields that do not match, such as "Required Fields Only" and a field search, and hide sections that are then empty.
- **Create** (`products_create`) builds one item request from the filled-in fields. A blank value is never sent. **Edit** reads the product first (`products_item`).
- **Update** (`products_update`) sends a `PATCH` of only the values that differ from what the product holds, and sends nothing if none differ. This means **an edit cannot clear a field**, because a blank is never sent.
- **When Fusion Manage refuses a write**, `fm/refusal.py` reads the answer loosely. A message is attached to the field it names, and a message that names no field is shown for the whole form. Anything not understood is shown as it was said.
- The Create button is shown according to the user's permissions: `may(client, workspace, "add_items")`. If the permissions cannot be read, the button is allowed, because Fusion Manage still refuses what the user may not do.

## 4. Assigning the open design to a product

This is the core action. **Choose a row, then press Assign** (`products_assign`).

### Finding the design's number

`OpenDesign` (`src/ui/actions/design_number.py`) takes the open design's reference on Fusion's UI thread, then resolves its **item number** on a worker thread. That number is what Fusion Manage finds the component by. If the design has no item number, the panel is told why.

### Choosing which revision

A component has one picklist option for each revision. The Manufacturing Data Model `itemUrn` is the same for the WORKING, RELEASED and PENDING versions, so the model cannot say which one to use. The add-in picks it from the picklist (`_latest_revision` in `src/publish/products.py`):

1. The **latest released revision**: the option that is not the working version (`[REV:w]`) and has the largest item id.
2. If the component has no released revision, the **working version**.

### The outcome

`ProductService.assign` reads the product's current Primary Component and decides:

| Product's Primary Component | Result | What happens |
|---|---|---|
| Empty | `assigned` | `PATCH` sets the Primary Component field to the chosen revision. |
| Already the same revision | `same` | Nothing is changed. |
| A different component | `exists` | Nothing is changed yet. The panel asks: **Replace** or **Add as variant** (or Cancel). It names the current component and the design's number. |
| After choosing Replace | `assigned` | `PATCH` replaces the Primary Component. |
| After choosing Add as variant | `variant` | A row is added to the product's Grid tab (see below). |

### Adding a variant

`POST .../items/{id}/views/GRID_VIEW/rows` adds one row. Its linking column is set to the component. The same revision is looked up in **the column's own picklist**, which can differ from the Primary Component field's picklist. If that revision cannot be found exactly once, the add stops with a message to check the settings.

### What the user sees

A clean progress dialog, "Updating product - Adding your design to the product. This only takes a moment." There is no success banner. Errors show in the panel.

Several things are checked before Python is called, each with its own message:

- no row is chosen;
- the Primary component field is not set in the settings;
- the Variants linking column is not set (for variants only);
- the mode is not recognised.

## 5. How a request travels

```
Palette JS  ->  bridge message "products_*"  ->  Python action (registered in product_actions.py)
     ^                                                   |
     |                                                   v
 polls "products_status"   <----  worker thread runs the Fusion Manage call (PickerReads._start)
```

- Fusion's palette handler never waits on the network. Each action answers "pending" with a token at once, runs on a worker thread, and the page polls `products_status` (every 300 ms) for the answer. An older answer that arrives late is dropped.
- `_in_workspace` is the wrapper every action uses. It answers at once if the feature is off or no workspace is set, and otherwise starts the work with a Fusion Manage client.
- Registered actions (`register_product_actions`): `products_views`, `_columns`, `_fields`, `_image`, `_picture`, `_filter`, `_create_view`, `_rename_view`, `_delete_view`, `_rows`, `_form`, `_options`, `_create`, `_item`, `_update`, `_assign`, `_status`.

## 6. Where the code lives

| Area | Files |
|---|---|
| Settings model | `src/config/workspace_models.py`, `config_service.py`, `problems.py` |
| Settings UI | `src/ui/web/settings/index.html`, `js/workspaces.js`, `css/workspaces.css` |
| Ribbon, gate and panel host | `Fusion Manage Item Management.py`, `src/ui/ribbon.py`, `src/ui/availability.py`, `src/core/constants.py` |
| Actions (bridge) | `src/ui/actions/product_actions.py`, `design_number.py`, `search_actions.py` (the shared `PickerReads`) |
| Create, edit, assign | `src/publish/products.py`, `item_requests.py` |
| Form model | `src/fm/workspace_form.py`, `sections.py`, `refusal.py`, `workspace_schema.py` |
| Views, rows and pictures | `src/fm/tableaus.py` |
| Permissions | `src/fm/permissions.py` |
| Panel UI | `src/ui/web/products/index.html`, `css/products-page.css`, `js/products-page.js`, `filters.js`, `validators.js`, `sortable.js` |
| Strings | `resources/languages/en.json` (`products.*`, `app.product_*`, `data.portfolio_*`) |
| Tests | `tests/test_products.py`, `test_workspace_form.py`, `test_tableaus.py`, `test_refusal.py`, `test_workspace_schema.py`, `test_portfolio_workspace.py`, `test_tableau_picture.py` |

## 7. How to run and test it

- **Python changes** need a full Fusion restart. **JS, CSS and HTML changes** only need the page reloaded.
- Tests: `uv run python -m unittest discover -s tests -t .`. The one known failure is `tests.test_paths` (DataDirError), which was there before this feature.
- The i18n tests require every key in `en.json` to be used and every `t()` key to be a literal string.

## 8. Not done, untested or undecided

**Untested live in Fusion**
- View create, rename and delete.
- The Columns panel, including the new green funnel per column.
- That `[REV:C]` is really the expected released revision for the test component.
- Clearing a field in an edit, which is not possible by design (see section 3).
- Whether "Or" in the filter match rule maps to `ANY` in Fusion Manage.
- The revision lookup for link chips in the form.

**Not filled in**
- The Portfolio kind has no schema, so there is no workspace layout check.

**Designed but not built: "Where used"**
You asked for a check, on opening the panel, of whether the open design is already on a product, including in any Variants grid. The decisions so far:
- Show it as a **Where used** tab in the Assign Product panel.
- Match by **component number**, so any revision counts.
- Search **every product in the workspace chosen in settings**, checking both the Primary Component field and the Variants grid rows.

Fusion Manage has no reverse lookup from a component to its products, so this means scanning products and reading each one's Primary Component and grid rows. It could be slow on a large portfolio. Still open: the tab layout and which tab is the default, what each row shows (product, role, revision, state), what it shows when nothing is found, and whether the scan runs when the panel opens or when the tab is opened.

**Not committed**
All of this work is uncommitted on the branch. Commit only when you ask, with no AI attribution lines.
