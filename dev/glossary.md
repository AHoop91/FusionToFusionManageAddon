# Glossary of what is already built

Look here first when you need something. If a row names what you need, call it. If it nearly fits, extend it and say so in the commit. Only if nothing here fits, write something new, and add a row for it in the same commit.

Paths are under `src/`. A "worker thread" means a thread of our own, never Fusion's main thread. Where a topic has its own note, the last column links to it.

## Talking to Fusion Manage

| I need to | Use | Where | Note |
| --- | --- | --- | --- |
| Call the Fusion Manage REST API (read, write, download, upload) | `FmClient` (`get_json`, `get_bytes`, `put_bytes`, `send_json`); `FmApiError` for a failure. A read is tried up to 3 times on 429, 502, 503, 504 or no answer; a write is tried again only on 429. Both wait as `Retry-After` says, else exponentially with jitter. A write with no answer or a 5xx is never sent again by the client: `FmApiError.outcome_unknown` says so, and a publish resolves it (see `publish/sender.py`) | `fm/client.py` | |
| Log an API call without its content | `get_logger`; for an answer or request `describe_body`, `endpoint`, `new_request_id`; for a body that only a verbose log may hold `log_body`; `ALLOWED_FIELDS` is the allowlist of codes. An error with a `log_text` (`FmApiError`, `MfgApiError`) is logged as that, not as its message | `core/logging_setup.py` | |
| Wait before trying a request again | `backoff.delay(attempt, retry_after)`, `backoff.retry_after(headers)` | `core/backoff.py` | |
| Take an id or the last part off an API link | `last_segment`, `id_of` | `fm/client.py` | |
| Build the address of an item's page in the Fusion Manage web UI | `page_url`, `link_page`, `item_page` | `fm/pages.py` | |
| Keep a read that rarely changes for a while | `TtlCache` | `fm/ttl_cache.py` | |
| Read an answer that may be a list or an object holding the list | `rows_in`, `dict_rows`, `as_dict`, `as_list`, `dig`, `whole` | `core/shapes.py` | |
| Open any https address (cancellable) | `open_url` | `core/http.py` | |

## Reading from Fusion Manage

