---
title: Troubleshooting and Limitations
---

# Troubleshooting and Limitations

## Sign-in problems

| Message | Cause and fix |
|---|---|
| **Client ID is required.** / **Tenant is required.** / **Callback port must be between 1024 and 65535.** / **At least one scope is required.** | Complete the **Connection** tab and save. |
| **Callback port 8765 is unavailable: …** | Another program is using the port. Choose a different **Callback port**, register the new callback URL on your APS application, and sign in again. |
| **State mismatch; sign-in rejected.** | The browser returned a redirect that does not belong to the sign-in you started, for example from an old tab. Close old sign-in tabs and click **Sign in** again. |
| **Sign-in timed out.** | No redirect arrived within 180 seconds. Sign in again and complete the browser step promptly. |
| **Sign-in cancelled.** | You clicked **Cancel**. |
| **Sign-in already in progress.** | Wait for the current attempt to end or cancel it. |
| The browser shows an error from Autodesk instead of signing in | The callback URL or Client ID does not match your APS application. The callback URL must be registered exactly as shown on the Connection tab. |
| **Not signed in.** / **Session expired; sign in again.** | The stored tokens are gone or can no longer be refreshed. Sign in again. |

## Buttons are greyed out

Hover over the button: the tooltip ends with *Not available:* and the reason.

- Messages such as *The Items workspace ID is not set.* or *Items: tick Key on one mapping so existing items in Fusion Manage can be matched.* mean the Items workspace settings are incomplete. Fix them on the **Workspaces** tab ([Workspace and Field Mapping](05-workspace-and-field-mapping.md)).
- For the drawing PDF, *The drawing has no references yet.*, *… none of the designs is loaded yet.* and *The top-level component of … has no part number.* mean the drawing is not ready. Wait for it to finish loading, or give the top-level component a part number. The add-in rechecks every couple of seconds.

## Publishing

| Message | Cause and fix |
|---|---|
| **Insufficient permissions to publish to the Items workspace. Missing: …** | Your Fusion Manage user lacks the named permissions. Ask your administrator. Publishing needs View Items, Add Items, Edit Items, View BOM, Add To BOM and Edit BOM. |
| **Could not check your permissions in Fusion Manage: …** | The permissions request failed for a reason other than being refused: check the tenant name, your network and sign-in. |
| **Set the Items workspace ID in Settings first.** | Configure the Items workspace. |
| **Could not find the Data Model id of the open design.** | The design is not saved to the cloud, or its Data Model reference is not available yet. Save the design and try again. |
| **n items match … Choose one.** (status **Choose item**) | More than one Fusion Manage item has this item number. Pick the right one in the Details Panel. |
| **No value in the Data Model, not sent: …** | A mapped property is empty in the Data Model, so the field is left alone. Fill the property in Fusion if you want it published. |
| **'…' is not an option of … in Fusion Manage, so it was not sent.** | The target field is a picklist and the value matches none of its options. Add the option in Fusion Manage or correct the value. For `Type`, make sure both picklists have the same values (see [Default fields](05-workspace-and-field-mapping.md#the-type-field-and-its-picklist)). The rest of the item is still sent. |
| A row is missing after **Add default fields** | The workspace has no field with that field ID, and defaults for missing fields are skipped without a warning. Add the field in Fusion Manage with the exact ID (see [Default fields](05-workspace-and-field-mapping.md#default-fields)), validate the workspace, and load the defaults again. |
| **No thumbnail** (*The Data Model has no thumbnail for this component yet.*) | The thumbnail has not been generated yet. Open the design and let Fusion finish processing, then publish again. |
| A "component link" step failed | No component was found for the item. Check the component-linking field and that the component exists in the picklist. The item itself is still published. |
| Some items failed and others did not | Open the **Job Queue** for the reason of each row. Fix the cause, then use **Send to Fusion Manage** on the run's folder: what Fusion Manage already accepted is skipped. |
| A request fails with `429`, `502`, `503` or `504` | Reads are retried up to three times. If it persists, wait and send the folder again. |

## Upload

| Message | Cause and fix |
|---|---|
| **No item exists for …** | Publish the item first, or check the part number. |
| **Open the design to publish as a STEP file first.** | Open a design. |
| **No component with part number … in the open design.** | The selected component has no part number, or it is not in the open design. |
| **Fusion could not export the STEP file.** | Fusion refused the export. The message lists what was tried: *occurrence*, *component* and *own document*. A component nested inside another may have no document of its own. |
| **Fusion reported the PDF as exported, but no file was written.** | The drawing had not finished loading. Wait and try again. |
| **A file is already being uploaded.** | Only one upload runs at a time. |

## Item panel

- **No item exists for …**: the part number has no item. Check it, or publish.
- **Insufficient permissions to view the Items workspace.**: you lack View Items.
- A tab is disabled or missing: your user or workspace does not provide it.

## Where files are kept

| What | Windows | macOS |
|---|---|---|
| Configuration (`config.json`) | `%APPDATA%\MfgToFm` | `~/Library/Application Support/MfgToFm` |
| Sign-in tokens | Encrypted file under `%LOCALAPPDATA%\MfgToFm` | Login Keychain |
| Logs | `%LOCALAPPDATA%\MfgToFm\logs` | `~/Library/Logs/MfgToFm/logs` |
| Publish runs (`publishes`) | `%LOCALAPPDATA%\MfgToFm\publishes` | `~/Library/Logs/MfgToFm/publishes` |

Uploads write their STEP or PDF to a temporary folder (`MfgToFm_upload` under the system temp folder) and remove it when done.

### Verbose logging

For support, you can turn on verbose logging by setting the environment variable `MFGTOFM_DEBUG=1`, or by creating an empty file named `debug.flag` in the logs folder. Restart the add-in after changing it.

!!! warning "Verbose logs may contain business data"
    Verbose logs include full request and response bodies, which may contain business data. Review them before sharing. Tokens are never written to logs.

## Limitations

- **One workspace.** Only the **Items** workspace is supported. BOMs are those of items; other workspaces are not yet handled.
- **Shared Configuration** is shown as *coming soon* and cannot be selected. Use **Export…** and **Import…** to share a setup.
- **Matching is by item number only**, taken from the component's part number. Components with no part number cannot be published or opened.
- **A drawing is not published.** Publishing starts from a design. A drawing can only have its PDF attached to the item of its design's top-level component.
- **STEP uploads one component at a time**, and the selection decides which. Large assemblies can take a while to find and export.
- **Releasing is done in Fusion Manage.** The Item panel is read-only apart from file uploads.
- **Extra Fusion Manage BOM lines are never removed automatically.** You must choose **Remove**.
- **Items are not deleted** by the add-in.
- Opening a run's folder from the Job Queue uses Windows Explorer.
- Fusion must be running to create the STEP and PDF files; a publish itself runs in the background and does not need the design to stay open.
