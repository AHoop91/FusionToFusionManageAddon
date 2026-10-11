---
title: Tabs
---

# Item Panel Tabs

The tabs are named as Fusion Manage names them and show a count where there is one. A tab your user or workspace does not have is hidden, and one you may not use is disabled. Tabs other than **Item** are read from Fusion Manage the first time you open them.

| Tab | Shows |
|---|---|
| [Item](#item) | The item's fields |
| [Files](#files) | Attached files |
| [Bill of Materials](#bill-of-materials) | The item's BOM lines |
| [Where Used](#where-used) | The assemblies that hold the item |
| [Associated Workflows](#associated-workflows) | Workflow items that reference the item |

## Item

The item's sections and fields as label and value, and matrices as grids. Sections can be collapsed. Images show as thumbnails; click one to enlarge it. Fields the workspace hides are not shown.

## Files

The files attached to the item, with a type icon, sortable by any column. This is where you check that a [STEP file](../publishing/step-file.md) or [drawing PDF](../publishing/drawing-representation.md) arrived. Empty state: *No files attached*.

## Bill of Materials

The item's lines as a tree, with the same columns as Fusion Manage's own BOM view, a **Views** selector and a column chooser. Use it to check the BOM you published. See [Bill of Materials](../publishing/bill-of-materials.md). Empty state: *No Bill of Materials*.

## Where Used

The assemblies that hold the item, as a tree. Expand a parent to read the next level up. Empty state: *Not used in any assembly*.

## Associated Workflows

The workflow items, such as change orders, that reference the item. Each row shows the workflow item's current state and its last workflow step: when, by whom, the action taken and any comments. Empty state: *No associated workflows*.