| I need to | Use | Where | Note |
| --- | --- | --- | --- |
| Find an item by item number | `ItemFinder.search` (one) or `find_many` (several, with fields) | `fm/v3_search.py` | [finding-items.md](finding-items.md) |
| Pick one item when several share a number | `resolve_hits`, `ItemChoices.resolve` | `fm/v3_search.py` | [finding-items.md](finding-items.md) |
| Pick one item when several were found by something other than their number (the MBOM items of a component) | `ItemChoices.pick` | `fm/v3_search.py` | [finding-items.md](finding-items.md) |
| Read an item's fields | `ItemService.read`, `read_named` | `fm/items.py` | |
| Search a workspace's Grid tab (the v3 search cannot) | `V1SearchService.page` or `rows`, with `build_definition` | `fm/v1_search.py` | [finding-items.md](finding-items.md) |
| Find where a design is used in the portfolio (a product's Primary Component, or a row of its Variants grid) | `ProductService.usage` (the `products_usage` action) | `publish/products.py`, `ui/actions/product_actions.py` | [finding-items.md](finding-items.md) |
| The open design's name, number and thumbnail from the Data Model, with the revision and state of its Fusion Manage item | `ItemNumbers.describe`, `item_view.revision_and_state` (the `products_design` action) | `ui/item_numbers.py`, `fm/item_view.py` | [finding-items.md](finding-items.md) |
| Open the Fusion design a Components item was published from (its Lineage URN, then `findFileById`) | `ComponentService.design_file`, `open_design_file` (the `products_design_file` and `products_open_file` actions) | `fm/components.py`, `ui/actions/product_actions.py` | [finding-items.md](finding-items.md) |
| Search the Items workspace with text and filters (Add Items picker) | `ItemSearchService.page`, `search_path`, `build_query` | `fm/v3_search.py` | [finding-items.md](finding-items.md) |
| Find the Components record of a part of the open design (its address, from the Data Model; kept for a saved version of the design) | `ItemNumbers.record_link(ref, part_number)`, which uses `read_manage_item` and `manage_link` | `ui/item_numbers.py`, `fusion_mfg/model_service.py`, `fm/components.py` | [manufacturing-data-model.md](manufacturing-data-model.md) |
| Read the Asset URN or the Lineage URN of a Components record (`identity` gives both in one read) | `ComponentService.identity`, `asset`, `design_file` | `fm/components.py` | [manufacturing-data-model.md](manufacturing-data-model.md) |
| Find the manufacturing bills of materials (MBOM) of a design, or of a component (the Item panel's lookup), or check an item number is free | `MbomService.find` (lineage and asset), `of_component` (lineage read from the component's record), `number_taken` | `fm/mbom.py` | [manufacturing-data-model.md](manufacturing-data-model.md) |
| List the options of the Component linking picklist for a number | `ComponentService.matching` | `fm/components.py` | [finding-items.md](finding-items.md) |
| Read the derived fields a linking field takes from the item it links to (sent with the link on publish) | `PivotService.derived` | `fm/pivots.py` | [publish-item-flow.md](publish-item-flow.md) |
| Read an item's BOM, its BOM tab, or where it is used | `fm/bom.py`, `fm/bom_view.py`, `fm/where_used.py` | `fm/` | |
| Read an item's whole BOM as one tree, each line with its item id and line id (the `mbom_tree` section) | `BomService.tree`, `build_tree` | `fm/bom.py`, `publish/panel_sections.py` | [publish-item-flow.md](publish-item-flow.md) |
| Read the design's whole Bill of Materials from the Data Model once for the open design, whichever MBOM is chosen (the `structure` section) | `PublishSections._structure_rows` (kept until a forced refresh, another design or other settings) | `publish/panel_sections.py` | [publish-item-flow.md](publish-item-flow.md) |
| Show an item as the Item tab does (header, sections, matrices) | `fm/item_view.py` | `fm/` | [workspace-forms.md](workspace-forms.md) |
| Read an item's tabs and counts, and which the user may open | `TabService` | `fm/tabs.py` | [permissions.md](permissions.md) |
| Read an item's tab names, counts and permission for the Publish panel, with its workspace id and urn (the `item_tabs:<id>` section), or the item laid out as the Item panel shows it, with no tabs or permissions (those are read once by `item_tabs`), and each picture of it by its link (the `item_view:<id>` and `item_picture:<link>` sections) | `PublishSections` (`_load`), `ItemService.item` (the one read of the item, which `ItemService.urn` and `ItemViewService` use), `ItemViewService.layout` (`read` is `layout` plus the tabs, for the Item panel and the product page) | `publish/panel_sections.py`, `fm/items.py` | [publish-item-flow.md](publish-item-flow.md) |
| Read an item's files, change log or associated workflows | `fm/attachments.py`, `fm/change_log.py`, `fm/associated_workflows.py` | `fm/` | |
| Read a workspace's fields, sections and picklist options | `WorkspaceService`, `SectionService` | `fm/workspace.py`, `fm/sections.py` | [workspace-forms.md](workspace-forms.md) |
| Build the form of a workspace (or its Grid tab) | `WorkspaceFormService.form`, `grid_form` | `fm/workspace_form.py` | [workspace-forms.md](workspace-forms.md) |
| Check a workspace has the layout a kind of workspace needs | `WorkspaceService.validate`, `fm/workspace_schema.py` | `fm/` | |
| List a workspace's views and read their rows, columns and filters | `TableauService` | `fm/tableaus.py` | [tableaus.md](tableaus.md) |
| Find out what the user may do in a workspace | `may`, `granted`, `denial`, `missing` | `fm/permissions.py` | [permissions.md](permissions.md) |
| Turn a refusal of a write into a message for the form and for each field | `read_refusal` | `fm/refusal.py` | [validation.md](validation.md) |
| Read the signed-in user's profile | `fm/profile.py` | `fm/` | |

## Writing to Fusion Manage

| I need to | Use | Where | Note |
| --- | --- | --- | --- |
| Create or update an item from a form | `ProductService.create`, `update` | `publish/products.py` | [workspace-forms.md](workspace-forms.md) |
| Assign a component to a product, as primary or as a variant | `ProductService.assign` (modes `variant`, `replace`, `replace_move`, `variant_update`) | `publish/products.py` | |
| Build the request that creates or updates an item, or changes its BOM | `publish/item_requests.py`, `publish/bom_requests.py` | `publish/` | |
| Send requests safely (once, logged, resumable) | `Dispatcher`, `SendRun`, `SendLog` | `publish/sender.py`, `publish/send_log.py` | |
| Fit a value to the field it is sent to (picklist link, number, unit) | `PicklistResolver.link`, `convert_unit`, `fit_number` | `fm/picklists.py` | |
| Make a manufacturing item, or a bought version of a made item (number = source number + suffix, Make or buy set, source link set, values copied, duplicates refused) | `BoughtItems`: `assembly_form`, `create_assembly`, `open`, `create_bought` (`open` is the `bought_open` action: one request that answers the bought version of an item there is already, which the dialog offers, or the form, with the `source_id` the create is then sent with) (the source is an item id, which `bought_open` takes from the Data Model's link of the EBOM line's component, or an item number found with `ItemFinder` when there is none); `plan_copy` says what is copied and skipped; `specs_of` lists the fields of a form by id and `form_value` turns a value an item holds into the shape the form sends (the `items_form`, `items_create`, `bought_open` and `bought_create` actions) | `publish/bought_items.py`, `ui/actions/item_create_actions.py` | [publish-item-flow.md](publish-item-flow.md) |
| Attach a file to an item (a new version if it is there) | `fm/attachments.py`, `ui/attachment_upload.py` | `fm/`, `ui/` | |

## The Manufacturing Data Model

| I need to | Use | Where | Note |
| --- | --- | --- | --- |
| Run a GraphQL query | `FusionGraphQlClient.query` (worker thread) | `fusion_mfg/fusion_graphql_client.py` | [manufacturing-data-model.md](manufacturing-data-model.md) |
| Read a design's summary, properties or BOM | `read_section`, or `DesignReads` for the version in use | `fusion_mfg/model_service.py`, `design_reads.py` | [manufacturing-data-model.md](manufacturing-data-model.md) |
| Read many components for a publish | `read_publish_components` | `fusion_mfg/model_service.py` | [manufacturing-data-model.md](manufacturing-data-model.md) |
| Get a thumbnail, or the Fusion Manage item a component links to | `read_thumbnail_url`, `read_manage_item` | `fusion_mfg/model_service.py` | [manufacturing-data-model.md](manufacturing-data-model.md) |
| Get the item number of a component or the design | `ItemNumbers.resolve` | `ui/item_numbers.py` | [finding-items.md](finding-items.md) |
| Find which design is open, as the Data Model knows it | `design_ref`, `active_design_ref`, `component_ref` | `ui/item_numbers.py`, `ui/actions/design_ref.py` | |
| List a hub's properties for field mapping | `PropertyService.list_properties` | `fusion_mfg/properties.py` | |
| Find a hub's id, or the user's role in it | `read_hub_id`, `read_hub_role`, `HubRoles.is_admin` | `fusion_mfg/`, `ui/actions/hub_actions.py` | [permissions.md](permissions.md) |
| Browse a hub's projects and folders, or read a file in a hub | `FusionHubFiles` (Fusion's main thread) | `fusion_mfg/fusion_hub_files.py` | |
| Get mass, volume or size of a component | `parse_physical`, `physical.py` | `fusion_mfg/physical.py` | |
| Convert a unit | `convert` | `core/units.py` | |

