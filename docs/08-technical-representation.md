---
title: Technical Representation
---

# Technical Representation

Besides item data, the add-in can attach a technical representation of a design to its Fusion Manage item:

- a **STEP file** of a component, from the Design workspace;
- a **PDF** of the open drawing, from the Drawing workspace.

!!! important "Uploaded by you, never automatic"
    Publishing an item does not attach a STEP file or a drawing PDF. Representations are uploaded manually, so you stay in control of what is released to the wider supply chain, for which items, and when.

Both go to the item's attachments. If a file of the same name is already attached, the upload creates **a new version** of it instead of a duplicate, and the confirmation says so.

## Upload a STEP file

The file is named after the item number (for example `PN-1001.step`).

1. In the Design workspace, select a component in the browser or canvas. With nothing selected, the open design's top-level component is used.
2. Do one of the following:
   - Right-click and choose **Upload STEP File To Fusion Manage Item**.
   - Open the item in the Item panel and choose **Actions ▸ Upload STEP File**.
3. A small **Uploading STEP File** window shows three stages: **Find item**, **Create STEP** and **Upload**, with a percentage where one can be measured.
4. When it finishes you see a confirmation: `<name> was attached to the item in Fusion Manage`, or `A new version of <name> was uploaded to the item in Fusion Manage`.

### Which geometry is exported

The STEP file contains the **selected component**, not the whole design. If the selected component is the design's top-level component, the whole design is exported. Otherwise the add-in finds the component by part number in the open design and exports just that. If Fusion cannot export it directly from the open design, the add-in falls back to the component's own document.

Finding a component by part number can take a while in large designs. The progress window stays responsive and you will see the percentage move.

### Messages you may see

- **Open the design to publish as a STEP file first.** No design is open.
- **No component with part number … in the open design.** The selected component's part number is not found, for example because the part number is empty.
- **No item exists for …** The part number has no item in Fusion Manage. Publish the item first.
- **Fusion could not export the STEP file.** Fusion refused the export; the message lists each method that was tried.

Only one upload runs at a time. Starting another reports that a file is already being uploaded.

## Upload a drawing PDF

1. Open the drawing. The add-in works out which item it belongs to from the design the drawing references: the Fusion Manage item of that design's **top-level component**, found by its part number.
2. Choose **Fusion Manage ▸ Item ▸ Upload Drawing Representation To Fusion Manage Item**, or right-click the top of the drawing's component tree and choose the same entry.
3. A PDF of every sheet of the drawing is created, named after the item number (for example `PN-1001.pdf`), and uploaded in a window with the stages **Find item**, **Create PDF** and **Upload**.

The right-click entry is offered only when the **top of the tree** is selected, not a component below it.

### The drawing must be loaded

A drawing takes a moment to load. Until its design reference has loaded and the top-level component's part number can be read, the drawing button and menu entry are greyed out and the tooltip says what it is waiting for, for example *The drawing has no references yet.* or *The top-level component of … has no part number.* The add-in checks again every couple of seconds, so the button enables itself.

### A drawing of a different item

If the item you are attaching to is not the one the drawing shows, you are asked: *The open drawing is of X, but the item is Y. Upload this drawing as Y.pdf anyway?* Choose **Yes** only if that is what you intend.

### If the PDF is empty

Fusion can report an export as successful straight after a drawing opens while writing nothing. The add-in detects this and asks you to wait for the drawing to finish loading and try again.

## Seeing the result

Attached files appear on the **Files** tab of the item in the Item panel (see [Item Review & Release](09-item-review-and-release.md)). If the panel is open it shows a success toast and re-reads the item, so the file count updates.
