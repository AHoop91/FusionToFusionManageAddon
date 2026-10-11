---
title: Item Panel
---

# Item Panel

The **Item Panel** shows an item's Fusion Manage record inside Fusion, next to the design it came from. You can check a publish and see where an item stands in its lifecycle without switching to the browser.

!!! note "It is for reviewing"
    The panel reads the item. It does not move it through its workflow, and its only change to the item is attaching files you choose to upload. Release happens in Fusion Manage. See [Review and Release](review-and-release.md).

## In this section

| Topic | What it covers |
|---|---|
| [Tabs](tabs.md) | Item, Files, Bill of Materials, Where Used and Associated Workflows |
| [Review and Release](review-and-release.md) | A routine for reviewing after a publish, and how the item is released |

## Open the Item Panel

- Select a component and choose **Fusion Manage ▸ Item ▸ Open Fusion Manage Item**, or right-click the component and choose **Open Fusion Manage Item**.
- With nothing selected, the panel shows the item of the open design (or, in a drawing, of the design the drawing shows).

The add-in looks the item up in the Items workspace by the component's part number. The panel is drawn by the add-in from the item's own sections and fields, so it needs no separate web sign-in.

**The panel follows your selection.** While it is open, selecting another component shows that component's item.

If no item has the number, the panel says **No item exists for …** and suggests checking the part number or publishing the item first. If you may not view the workspace, it tells you so.

## Header

| Control | What it does |
|---|---|
| Title and status line | The item's title, and a line with its version, lifecycle state and Type. |
| **Open in browser** | Opens the item in Fusion Manage in your web browser. |
| **Refresh** | Reads the item again from Fusion Manage. |
| **Actions** (⋯) | Uploads the technical representation: **Upload STEP File** in a design, or the drawing PDF in a drawing. See [STEP File](../publishing/step-file.md) and [Drawing Representation](../publishing/drawing-representation.md). |

## Required permission

Reading an item needs **View Items** in the Items workspace. Without it the panel shows *Insufficient permissions to view the Items workspace.*
