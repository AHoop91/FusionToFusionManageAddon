# Glossary of what is already built

Look here first when you need something. If a row names what you need, call it. If it nearly fits, extend it and say so in the commit. Only if nothing here fits, write something new, and add a row for it in the same commit.

Paths are under `src/`. A "worker thread" means a thread of our own, never Fusion's main thread. Where a topic has its own note, the last column links to it.

## Talking to Fusion Manage

| I need to | Use | Where | Note |
| --- | --- | --- | --- |
| Call the Fusion Manage REST API (read, write, download, upload) | `FmClient` (`get_json`, `get_bytes`, `put_bytes`, `send_json`); `FmApiError` for a failure | `fm/client.py` | |
| Take an id or the last part off an API link | `last_segment`, `id_of` | `fm/client.py` | |
| Build the address of an item's page in the Fusion Manage web UI | `page_url`, `link_page`, `item_page` | `fm/pages.py` | |
| Keep a read that rarely changes for a while | `TtlCache` | `fm/ttl_cache.py` | |
| Read an answer that may be a list or an object holding the list | `rows_in`, `dict_rows`, `as_dict`, `as_list`, `dig`, `whole` | `core/shapes.py` | |
| Open any https address (cancellable) | `open_url` | `core/http.py` | |

## Reading from Fusion Manage

| I need to | Use | Where | Note |
| --- | --- | --- | --- |
| Find an item by item number | `ItemService.search` (one) or `find_many` (several, with fields) | `fm/items.py` | [finding-items.md](finding-items.md) |
| Pick one item when several share a number | `resolve_hits`, `ItemChoices` | `fm/items.py` | [finding-items.md](finding-items.md) |
| Read an item's fields | `ItemService.read`, `read_named` | `fm/items.py` | |
| Search the Items workspace with text and filters (Add Items picker) | `ItemSearchService.page`, `search_path`, `build_query` | `fm/item_search.py`, `fm/search_query.py` | [finding-items.md](finding-items.md) |
| Find the Components record for a part | `ComponentService.find_working`, `find`, `matching` | `fm/components.py` | [finding-items.md](finding-items.md) |
| Read an item's BOM, its BOM tab, or where it is used | `fm/bom.py`, `fm/bom_view.py`, `fm/where_used.py` | `fm/` | |
| Show an item as the Item tab does (header, sections, matrices) | `fm/item_view.py` | `fm/` | [workspace-forms.md](workspace-forms.md) |
| Read an item's tabs and counts, and which the user may open | `TabService` | `fm/tabs.py` | [permissions.md](permissions.md) |
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
| Compare properties, or a BOM, or one level of a BOM | `sync/property_compare.py`, `sync/bom_compare.py`, `sync/bom_levels.py` | `sync/` |
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
| Register a palette action | a `register_*_actions` function, called from `ui/actions/__init__.py` | `ui/actions/` |

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
| Tab strips | `tabs.js` | |
| A short message at the bottom | `ns.toast.show` | |
| A tooltip that shows quickly | `ns.tooltip` | |
| A progress card for an upload | `ns.uploadProgress` | |
| A report of what differs from Fusion Manage | `ns.diffReport` | |

Shared stylesheets are in `ui/web/shared/css/`: `base.css` (tokens, reset, the scrollbar), `components.css` (buttons, cards, fields), `layout.css`, `header.css`, `picker.css`, `toast.css`, `tooltip.css`, `progress.css`, `upload-progress.css`, `diff-report.css`. Use their classes and tokens; do not restyle a button or a scrollbar.

## Web: reusable pieces that live inside one page

These are built but are not yet shared, so a second page cannot call them. Move one into `shared/js/` when a second page needs it (see the notes), and do not paste it.

| Piece | Where it is | Note |
| --- | --- | --- |
| Field controls, sections, the form, the checklist | `products/js/products-page.js` | [workspace-forms.md](workspace-forms.md) |
| The table of rows, column widths, pictures, view selector | `products/js/products-page.js` | [tableaus.md](tableaus.md) |
| Filters and columns panel | `products/js/filters.js` | [tableaus.md](tableaus.md) |
| Browser checks of Fusion Manage's validators | `products/js/validators.js` (`ns.validators.check`) | [validation.md](validation.md) |
| Drag to reorder a list | `products/js/sortable.js` | [tableaus.md](tableaus.md) |
| Show Fusion Manage's own markup safely | `item/js/safe-html.js` (`ns.safeHtml.render`, also used by the Products page) | |
| The BOM table, tree, columns, filters and cells | `publish/js/bom-*.js`, `item/js/bom.js`, `item/js/tree.js` | |
| The Add Items picker | `publish/js/add-items.js` | [finding-items.md](finding-items.md) |
| Files, change log, where used, workflows | `item/js/files.js`, `change-log.js`, `where-used.js`, `associated-workflows.js` | |
| Settings: workspaces, mappings, exports, language, hub picker | `settings/js/` | |

## Keeping this glossary true

- Add a row when you build something others could reuse, and change the row when you rename or move it. Do it in the same commit.
- A row says what to call. If it needs more than a line, write or extend a note in `dev/` and link it.
- Do not list a private helper. If it is worth reusing, it is worth a public name first.
