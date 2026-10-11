---
title: STEP File
---

# STEP File

The add-in can attach a **STEP file** of a component to its Fusion Manage item, so the wider supply chain has a neutral 3D representation to work from.

!!! important "Uploaded by you, never automatic"
    Publishing an item does not attach a STEP file. STEP files are uploaded manually, one component at a time, so you stay in control of what is released, for which items, and when. If you never upload one, none is sent.

The item must already exist. Publish it first ([Item Creation](item-creation.md)).

!!! example "Screenshot placeholder: Right-click menu: Upload STEP File To Fusion Manage Item"
    **Show:** The right-click menu of a component with the STEP upload entry.

    Save the image as `docs/images/step-context-menu.png`, then replace this box with `![Right-click menu: Upload STEP File To Fusion Manage Item](../images/step-context-menu.png)`.

## Upload a STEP file

The file is named after the item number, for example `PN-1001.step`.

1. In the Design workspace, select a component in the browser or canvas. With nothing selected, the open design's top-level component is used.
2. Do one of the following:
    - Right-click and choose **Upload STEP File To Fusion Manage Item**.
    - Open the item in the [Item Panel](../item-panel/index.md) and choose **Actions ▸ Upload STEP File**.
3. A small **Uploading STEP File** window shows three stages: **Find item**, **Create STEP** and **Upload**, with a percentage where one can be measured.
4. When it finishes you see a confirmation: `<name> was attached to the item in Fusion Manage`, or `A new version of <name> was uploaded to the item in Fusion Manage`.

### New versions, not duplicates

If a file of the same name is already attached, the upload creates **a new version** of it instead of a duplicate, and the confirmation says so. You can refresh a STEP file as the design changes without cluttering the item.

!!! example "Screenshot placeholder: Upload confirmation"
    **Show:** The confirmation that the file was attached, or that a new version was uploaded.

    Save the image as `docs/images/step-uploaded.png`, then replace this box with `![Upload confirmation](../images/step-uploaded.png)`.

## Which geometry is exported

The STEP file contains the **selected component**, not the whole design.

- If the selected component is the design's **top-level component**, the whole design is exported.
- Otherwise the add-in finds the component by part number in the open design and exports just that.
- If Fusion cannot export it directly from the open design, the add-in falls back to the component's own document.

Finding a component by part number can take a while in large designs. The progress window stays responsive and you will see the percentage move.

!!! example "Screenshot placeholder: Uploading STEP File progress window"
    **Show:** The small window with the Find item, Create STEP and Upload stages and the percentage.

    Save the image as `docs/images/step-progress.png`, then replace this box with `![Uploading STEP File progress window](../images/step-progress.png)`.

## Messages you may see

- **Open the design to publish as a STEP file first.** No design is open.
- **No component with part number … in the open design.** The selected component's part number is not found, for example because the part number is empty.
- **No item exists for …** The part number has no item in Fusion Manage. Publish the item first.
- **Fusion could not export the STEP file.** Fusion refused the export; the message lists each method that was tried.

Only one upload runs at a time. Starting another reports that a file is already being uploaded.

## Seeing the result

The file appears on the **Files** tab of the item in the [Item Panel](../item-panel/tabs.md#files). If the panel is open it shows a success toast and re-reads the item, so the file count updates.