## Comparing the design with Fusion Manage

| I need to | Use | Where |
| --- | --- | --- |
| Compare a design or component with its item | `sync/item_compare.py` | `sync/` |
| Compare properties, or a BOM; or mark what a design's BOM cannot publish | `sync/property_compare.py`, `sync/bom_compare.py`, `sync/bom_levels.py` (`mark_design_bom`) | `sync/` |
| Say whether the item panel's tabs are up to date | `sync/up_to_date.py` | `sync/` |
| Get the item number a design or component is looked up by | `item_number_of` | `sync/item_number.py` |

## Publishing

| I need to | Use | Where |
| --- | --- | --- |
| Queue a publish and follow it | `JobQueue`, `job_state.py`, `states.py`, `watched.py` | `publish/` |
| Run a publish (write files and requests, then send) | `runner.py`, `writer.py`, `run_files.py` | `publish/` |
| Read what a run shares between items ahead of time | `ReadAhead` | `publish/read_ahead.py` |
| Fill `{{kind:argument}}` markers in requests | `placeholders.py` | `publish/` |
| Make STEP, PDF, DWG or DXF files from the open document | `exporters.py` (Fusion's UI thread) | `publish/` |
| Download a signed url, or make a thumbnail's background transparent | `download.py`, `thumbnail.py` | `publish/` |
| Say how a run ended in a message box | `reports.py`, `ui/job_alerts.py` | `publish/`, `ui/` |
| Find item numbers that more than one component carries | `shared_numbers.py` | `publish/` |

## Settings, hub and sign-in

| I need to | Use | Where |
| --- | --- | --- |
| Load, save or resolve the configuration | `ConfigService` | `config/config_service.py` |
| Model a workspace's settings (kinds, mappings, required permissions) | `WorkspaceConfig`, `WorkspaceKind` | `config/workspace_models.py` |
| Say which field is Make or buy, its two values, the source link field, the suffix of a bought item's number and (optionally) the exact fields it copies (`skip_fields`, the unticked ones of a checklist by form section; none = every field the form holds) | `MakeBuyConfig` (`WorkspaceConfig.make_buy`, Items kind), checked by its `problems` and by `_filled_twice`; edited in the Make or buy section of the Items card (`ns.makeOrBuy.buildSection`: field and source pickers, Make and Buy value pickers that are the options of the field, suffix input; its problems are found by `findMakeBuy` in `validation.js`) | `config/workspace_models.py`, `settings/js/make-or-buy.js`, `settings/js/workspaces.js`, `settings/js/validation.js` | [publish-item-flow.md](publish-item-flow.md) |
| Share settings through the hub or a network path | `config_transfer.py`, `shared_config.py`, `config_envelope.py` | `config/` |
| Know the hub, tenant and workspace a piece of work is under | `HubContext` | `config/hub_context.py` |
| Report a problem in the settings with where it is | `Problem`, `problem_payload` | `config/problems.py` |
| Keep and switch the language | `core/i18n.py`, `config/language_setting.py`, `config/hub_languages.py`, `core/language_check.py` | |
| Sign in, keep the token, build the profile | `auth/auth_service.py`, `token_store.py`, `oauth_pkce.py` | `auth/` |

## Core helpers

| I need to | Use | Where |
| --- | --- | --- |
| Cancel work that waits on the network | `CancelToken`, `TokenSlot`, `Cancelled` | `core/cancel.py` |
| Write a file whole or not at all | `write_atomically`, `replace_file` | `core/atomic.py` |
| Find where the add-in keeps its files | `data_dir`, `log_dir`, `temp_dir` | `core/paths.py` |
| Time something for the log | `Stopwatch` | `core/timing.py` |
| Log | `get_logger` | `core/logging_setup.py` |
| Show text in the user's language (Python) | `t("group.key")` with a literal key | `core/i18n.py` |

## Fusion plumbing (Python)

| I need to | Use | Where |
| --- | --- | --- |
| Show an HTML panel in a palette | `PaletteHost` | `ui/palette_host.py` |
| Let the page call Python, and Python tell the page | `MessageBridge.register`, `push` | `ui/message_bridge.py` |
| Run slow work off Fusion's thread, and let the page poll | `in_thread`, `BackgroundRead` | `ui/actions/background.py` |
| Run something on Fusion's main thread from a worker | `UiThread.post`, `run_on_main` | `ui/ui_thread.py`, `fusion_mfg/fusion_hub_files.py` |
| Switch a command off until what it needs is ready | `SetupGate`, `GateWatcher` | `ui/availability.py` |
| Add a ribbon tab or button | `ui/ribbon.py`, `ui/ui_text.py` | `ui/` |
| Show a Fusion message box | `ui/file_dialogs.py` | `ui/` |
| Read or write in the workspace of one kind from the settings, with the answer polled by token | Subclass `WorkspaceReads` (set `kind`, override `_problem`): `ProductReads` (Portfolio Management), `ItemCreateReads` (Items) | `ui/actions/product_actions.py`, `ui/actions/item_create_actions.py` | [workspace-forms.md](workspace-forms.md) |
| Register a palette action | a `register_*_actions` function, called from `ui/actions/__init__.py` | `ui/actions/` |
| Read what is selected or open in Fusion: the component of an entity, the part number of the selection or open design, its Data Model reference, what Export exports | `fusion_selection.component_of`, `selected_part_number`, `part_ref`, `active_ref`, `export_component` (the selection the right-click menu saw: `menu_selection`) | `ui/fusion_selection.py` |
| Add entries to Fusion's right-click menu | `ItemContextMenu` | `ui/item_context_menu.py` |
| Find the item number of a component on a worker thread, then act on it on the UI thread | `NumberFinder.find` with `FindOptions` | `ui/number_finder.py` |
| What the Export window reads and does: what is exported, its names, the item number read ahead, the look at the attached files, the export | `ExportPanel` (the Item panel's `exporter`) | `ui/export_panel.py` |
| The Item page's actions: tab look-ups, item loading, selection following, uploads from the Actions menu, files freshness (it opens the palette at once in its loading state, `_open_part`, and finds the item behind it; pictures are a look-up of their own, `picture_load`) | `ItemPanel` | `ui/item_panel.py` |

## Web: shared scripts (`ui/web/shared/js/`)

Every script attaches to `window.MfgUi` (`ns`). Load order is in each `index.html`.

| I need to | Use | Note |
| --- | --- | --- |
| A drop-down, combo box, searchable list or chip box | `ns.picker.make` | [pickers.md](pickers.md) |
| Call Python from the page | `bridge.js` (`bridge.send`, `bridge.on`) | |
| The panel's own wording | `ns.i18n` (`t`) with `data-i18n` in the HTML | |
| Small DOM helpers and the namespace | `dom.js` | |
| A header with logo, avatar and account card | `shell.js`, `account.js` (also the hub role pill) | |
| Sign-in and view switching | `auth.js` | |
| Tab strips | `tabs.js` (`ns.tabs.init` wires Settings'; `ns.tabs.setup(nav, buttonClass, idPrefix)` wires a strip a page builds, as Publish's details panel does) | |
| A section card that folds (a form or item section) | `ns.section.make(title, content, {folded})`, styled by `shared/css/section.css` | The Product Portfolio form, the Item panel and the workspace tabs of Settings (`foldable` in `settings/js/workspaces.js`) use it |
| One control per field of a workspace form spec, its value, required star, error line and Fusion Manage refusals | `ns.formControls.make({ask, failure, openLightbox, actions})` in `form-controls.js` (the Products page and the Publish dialog use it) | [workspace-forms.md](workspace-forms.md) |
| Browser checks of Fusion Manage's validators | `ns.validators.check` in `validators.js` | [validation.md](validation.md) |
| A short message at the bottom | `ns.toast.show` | |
| A table to choose one row from, with a search bar, column titles, a row count and arrows (Publish lists its MBOM items with it; the Item panel lists the items made from a component) | `ns.choiceTable.make({rows, titles, text, onPick})`, styled by `shared/css/choice-table.css` (it holds the structure viewer's `sv-bar`, `sv-search` and `sv-pane` too) | |
| The Export window's items: the table of choices to open on when several items are made from what is exported, then the item picked, with "Change item" to choose again | `ns.exportItems` (`show`, `state`, `selected`, `current`, `reset`, `note`, `recordUrl`; each item and the component carry their Fusion Manage page, opened with `open_url` from the Link row), fed by the `export_items` push (`ExportPanel.warm_export_items`, `AttachmentUpload.items_of`) | |
| A tooltip that shows quickly | `ns.tooltip` | |
| A progress card for an upload | `ns.uploadProgress` | |
| A report of what differs from Fusion Manage (the Item panel) | `ns.diffReport` | |

Shared stylesheets are in `ui/web/shared/css/`: `base.css` (tokens, reset, the scrollbar), `components.css` (buttons, cards, fields), `layout.css`, `header.css`, `picker.css`, `section.css`, `toast.css`, `tooltip.css`, `progress.css`, `upload-progress.css`, `diff-report.css`. Use their classes and tokens; do not restyle a button or a scrollbar.

## Web: reusable pieces that live inside one page

The pieces below are built but not yet shared, so a second page cannot call them. Move one into `shared/js/` when a second page needs it (see the notes), and do not paste it.

| Piece | Where it is | Note |
| --- | --- | --- |
| Sections, the form layout, matrices, the filters above the form, the checklist | `products/js/products-page.js` | [workspace-forms.md](workspace-forms.md) |
| The table of rows, column widths, pictures, view selector | `products/js/products-page.js`, `products/js/product-views.js` | [tableaus.md](tableaus.md) |
| Filters and columns panel | `products/js/filters.js` | [tableaus.md](tableaus.md) |
| Drag to reorder a list | `products/js/sortable.js` | [tableaus.md](tableaus.md) |
| Show Fusion Manage's own markup safely | `item/js/safe-html.js` (`ns.safeHtml.render`, also used by the Products page) | |
| The BOM tree (rows read, levels) and the data of a line | `publish/js/bom-tree.js`, `bom-model.js` (there is no table view: the structure viewer draws the lines; `pubUi.foldTools` in `ui.js` is its Collapse and Expand all) | [publish-item-flow.md](publish-item-flow.md) |
| The structure of an MBOM: the tree, its edits (move, reorder, phantom and other assemblies, add, remove, quantity), undo and redo, and the EBOM and change comparisons | `publish/js/mbom-structure.js` (`ns.mbomStructure`) | |
| The Add Items picker | `publish/js/add-items.js` | [finding-items.md](finding-items.md) |
| The dialog of the structure viewer: a modal with the Items form for a new manufacturing item (toolbar New Manufacturing Item) or a bought version of an EBOM line (row action Create bought version) | `publish/js/item-panel.js` (`ns.pubItemPanel.open({mode, sourceNumber, number})`), styles in `publish/css/item-panel.css` | [publish-item-flow.md](publish-item-flow.md) |
| The look of a workspace form's controls (lines, star, text boxes, pickers, count, pictures) | `shared/css/form-controls.css`, loaded by the Products and Publish pages | [workspace-forms.md](workspace-forms.md) |
| Turn the edited MBOM into the publish job (items and BOM operations; what it refuses is `problems`) | `publish/js/mbom-plan.js` (`ns.mbomPlan.build`), from `ns.mbomStructure.changes()` | [publish-item-flow.md](publish-item-flow.md) section 2 |
| Show the EBOM beside the editable MBOM (two panes, drag and drop, search, undo), or map an MBOM read from Fusion Manage to the EBOM by item number | `publish/js/mbom-viewer.js` (`ns.mbomViewer`; the rows of its two panes are drawn by `publish/js/mbom-viewer-draw.js`, `ns.mbomViewerDraw`), `ns.mbomStructure.mapByNumber`, `zoneOf`, `numberKey` (compare two item numbers) | [publish-item-flow.md](publish-item-flow.md) |
| Choose an assembly of the MBOM in a tree (with the line numbers 3, 3.1 and a search), or ask for one value in a small box (Set Position, Split Quantity) | `destTree`, `openValueBox`, `openSplitBox` in `mbom-viewer.js` | [publish-item-flow.md](publish-item-flow.md) |
| Split the quantity of an MBOM line between assemblies | `structure.split` (`mbom-structure.js`), `openSplitBox` in `mbom-viewer.js` | [publish-item-flow.md](publish-item-flow.md) |
| Count the EBOM lines added, with a different quantity and missing, and keep only one kind (the colour bar under the Fusion Component pane) | `drawMeter`, `statusOf`, `pickStatus`, `filterView` in `mbom-viewer.js` | [publish-item-flow.md](publish-item-flow.md) |
| Quick add: make the MBOM a copy of the EBOM (item numbers and all), asking first when Fusion Manage has lines | `structure.matchEbom` / `hasLines` (`mbom-structure.js`), `matchEbom` in `mbom-viewer.js` | [publish-item-flow.md](publish-item-flow.md) |
| Ask a yes or no before something is overridden (same dialog as Create New Manufacturing Item) | `ns.pubItemPanel.confirm({title, lead, ask, confirm, icon, onConfirm})` | `publish/js/item-panel.js` |
| Files, change log, where used, workflows (the Products and Publish pages include them; `ns.itemFiles.NO_TOOLS` is the `tools` for a page with no open document to attach from, `ns.itemFiles.open` what a click on a file does there; `ns.itemTree.labelTab(button, tab)` names an item tab's button, with its count and permission) | `item/js/files.js`, `change-log.js`, `where-used.js`, `associated-workflows.js`, `tree.js` | |
| Show the details of a line of the structure viewer (a magnifier on every line of both panes; the Overview tab with the comparison, or the no-item card with the properties that would be sent; the item's tabs, Item details (`ns.itemSections.section`) then Attachments, more to add as one entry of `ITEM_TABS`) | `publish/js/details.js` (`ns.pubDetails.open(line)`, `handleItemTabs`), `detailsLine` and `showDetails` in `publish/js/mbom-viewer.js` | [publish-item-flow.md](publish-item-flow.md) |
| Settings: workspaces, mappings, exports, language, hub picker | `settings/js/` | |

## Testing the web scripts

Paths are under `tests/js/`.

| I need to | Use | Where |
| --- | --- | --- |
| Test a script that needs a page (the DOM, events, timers) | A `*.test.js` file in `dom/`; `new PageWindow(html).window` is a real window in headless Edge or Chrome, and `run(window, src)` loads a script into it. Run `node tests/js/browser/run.mjs [files]`; the Python suite runs it and skips when no browser is found | `browser/window.js`, `browser/run.mjs`, `browser/in-page.js`, `helpers.js` |
| Test a script that needs no page (the Bill of Materials data) | A `*.test.js` file here; `dataWindow()` loads its scripts into a vm context, run by `node --test` | `helpers.js` |

## Keeping this glossary true

- Add a row when you build something others could reuse, and change the row when you rename or move it. Do it in the same commit.
- A row says what to call. If it needs more than a line, write or extend a note in `dev/` and link it.
- Do not list a private helper. If it is worth reusing, it is worth a public name first.
