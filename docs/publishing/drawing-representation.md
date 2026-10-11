---
title: Drawing Representation
---

# Drawing Representation

The add-in can attach a **PDF of a drawing** to the Fusion Manage item of the design the drawing shows, so the supply chain has the released drawing alongside the item.

!!! important "Uploaded by you, never automatic"
    Publishing an item does not attach a drawing PDF. Drawing PDFs are uploaded manually, so you decide which drawings go to the supply chain, and when.

A drawing is **not an item of its own**. Its PDF is attached to the item of the design's top-level component. That item must already exist; publish it first ([Item Creation](item-creation.md)).

!!! example "Screenshot placeholder: Fusion Manage ribbon tab in the Drawing workspace"
    **Show:** The Item panel with Open Fusion Manage Item and the drawing upload button.

    Save the image as `docs/images/ribbon-drawing.png`, then replace this box with `![Fusion Manage ribbon tab in the Drawing workspace](../images/ribbon-drawing.png)`.

## Upload a drawing PDF

1. Open the drawing. The add-in works out which item it belongs to from the design the drawing references: the Fusion Manage item of that design's **top-level component**, found by its part number.
2. Choose **Fusion Manage ▸ Item ▸ Upload Drawing Representation To Fusion Manage Item**, or right-click the top of the drawing's component tree and choose the same entry. In a drawing, the [Item Panel](../item-panel/index.md) **Actions** menu offers the same upload.
3. A PDF of every sheet of the drawing is created, named after the item number (for example `PN-1001.pdf`), and uploaded in a window with the stages **Find item**, **Create PDF** and **Upload**.

The right-click entry is offered only when the **top of the tree** is selected, not a component below it.

### New versions, not duplicates

If a file of the same name is already attached, the upload creates **a new version** of it instead of a duplicate.

## The drawing must be loaded

A drawing takes a moment to load. Until its design reference has loaded and the top-level component's part number can be read, the drawing button and menu entry are greyed out and the tooltip says what it is waiting for, for example *The drawing has no references yet.* or *The top-level component of … has no part number.* The add-in checks again every couple of seconds, so the button enables itself.

!!! example "Screenshot placeholder: Drawing upload button greyed out with its tooltip"
    **Show:** The disabled button and the tooltip that says what the drawing is waiting for.

    Save the image as `docs/images/drawing-greyed.png`, then replace this box with `![Drawing upload button greyed out with its tooltip](../images/drawing-greyed.png)`.

## A drawing of a different item

If the item you are attaching to is not the one the drawing shows, you are asked: *The open drawing is of X, but the item is Y. Upload this drawing as Y.pdf anyway?* Choose **Yes** only if that is what you intend.

!!! example "Screenshot placeholder: Drawing of a different item prompt"
    **Show:** The question asking whether to upload the drawing as another item's PDF.

    Save the image as `docs/images/drawing-different-item.png`, then replace this box with `![Drawing of a different item prompt](../images/drawing-different-item.png)`.

## If the PDF is empty

Fusion can report an export as successful straight after a drawing opens while writing nothing. The add-in detects this and asks you to wait for the drawing to finish loading and try again.

## Seeing the result

The PDF appears on the **Files** tab of the item in the [Item Panel](../item-panel/tabs.md#files). If the panel is open it shows a success toast and re-reads the item, so the file count updates.
