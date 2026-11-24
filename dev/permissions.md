# Permissions

What a user may do comes from two separate sources, and Fusion Manage itself has the last word on every write. Read this before you hide a button, grey out a control or check a right, so the same check is not written twice.

## The two sources

| Source | Question it answers | Where | Read with |
| --- | --- | --- | --- |
| Workspace permissions | May the user view, add or edit items, the BOM or files in one workspace? | `src/fm/permissions.py` | `GET /api/v3/workspaces/{ws}/users/@me/permissions` |
| Hub role | Is the user a Hub Admin of the active hub (who may publish languages and the Configuration File)? | `src/fusion_mfg/hub_role.py`, `src/ui/actions/hub_actions.py` | A GraphQL query to the Manufacturing Data Model |

They are unrelated. A Hub Admin can lack `add_items` in a workspace, and a user with every workspace permission can be a plain hub member. Never use one to answer the other's question.

A **validation refusal** (`{0} is required.`, status 400) is not a permission problem. See [validation.md](validation.md).

## Workspace permissions: `src/fm/permissions.py`

Permissions are used by their short name (`add_items`, not `permission.shortname.add_items`). `parse_granted` strips the prefix.

| Function | Use it to | When the read fails |
| --- | --- | --- |
| `granted(client, ws)` | Get the set of short names | Raises `FmApiError` |
| `may(client, ws, permission)` | Decide whether to show or enable one control | Returns `True` unless the status is 401 or 403. Fusion Manage still refuses what the user may not do, so a failed read must not take a right away. |
| `denial(client, ws, required, workspace_title, action)` | Get a sentence saying why the user may not do something, `""` when they may | 401 or 403 give the "not allowed" sentence; any other failure raises |
| `missing(required, held)` | List which of several permissions are absent | Not applicable (no request) |
| `title(permission)` | Show a permission's name in the user's language | Not applicable |

Constants: `VIEW_ITEMS` (without it nothing of the workspace can be seen), `ADD_ITEMS`, `ATTACH_PERMISSIONS` (find the record, attach a file, give a file a new version), and `REFUSED = (401, 403)`.

Choose between `may` and `denial` like this: `may` for a yes or no that shapes the page (fails open); `denial` when the person needs the reason or when the work must not start without the permission (fails closed on anything but a refusal).

### Where it is checked now

| Place | What it does | Call |
| --- | --- | --- |
| `src/ui/actions/product_actions.py` | `can_create` in the answer of `products_views` hides the New product button (`canCreate` in `products-page.js`) | `may(client, workspace, ADD_ITEMS)` |
| `src/publish/panel_sections.py` | Blocks publishing when the Items workspace's `required_permissions` are not all held (`publish_denial`); `publish_run_actions.py` checks again when the run starts, because a page can be open when rights change | `denial(...)` |
| `src/ui/export_dialog.py` | Turns off a file destination the user may not attach to, with the reason beside it | `denial(..., ATTACH_PERMISSIONS, ..., "attach files to")` |
| `src/ui/item_panel.py` | Reads all permissions once; without `view_items` nothing else is read and the panel says no access (`NoAccess`) | `granted` |
| `src/fm/tabs.py` | `TabService.read` marks each item tab `allowed` by `TAB_PERMISSIONS`; the page disables a tab that is not allowed (`item.js`) | The set `held` that `item_panel.py` read |
| `src/ui/actions/item_create_actions.py` | `can_create` in the answers of `items_form` and `bought_form` (the dialog of the structure viewer disables Create without it). The create itself is not blocked: Fusion Manage's refusal is what the person sees. | `may(client, workspace, ADD_ITEMS)` |
| `src/ui/actions/settings_actions.py` | `save_settings` refuses a hub member who changes the Make or buy settings (they decide the item numbers of bought items). A role that is not known yet (`pending`, `unknown`) is not a refusal: then only the page's own lock stands. A request that does not name `make_buy` keeps what is stored, so a member saving other settings cannot clear it. | `HubRoles.get()["state"]` is `member` |
| `src/fm/workspace.py` | Setup check of a workspace kind: `required_permissions` of the kind (`WorkspaceKind` in `src/config/workspace_models.py`) | `parse_granted` and `missing` on its own request |

The Items kind needs `view_items`, `add_items`, `edit_items`, `view_bom`, `add_to_bom` and `edit_bom`.

## Hub role

`read_hub_role` asks the Data Model for the user's role in the hub. Only a Hub Admin may read a hub's members, so `FHQ-403` is itself the answer "not an admin"; any other failure says nothing and gives `UNKNOWN`. `HubRoles.is_admin` (`hub_actions.py`) is what Python code calls, and it keeps an answer longer than it should expire so an open panel does not turn on an admin. The page learns the role through `get_hub_role` and `ns.settings.roleState()`; the Settings language card uses it to show or hide the publish button.

## Rules, so nothing is doubled

- Read permissions only through `src/fm/permissions.py`. Do not call `/users/@me/permissions` from anywhere else.
- Read them once per task and pass the set on. `item_panel.py` reads once and hands `held` to `TabService.read`.
- Hide or disable a control with `may`; never replace Fusion Manage's own refusal. A write that Fusion Manage refuses with 401 or 403 still has to show its message.
- Add a permission to a feature by adding it to the right tuple (`required_permissions` of a kind, `ATTACH_PERMISSIONS`, `TAB_PERMISSIONS`), not by writing a new check next to the code.
- A new permission name the user will see needs a `data.permission_<name>` key in `en.json` and a row in `title`; without it the name is shown title-cased from its short name.
- A role is not a permission. Use `is_admin` for Hub Admin questions.

## What Fusion Manage answers

**Seen** means in a real answer in the add-in log; **Assumed** means the code or a test relies on it.

`GET /api/v3/workspaces/{ws}/users/@me/permissions` (`parse_granted`): **Assumed**. The add-in log does not record these answers. The module docstring and `tests/test_permissions.py` use `{"permissions": [{"name": "permission.shortname.view_bom"}]}`, and only `permissions[].name` is read. When you see a real answer, mark it Seen here.

## Known gaps and duplication

- `fm/workspace.py` makes its own request and calls `parse_granted`, where it could call `granted`. `item_panel.py` imports `granted` as `granted_permissions` and reads the status itself. Neither is wrong, but a third copy should call `granted`, `may` or `denial`.
- The Products page only checks `add_items`. Editing a product and changing a variant link (`edit_items`) are not checked first; Fusion Manage's refusal is what the person sees. Add the check through `may` if that should change.
- `ATTACH_PERMISSIONS` and the kind's `required_permissions` are plain tuples. There is no single table of which feature needs which permission.
