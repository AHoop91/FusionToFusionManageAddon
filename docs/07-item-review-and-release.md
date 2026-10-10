---
title: Item Review & Release
---

# 7. Item Review & Release

The **Item panel** lets you review an item's Fusion Manage record next to the design it came from, so you can check a publish and see where the item stands in its lifecycle without switching to the browser.

> **Release happens in Fusion Manage.** The panel is for reviewing. It does not move an item through its workflow. When an item is ready to be released, use the **Open in browser** button in the panel header to jump to the item in Fusion Manage and run the workflow transition there.

## Open the Item panel

- Select a component and choose **Fusion Manage ▸ Item ▸ Open Fusion Manage Item**, or right-click the component and choose **Open Fusion Manage Item**.
- With nothing selected, the panel shows the item of the open design (or, in a drawing, of the design the drawing shows).

The add-in looks the item up in the Items workspace by the component's part number. The panel is drawn by the add-in from the item's own sections and fields, so it needs no separate web sign-in. **The panel follows your selection:** while it is open, selecting another component shows that component's item.

**[Screenshot: the Item panel showing the Item tab]**

If no item has the number, the panel says **No item exists for …** and suggests checking the part number or publishing the item first. If you may not view the workspace, it tells you so.

## Header

| Control | What it does |
|---|---|
| Title and status line | The item's title and its type and life-cycle line. |
| **Open in browser** | Opens the item in Fusion Manage in your web browser. |
| **Refresh** | Reads the item again from Fusion Manage. |
| **Actions** (⋯) | Uploads the technical representation: **Upload STEP File** in a design, or the drawing PDF in a drawing. See [Technical Representation](06-technical-representation.md). |

## Tabs

The tabs are named as Fusion Manage names them and show a count where there is one. A tab your user or workspace does not have is hidden, and one you may not use is disabled. Tabs other than **Item** are read from Fusion Manage the first time you open them.

| Tab | Shows |
|---|---|
| **Item** | The item's sections and fields as label and value, and matrices as grids. Sections can be collapsed. Images show as thumbnails; click one to enlarge it. |
| **Files** | Attached files with a type icon, sortable by any column. Empty state: *No files attached*. |
| **Bill of Materials** | The item's lines as a tree, with the same columns as Fusion Manage's own BOM view, a **Views** selector and a column chooser. |
| **Where Used** | The assemblies that hold the item, as a tree. Expand a parent to read the next level up. Empty state: *Not used in any assembly*. |
| **Associated Workflows** | The workflow items, such as change orders, that reference the item, with each one's current state and its last workflow step: when, by whom, the action taken and any comments. |

## A review routine

After publishing:

1. Open the item and check the **Item** tab fields against the design.
2. Check **Files** for the STEP file or drawing PDF you attached.
3. Check **Bill of Materials** against the design BOM you published.
4. Check **Where Used** to confirm the item sits in the right assembly.
5. Check **Associated Workflows** to see whether a change order already covers the item and where it is.
6. Use **Open in browser** to send the item for release in Fusion Manage.

## Required permission

Reading an item needs **View Items** in the Items workspace. Without it the panel shows *Insufficient permissions to view the Items workspace.*
