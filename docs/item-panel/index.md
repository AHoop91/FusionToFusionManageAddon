---
title: Item Panel
---

# Item Panel

The **Item Panel** shows an item's Fusion Manage record inside Fusion, next to the design it came from. You can check a publish and see where an item stands in its lifecycle without switching to the browser.

!!! note "It is for reviewing"
    The panel reads the item. It does not move it through its workflow, and its only change to the item is attaching files you choose to upload. Release happens in Fusion Manage. See [Review and Release](review-and-release.md).

## Tabs

Item, Files, Bill of Materials, Where Used and Associated Workflows. [Read more](tabs.md).

## Review and Release

A routine for reviewing after a publish, and how the item is released. [Read more](review-and-release.md).


## Open the Item Panel

- Select a component and choose **Fusion Manage ▸ Item ▸ Open Fusion Manage Item**, or right-click the component and choose **Open Fusion Manage Item**.
- With nothing selected, the panel shows the item of the open design (or, in a drawing, of the design the drawing shows).

The add-in looks the item up in the Items workspace by the component's part number. The panel is drawn by the add-in from the item's own sections and fields, so it needs no separate web sign-in.

**The panel follows your selection.** While it is open, selecting another component shows that component's item.

!!! example "Screenshot placeholder: Item Panel showing the Item tab"
    **Show:** The Item Panel with the header, tabs and the Item tab's sections and fields.

    Save the image as `docs/images/item-panel.png`, then replace this box with `![Item Panel showing the Item tab](../images/item-panel.png)`.

If no item has the number, the panel says **No item exists for …** and suggests checking the part number or publishing the item first. If you may not view the workspace, it tells you so.

!!! example "Screenshot placeholder: Item Panel: no item exists"
    **Show:** The empty state saying No item exists for the part number.

    Save the image as `docs/images/item-not-found.png`, then replace this box with `![Item Panel: no item exists](../images/item-not-found.png)`.

## Header

!!! example "Screenshot placeholder: Item Panel header with the Actions menu open"
    **Show:** The title, status line, Open in browser, Refresh and the Actions menu showing Upload STEP File.

    Save the image as `docs/images/item-actions.png`, then replace this box with `![Item Panel header with the Actions menu open](../images/item-actions.png)`.

| Control | What it does |
|---|---|
| Title and status line | The item's title, and a line with its version, lifecycle state and Type. |
| **Open in browser** | Opens the item in Fusion Manage in your web browser. |
| **Refresh** | Reads the item again from Fusion Manage. |
| **Actions** (⋯) | Uploads the technical representation: **Upload STEP File** in a design, or the drawing PDF in a drawing. See [STEP File](../publishing/index.md#step-file) and [Drawing Representation](../publishing/index.md#drawing-representation). |

## Required permission

Reading an item needs **View Items** in the Items workspace. Without it the panel shows *Insufficient permissions to view the Items workspace.*
