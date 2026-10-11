---
title: Publishing
---

# Publishing

Publishing is how a released design becomes manufacturing items in Fusion Manage. This section covers everything the add-in sends, from creating and updating items to the BOM and the technical representations.

## What publishing covers

| Topic | What it covers |
|---|---|
| [Item Creation](item-creation.md) | What happens when no item exists yet for a component |
| [Item Update](item-update.md) | What happens when the item already exists, and what is left alone |
| [Bill of Materials](bill-of-materials.md) | Comparing and synchronising the BOM, and choosing what to keep |
| [STEP File](step-file.md) | Attaching a STEP file of a component, manually |
| [Drawing Representation](drawing-representation.md) | Attaching a PDF of a drawing, manually |

Items and BOMs are sent by **Publish**. STEP files and drawing PDFs are different: they are **never sent by a publish** and are uploaded one at a time by you. See [Technical representations are manual](#technical-representations-are-manual).

Runs are tracked in the [Job Queue](../job-queue/index.md), and the result can be reviewed in the [Item Panel](../item-panel/index.md).

## Before you start

- You are signed in and the Items workspace is configured ([Installation and Authentication](../getting-started/installation.md), [Workspace and Field Mapping](../configuration/field-mapping.md)).
- The design is saved and its components have part numbers. The part number becomes the item number.
- Your Fusion Manage user holds the permissions listed in the Items workspace: View Items, Add Items, Edit Items, View BOM, Add To BOM and Edit BOM. Otherwise the panel shows a "no access" message naming what is missing.

## Open the Publish panel

With the design open, choose **Fusion Manage ▸ Item ▸ Publish Fusion Manage Item**, or right-click the top-level component and choose **Publish Fusion Manage Item**. The right-click entry is offered for the root component only, because publishing always starts from the top of the design.

The panel shows the design's thumbnail and summary, and below it the **Bill of Materials** of the design compared with Fusion Manage. Click a row to open the **Details Panel** beside it, which lists each property, the Fusion Manage field it maps to, its current value in Fusion Manage and what publishing will do.

!!! example "Screenshot placeholder: Publish panel with the BOM and Details Panel open"
    **Show:** The Publish panel: thumbnail, summary, the BOM table and the Details Panel beside it.

    Save the image as `docs/images/publish-panel.png`, then replace this box with `![Publish panel with the BOM and Details Panel open](../images/publish-panel.png)`.

### Property status in the Details Panel

| Status | Meaning |
|---|---|
| **New** | No item exists in Fusion Manage yet; publishing creates it. See [Item Creation](item-creation.md). |
| **Update** | The Fusion Manage value differs; publishing changes it. See [Item Update](item-update.md). |
| **Up to date** | The values already match. |
| **Choose item** | Several Fusion Manage items have this number; pick the right one. |
| **Error** | Fusion Manage could not be read for this item. |

Properties with no mapping are listed as not published. Mapped properties are listed first so you see what will change.

!!! example "Screenshot placeholder: Details Panel showing New and Update properties"
    **Show:** Property rows with their Fusion Manage field, current value and status chips.

    Save the image as `docs/images/details-panel.png`, then replace this box with `![Details Panel showing New and Update properties](../images/details-panel.png)`.

## Publish

1. Review the BOM and details. **Refresh** reads the design and Fusion Manage again.
2. Optionally use **Add Items** to include existing Fusion Manage items in the BOM (see [Bill of Materials](bill-of-materials.md#add-items)).
3. Click **Publish**. The button is enabled once the BOM has loaded.

A progress dialog appears. You can close it; the run continues in the background and you can keep working in Fusion, even in another design. Use **Cancel publish** to stop: items already processed are kept in the run's folder, the rest are not published.

!!! example "Screenshot placeholder: Publish progress dialog"
    **Show:** The progress dialog with the bar, the count, and the Cancel publish and Close buttons.

    Save the image as `docs/images/publish-progress.png`, then replace this box with `![Publish progress dialog](../images/publish-progress.png)`.

### What a run does

1. Reads each item's properties from the Data Model and compares them with Fusion Manage (up to five items at once).
2. Downloads the thumbnail, where the thumbnail is mapped to a field.
3. Writes a request file for each item, then sends it: a `POST` creates an item, a `PATCH` updates one.
4. Once **every** item exists, sends the BOM changes of each parent assembly. BOMs go last so that new parents and children already have IDs.

When the run ends you get a message box with **Total Items Processed**, **Total Items Created** and **Total Items Updated**, and, for any failure, the item and the reason.

!!! example "Screenshot placeholder: Publish complete message"
    **Show:** The Publish complete message box with Total Items Processed, Created and Updated.

    Save the image as `docs/images/publish-complete.png`, then replace this box with `![Publish complete message](../images/publish-complete.png)`.

The run itself is shown in the [Job Queue](../job-queue/index.md), and if something fails you can send it again with [Request Files and Retry](../job-queue/request-files-and-retry.md).

## Technical representations are manual

A publish sends item data, the BOM and the thumbnail. It does **not** attach a STEP file or a drawing PDF. Those are uploaded manually, so you decide what goes to the supply chain, for which items, and when. See [STEP File](step-file.md) and [Drawing Representation](drawing-representation.md).

## What is and is not sent

- Mapped properties with no value in the Data Model are not sent; the run records "No value in the Data Model, not sent" with the field names.
- Properties are only ever added or changed. The add-in does not delete items.
