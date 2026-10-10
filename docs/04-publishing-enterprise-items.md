---
title: Publishing Enterprise Items
---

# 4. Publishing Enterprise Items

Publishing creates or updates the Fusion Manage items for a design and every component in it, then synchronises their BOMs.

## Before you start

- You are signed in and the Items workspace is configured ([Installation and Authentication](02-installation-and-authentication.md), [Manufacturing Data Model](03-manufacturing-data-model.md)).
- The design is saved and its components have part numbers. The part number becomes the item number.
- Your Fusion Manage user holds the permissions listed in the Items workspace: View Items, Add Items, Edit Items, View BOM, Add To BOM and Edit BOM. Otherwise the panel shows a "no access" message naming what is missing.

## Open the Publish panel

With the design open, choose **Fusion Manage ▸ Item ▸ Publish Fusion Manage Item**, or right-click the top-level component and choose **Publish Fusion Manage Item**. The right-click entry is offered for the root component only, because publishing always starts from the top of the design.

The panel shows the design's thumbnail and summary, and below it the **Bill of Materials** of the design compared with Fusion Manage. Click a row to open the **Details Panel** beside it, which lists each property, the Fusion Manage field it maps to, its current value in Fusion Manage and what publishing will do.

**[Screenshot: Publish Item panel with the BOM and the Details Panel open]**

### Property status in the Details Panel

| Status | Meaning |
|---|---|
| **New** | No item exists in Fusion Manage yet; publishing creates it. |
| **Update** | The Fusion Manage value differs; publishing changes it. |
| **Up to date** | The values already match. |
| **Choose item** | Several Fusion Manage items have this number; pick the right one. |
| **Error** | Fusion Manage could not be read for this item. |

Properties with no mapping are listed as not published. Mapped properties are listed first so you see what will change.

## Publish

1. Review the BOM and details. **Refresh** reads the design and Fusion Manage again.
2. Optionally use **Add Items** to include existing Fusion Manage items in the BOM (see [BOM Synchronisation](05-bom-synchronisation.md)).
3. Click **Publish**. The button is enabled once the BOM has loaded.

A progress dialog appears. You can close it; the run continues in the background and you can keep working in Fusion, even in another design. Use **Cancel publish** to stop: items already processed are kept in the run's folder, the rest are not published.

### What a run does

1. Reads each item's properties from the Data Model and compares them with Fusion Manage (up to five items at once).
2. Downloads the thumbnail, where the thumbnail is mapped to a field.
3. Writes a request file for each item, then sends it: a `POST` creates an item, a `PATCH` updates one.
4. Once **every** item exists, sends the BOM changes of each parent assembly. BOMs go last so that new parents and children already have IDs.

When the run ends you get a message box with **Total Items Processed**, **Total Items Created** and **Total Items Updated**, and, for any failure, the item and the reason.

## Job Queue

**Fusion Manage ▸ Administration ▸ Job Queue** lists every run, one row per item, newest first. Runs go through a single queue, one after another. The ribbon button shows whether runs are working or have failed. Each failed row carries the full reason.

- **Clear finished** removes finished runs. A run that finished with every item done removes itself.
- **Send to Fusion Manage** sends a folder you choose (see below).

**[Screenshot: Job Queue with a completed and a failed run]**

## Request files and retrying

Every run keeps its files, in a `publishes` folder in your user profile (see [Troubleshooting and Limitations](08-troubleshooting-and-limitations.md) for the path). Inside you will find per-item request JSON, thumbnails, the BOM requests under `bom`, a `manifest.json` summarising the run, and `send-log.json`, which records every request Fusion Manage accepted.

To retry a failed run, or to send a folder after reviewing it, click **Send to Fusion Manage** in the Job Queue and choose the folder. A confirmation shows the tenant and workspace, the items to create and update, the BOM requests, and how many requests an earlier try already sent. **What Fusion Manage already accepted is skipped**, so nothing is created twice. An item whose creation failed is not there for its BOM; the other items carry on.

> This changes real data in Fusion Manage. Check the tenant and workspace in the confirmation.

## What is and is not sent

- Mapped properties with no value in the Data Model are not sent; the run records "No value in the Data Model, not sent" with the field names.
- Properties are only ever added or changed. The add-in does not delete items.
