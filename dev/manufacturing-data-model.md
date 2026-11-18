# Manufacturing Data Model

How the add-in reads the Manufacturing Data Model (the Data Model): what it asks, through which code, and who uses each read. The Data Model describes the designs in Fusion: components, their properties, their bill of materials (BOM) and their link to a Fusion Manage item. It is separate from Fusion Manage, which holds the items the add-in publishes to. Finding items in Fusion Manage is in [finding-items.md](finding-items.md).

All code is in `src/fusion_mfg/`.

## The client: `FusionGraphQlClient`

- It sends GraphQL through Fusion itself, to the address `mfgdm://v3`, using `adsk.core.HttpRequest`. Fusion sends the request as the signed-in user, so there is no Client ID, sign-in or access token to manage.
- `query(text, variables, label)` returns the `data` object or raises `MfgApiError`. `label` names the query in the log.
- It waits on the network, so call it from a worker thread. A warning is logged when it is called on Fusion's own thread, which it blocks.
- A cancel token is checked on every request and ends the wait (`with_cancel`). The call itself cannot be ended once made; the wait is what ends, and the answer is dropped.
- A query only reads, so it is tried up to 3 times (`ATTEMPTS`), waiting 2 s and then 4 s, when the failure is transient: HTTP 429, 502, 503 or 504, or the codes `DATA_NOT_READY` and `SUBREQUEST_HTTP_ERROR`. The timeout is 45 s.
- `MfgApiError.code` carries the service's own code, such as `FHQ-403` (not allowed). `MfgApiError.transient` says a retry was worth making.
- A query costs points: at most 1000 a query, and a page of 250 BOM relations costs 467 (comment in `model_service.py`). The cost comes back in `extensions` and is logged at debug level.

## What is read

| Read | Code | Asks for | Used by |
| --- | --- | --- | --- |
| The hub's id | `hub_lookup.read_hub_id` | `hubs { results { id name } }`, then by name (case and space ignored) | `PropertyService`, `hub_actions`, `item_numbers` |
| The user's role in the hub | `hub_role.read_hub_role` | `hub(hubId).members(filter: {name: email})`, role `ADMIN`. `FHQ-403` means "not an admin". | `hub_actions` (see [permissions.md](permissions.md)) |
| The hub's property definitions | `properties.PropertyService.list_properties` | Base and custom `PropertyDefinitionCollections`; hidden, archived and non-`COMPONENT` ones are dropped; the physical names are added | `property_actions` (the property mapping in Settings) |
| The design's summary | `model_service.read_section("summary")` | `bulkModels(input: [{modelId, time}])`: root component id, `composition`, item number, part number, name, description | `sync/up_to_date.py`, `item_numbers`, the Publish panel, `tenant_actions` |
| The design's properties | `read_section("properties")` | `allProperties(pagination: {limit: 500})` as name and display value | `sync/up_to_date.py` (through `DesignReads`) |
| One component's properties | `read_section("component")` | The same, from `component(componentId, composition, time)` | Publish panel |
| The BOM | `read_section("structure")` | `bomRelations(depth, pagination)` as a flat list of relations; `parse_structure` rebuilds the tree | Publish panel, `sync/up_to_date.py`, `item_numbers` (through `DesignReads`) |
| One level of the BOM | `read_section("level")` | The same with depth 1, under one component | Publish panel (opening an assembly) |
| A thumbnail | `read_section("thumbnail")`, `read_thumbnail_url` | `thumbnail { status signedUrl }`. The URL is short-lived, so ask when it is needed. | Item panel, export, publish |
| The linked Fusion Manage item | `read_manage_item` | `lifecycle { itemUrn itemUrl }` (the hyperlink on the Item Number in Fusion) | `tenant_actions` |
| Everything a publish needs of several components | `read_publish_components` | One query with an alias per component (`c0`, `c1`...): properties, thumbnail, link, and the physical properties when mapped | `read_ahead` |
| The design itself (name, item number, thumbnail) | `item_numbers.ItemNumbers.describe` | The summary, then the thumbnail of its root component | `products_design`, for the head of View product portfolio |
| The Data Model id of a design file | `item_numbers.FILE_MODEL_QUERY` | `item(hubId, itemId) { ... on DesignItem { tipRootModel { id timestamp } } }` | `ItemNumbers._model_of_file`, for a design that a drawing shows and Fusion has not loaded |

A saved version of a design never changes. Reads that are asked again and again are cached for the version in use: `DesignReads` (summary, structure, properties; only the last version asked about is held, reads of one version are serialised so a burst of callers makes one read) and `ItemNumbers._Remembered` (a file of found item numbers).

### The model and the time

A design is addressed by `modelId` and, to pin a saved version, `time` (`saved_at`). Both come from Fusion (`rootDataComponent.mfgdmModelId` and `.timestamp`, in `item_numbers.design_ref`). `time` is sent only when it is not empty. A component lives in a `composition` (from the summary); a read of a component needs both ids, and `_component_variables` raises while the summary has none.

### Limits and sizes

- BOM: `STRUCTURE_PAGE_SIZE` 250 relations a page (the most the service allows), `MAX_PAGES` 100, and `STRUCTURE_DEPTH` 50. A BOM that reaches either limit raises `MfgApiError` and does not return a cut-off BOM.
- Publish: `PUBLISH_BATCH` 4 components a request, 2 with physical properties. A request the service refuses for any reason except being busy is read again in halves until the bad component is alone, so one component fails by itself. A busy answer fails the batch.
- `read_ahead` runs 3 Data Model requests at once (`DATA_MODEL_REQUESTS`), as the services limit how many may be in flight.

### Physical properties (`physical.py`)

