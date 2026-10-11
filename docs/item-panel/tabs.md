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

!!! example "Screenshot placeholder: Files tab"
    **Show:** Attached files with their type icons, including a STEP file and a PDF.

    Save the image as `docs/images/tab-files.png`, then replace this box with `![Files tab](../images/tab-files.png)`.

The files attached to the item, with a type icon, sortable by any column. This is where you check that a [STEP file](../publishing/step-file.md) or [drawing PDF](../publishing/drawing-representation.md) arrived. Empty state: *No files attached*.

## Bill of Materials

!!! example "Screenshot placeholder: Bill of Materials tab"
    **Show:** The BOM tree with the Views selector and column chooser.

    Save the image as `docs/images/tab-bom.png`, then replace this box with `![Bill of Materials tab](../images/tab-bom.png)`.

The item's lines as a tree, with the same columns as Fusion Manage's own BOM view, a **Views** selector and a column chooser. Use it to check the BOM you published. See [Bill of Materials](../publishing/bill-of-materials.md). Empty state: *No Bill of Materials*.

## Where Used

!!! example "Screenshot placeholder: Where Used tab"
    **Show:** The assemblies that hold the item, with a parent expanded.

    Save the image as `docs/images/tab-where-used.png`, then replace this box with `![Where Used tab](../images/tab-where-used.png)`.

The assemblies that hold the item, as a tree. Expand a parent to read the next level up. Empty state: *Not used in any assembly*.

## Associated Workflows

!!! example "Screenshot placeholder: Associated Workflows tab"
    **Show:** Workflow items such as a change order, with their state and last step.

    Save the image as `docs/images/tab-workflows.png`, then replace this box with `![Associated Workflows tab](../images/tab-workflows.png)`.

The workflow items, such as change orders, that reference the item. Each row shows the workflow item's current state and its last workflow step: when, by whom, the action taken and any comments. Empty state: *No associated workflows*.