Mass, volume, area, density and the bounding box are not in `allProperties`; the Data Model works them out and `status` says when (`COMPLETED`). They are read with `primaryModel { physicalProperties }` only when a caller maps them, because they are slow. They become property rows named `Physical Mass`, `Physical Length` and so on (`PHYSICAL_NAMES` in `src/config/workspace_models.py`; a mapping source is `physical:<name>`). Fusion Manage's weight field is in kilograms, so a mass is converted from the unit the Data Model names (`KILOGRAMS_PER`); an unknown unit is logged and sent as it is.

## From a Fusion Manage item to its design

A component item of the Components workspace carries the ids of the design it was published from. This is **Seen**: the answer of `GET /api/v3/workspaces/<ws>/items/<id>` of a published component (log and paste of 2026-11-18, workspace 57).

| Key | What it holds |
| --- | --- |
| `modelId`, `componentId` | The Data Model's ids, base64url encoded. `modelId` decodes to `model~<space>~<asset>` and `componentId` to `product~<space>~<product>`. The `modelId` of a design that is open in Fusion is the same string as `rootDataComponent.mfgdmModelId`. |
| field `SPACE_COLLECTION_ID`, `PRODUCT_URN`, `ASSET_URN` | The `<space>` part, the `<product>` part of `componentId` and the `<asset>` part of `modelId`. |
| field `LINEAGE_URN` | `urn:adsk.wipprod:dm.lineage:<id>`: the design's data file. It is the same string as `DesignRef.file_id` (the file's `dataFile.id`). |
| `fusionTeamLink` | A web address ending `/g/data/<base64url of the lineage urn>?version=<n>`. |
| field `DESIGN_THUMBNAIL` | `value.link` is a signed S3 address that expires after 300 s. |
| `version`, `versionId`, `lifecycle` | `[REV:C]`, `C` (`w` for a working version), and the state link with its `title`. `item_view.revision_and_state` reads them. |

The model id does **not** contain the file's lineage id: the two are unrelated strings (the add-in logged both for one design), so a lineage id cannot be worked out from a model id. Go through the item's `LINEAGE_URN` instead.

Fusion opens a design by its lineage id: `Application.data.findFileById(urn)` and `documents.open(file)`, on Fusion's own thread, and only for a file in the active hub. `ComponentService.design_file(link)` reads the lineage from a component item's link (the Lineage URN field; it raises when the field is missing, and does not decode `fusionTeamLink`) and `product_actions.open_design_file` opens it (the `products_design_file` and `products_open_file` actions). View product portfolio does not offer it, since the design is open there; a screen that needs it adds a menu entry that calls `openInFusion(product.component)` in `products-page.js` and the text "Open in Fusion". No query that goes from a model id to its file has been found.

## Not the Data Model

`fusion_hub_files.py` browses a hub's projects and folders and reads a file through Fusion's own data API (`adsk`), not GraphQL. It must run its calls on Fusion's main thread (`run_on_main`) and so is used by the folder browser in Settings and the Configuration File actions only.

## Adding a read

1. Put the query text and its parser next to the related ones (`model_service.py` for a model, `properties.py` for the hub's definitions). Do not write a GraphQL string in an action or a panel.
2. Parse with `as_dict`, `dig` and the helpers in `parsers.py`; do not read the raw answer in the caller.
3. Give the query a `label`.
4. Call it from a worker thread, with a cancel token.
5. If it is asked again for the same saved version, add it to `DesignReads` and do not keep a copy of your own.
6. Ask only for what you use: a query is billed by what it names, and the physical properties cost the most.

## What the Data Model answers

No Data Model answer is in the add-in log (it records timing, size and the cost in `extensions`, not the body). Every key below is **Assumed**: the code and the tests (`tests/test_components.py`, `tests/test_fusion_graphql_client.py`, `tests/test_hub_role.py` and the fixtures in `tests/hub_fixtures.py`) rely on it. When you see a real answer, mark its keys Seen and fix any difference in the code.

| Query | Keys read |
| --- | --- |
| Any | `data`; `errors[].message`, `errors[].extensions.code` and `.http.status`; top-level `extensions` (cost) |
| `hubs` | `hubs.results[].id`, `name` |
| `hub.members` | `results[].user.email`, `role`, `status` |
| `bulkModels` | `[].model.id`, `[].model.component.{id, composition, itemNumber.id, name.value, description.value, partNumber.value, allProperties.results[].{name, displayValue}}` |
| `component` | `allProperties.results[]`, `thumbnail.{status, signedUrl}`, `lifecycle.{itemUrn, itemUrl}`, `primaryModel.physicalProperties.{status, area, volume, mass, density, boundingBox.{length, height, width}}` where each measure is `{value, displayValue, definition.units.name}` |
| `bomRelations` | `pagination.cursor`; `results[].{sequenceNumber, quantityProperty.displayValue, fromComponent.id, toComponent.{id, hasChildren, itemNumber.id, name.value, description.value, partNumber.value}}` |
| `hub` definitions | `basePropertyDefinitionCollections` and `propertyDefinitionCollections`: `results[].name`, `definitions.results[].{name, specification, isHidden, isArchived, applicableEntityTypes}` |
| `item` | `... on DesignItem { tipRootModel { id timestamp } }` |

## Known gaps

These conflict with the rule in `CLAUDE.md` not to guess an answer's shape. They are listed for a decision and have not been changed.

- `parsers.py` says in its docstring that parsing is defensive, so a missing or wrongly shaped branch gives an empty value and not an error.
- `hub_lookup.find_hub_id` uses the only hub when the name matches none.
- `read_ahead.py` says an item whose search found nothing "falls back to asking for itself".
- `item_numbers._Remembered` ignores a failure to read or write its file (a cache, so low risk).
