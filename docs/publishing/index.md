---
title: Publishing
---

# Publishing

Publishing is how a released design becomes manufacturing items in Fusion Manage. This section covers everything the add-in sends, from creating and updating items to the BOM and the technical representations.


Items and BOMs are sent by **Publish**. STEP files and drawing PDFs are different: they are **never sent by a publish** and are uploaded one at a time by you. See [Technical representations are manual](#technical-representations-are-manual).


Runs are tracked in the [Job Queue](../job-queue/index.md), and the result can be reviewed in the [Item Panel](../item-panel/index.md).

## Before you start

- You are signed in and the Items workspace is configured ([Installation and Authentication](../getting-started/installation.md), [Workspace and Field Mapping](../configuration/index.md#workspace-and-field-mapping)).
- The design is saved and its components have part numbers. The part number becomes the item number.
- Your Fusion Manage user holds the permissions listed in the Items workspace: View Items, Add Items, Edit Items, View BOM, Add To BOM and Edit BOM. Otherwise the panel shows a "no access" message naming what is missing.

## Open the Publish panel

With the design open, choose **Fusion Manage ▸ Item ▸ Publish Fusion Manage Item**, or right-click the top-level component and choose **Publish Fusion Manage Item**. The right-click entry is offered for the root component only, because publishing always starts from the top of the design.

The panel shows the design's thumbnail and summary, and below it the **Bill of Materials** of the design compared with Fusion Manage. The thumbnail arrives a moment after the rest, so you can start on the BOM while it loads. Click a row to open the **Details Panel** beside it, which lists each property, the Fusion Manage field it maps to, its current value in Fusion Manage and what publishing will do. A row's details are read when you open it, and the design's own row reads its properties the first time you open it.

!!! example "Screenshot placeholder: Publish panel with the BOM and Details Panel open"
    **Show:** The Publish panel: thumbnail, summary, the BOM table and the Details Panel beside it.

    Save the image as `docs/images/publish-panel.png`, then replace this box with `![Publish panel with the BOM and Details Panel open](../images/publish-panel.png)`.

### Property status in the Details Panel

| Status | Meaning |
|---|---|
| **New** | No item exists in Fusion Manage yet; publishing creates it. See [Item Creation](#item-creation). |
| **Update** | The Fusion Manage value differs; publishing changes it. See [Item Update](#item-update). |
| **Up to date** | The values already match. |
| **Choose item** | Several Fusion Manage items have this number; pick the right one. |
| **Error** | Fusion Manage could not be read for this item. |

Properties with no mapping are listed as not published. Mapped properties are listed first so you see what will change.

!!! example "Screenshot placeholder: Details Panel showing New and Update properties"
    **Show:** Property rows with their Fusion Manage field, current value and status chips.

    Save the image as `docs/images/details-panel.png`, then replace this box with `![Details Panel showing New and Update properties](../images/details-panel.png)`.

## Publish

1. Review the BOM and details. **Refresh** reads the design and Fusion Manage again.
2. Optionally use **Add Items** to include existing Fusion Manage items in the BOM (see [Bill of Materials](#add-items)).
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

The run itself is shown in the [Job Queue](../job-queue/index.md), and if something fails you can send it again with [Request Files and Retry](../job-queue/index.md#request-files-and-retry).

## Technical representations are manual

A publish sends item data, the BOM and the thumbnail. It does **not** attach a STEP file or a drawing PDF. Those are uploaded manually, so you decide what goes to the supply chain, for which items, and when. See [STEP File](#step-file) and [Drawing Representation](#drawing-representation).

## What is and is not sent

- Mapped properties with no value in the Data Model are not sent; the run records "No value in the Data Model, not sent" with the field names.
- Properties are only ever added or changed. The add-in does not delete items.

## Item Creation

When a component has no item in Fusion Manage yet, publishing **creates** one.

### When an item is created

For each component in the Publish panel, the add-in searches the Items workspace for an item with the component's **item number**, which is its part number in Fusion. If nothing is found, the item is marked **New** and a publish creates it. If an item is found, see [Item Update](#item-update).

!!! example "Screenshot placeholder: Publish panel with a component marked New"
    **Show:** A BOM row or property marked New, before publishing.

    Save the image as `docs/images/item-new.png`, then replace this box with `![Publish panel with a component marked New](../images/item-new.png)`.

The search is by item number only. Make sure your workspace maps the part number to the item number field (`NUMBER` in the default mapping). See [Workspace and Field Mapping](../configuration/index.md#default-fields).

### What a new item receives

A new item is created with:

| Content | Where it comes from |
|---|---|
| Every **mapped property** that has a value | The Manufacturing Data Model, through your [field mapping](../configuration/index.md#workspace-and-field-mapping) |
| Every **static value** | Your workspace settings. Static values are set on every new item |
| The **thumbnail** | The Data Model, when the thumbnail is mapped to an image field |
| The **component link** | The Fusion Manage component for the part, when a linking field is chosen |

How values are prepared:

- **Picklist fields** receive the matching option. A value that matches no option is left out and recorded, and the rest of the item is still created. See the `Type` example in [Default fields](../configuration/index.md#the-type-field-and-its-picklist).
- **Number fields** are rounded to the precision the Fusion Manage field takes.
- **Empty values** are not sent. The run records *No value in the Data Model, not sent*, with the field names.

### Order of creation

Every component is created or updated first, **then** the BOM lines are sent. A BOM line needs both the parent and the child to exist, so BOMs always go last. See [Bill of Materials](#bill-of-materials).

If an item fails to be created, the other items carry on. The failed item's BOM is skipped, because the item is not there for it. You can retry from the [Job Queue](../job-queue/index.md#request-files-and-retry): what Fusion Manage already accepted is skipped, so nothing is created twice.

### Permission needed

Creating an item needs **Add Items** in the Items workspace.

### What does not happen

Creating an item does not attach a STEP file or a drawing PDF. Those are uploaded by you afterwards, only for the items you choose. See [STEP File](#step-file) and [Drawing Representation](#drawing-representation).

### After creation

The run reports **Total Items Created**. Open the new item in the [Item Panel](../item-panel/index.md) to check it.

## Item Update

When a component already has an item in Fusion Manage, publishing **updates** it, and only where something differs. Publishing the same design twice is safe.

### When an item is updated

The add-in searches the Items workspace for the component's item number.

| Result of the search | What happens |
|---|---|
| One item found | The item is compared with the design and updated where needed |
| No item found | The item is created. See [Item Creation](#item-creation) |
| Several items found | The status is **Choose item**. Pick the right one in the Details Panel before you publish |

### What an update sends

An update sends only what has changed:

- **Mapped properties whose values differ.** These are the ones marked **Update** in the Details Panel.
- **Static values the item does not hold yet.** A static value that is already set is left alone.
- **The component link, if the item lacks it.**
- **The thumbnail.** Images cannot be compared, so the thumbnail goes along with an update that already has a difference. It is not sent on its own.

If nothing differs, **no request is sent** and the run records *Fusion Manage already has the same values*. Such an item is not counted as updated.

Numbers are compared at the precision of the Fusion Manage field. If the field already holds the number at its precision, it is not sent again.

### What is never overwritten

An update never changes:

- **Fields you have not mapped.** Anything entered in Fusion Manage that is not part of the mapping is untouched. This is how the manufacturing information added after publishing survives a later publish.
- **The item's lifecycle state and workflow.** Fusion Manage owns them.
- **BOM lines that only Fusion Manage has.** They are kept unless you choose to remove them. See [Bill of Materials](#bill-of-materials).

!!! tip "Engineering changes"
    When a design changes after it was published, publish again. Items that still match are skipped, items that differ are updated, and what Manufacturing added in Fusion Manage is preserved.

### Choosing between several matches

If more than one Fusion Manage item has the same item number, the add-in does not guess. The row shows **Choose item** and a message such as *3 Fusion Manage items match PN-1001. Choose one.* Pick the item to update in the Details Panel. Until you do, that item cannot be published.

!!! example "Screenshot placeholder: Choose item status"
    **Show:** A row showing Choose item and the candidate items to pick from.

    Save the image as `docs/images/item-choose.png`, then replace this box with `![Choose item status](../images/item-choose.png)`.

### Permission needed

Updating an item needs **Edit Items** in the Items workspace.

### After the update

The run reports **Total Items Updated**. Open the item in the [Item Panel](../item-panel/index.md) to check the result.

## Bill of Materials

The Publish panel compares the design's BOM with the BOM already in Fusion Manage, line by line, and sends only the differences. You decide how to handle anything that is in Fusion Manage but not in the design.

### Large designs

The BOM is read from the Manufacturing Data Model a page of 250 lines at a time, so a large assembly takes a few requests, and the panel shows how many lines it has read so far. The add-in never shows part of a BOM as if it were all of it. If a design is bigger than it can read, the panel says so instead of showing a table:

- More than **25,000 lines**.
- Nested **50 levels deep or more**.
- A component that contains itself.

### How lines are compared

For each parent assembly, the lines of the design are matched to the Fusion Manage lines under that same parent by item number. Repeated item numbers pair one to one in order. Each line gets a status:

| Status | Meaning | Publishing does |
|---|---|---|
| **New** | The design has the line; Fusion Manage does not. | Adds the line. |
| **Changed** (quantity differs) | Same item, different quantity. | Updates the quantity in Fusion Manage. |
| **Match** | Same item and quantity. | Nothing. Shown as a quiet dash. |
| **Extra** (**Fusion Manage Only**) | Fusion Manage has a line the design does not. | **Keeps it** unless you choose **Remove**. |

If a parent does not exist in Fusion Manage yet, every child is **New**.

Fusion Manage often extends the design BOM with manufacturing lines such as oil or panels. For that reason lines found only in Fusion Manage are never deleted automatically.

!!! example "Screenshot placeholder: BOM table with New, Changed and Fusion Manage Only rows"
    **Show:** The BOM table with status chips, and the filter buttons above it.

    Save the image as `docs/images/bom-statuses.png`, then replace this box with `![BOM table with New, Changed and Fusion Manage Only rows](../images/bom-statuses.png)`.

### Filters

Filter buttons above the table narrow it to rows of one status, such as **New** or **Fusion Manage Only**. Each filter's tooltip explains what it shows.

### Paired rows: a replaced item

When a **New** design line and a **Fusion Manage Only** line sit under the same parent, they are shown **paired**, one above the other, each carrying the other's item number. The item number differs at that position, which may mean an item was replaced, so the add-in asks you to decide rather than guessing. For a pair you can choose:

!!! example "Screenshot placeholder: Paired rows: a replaced item"
    **Show:** A New row and a Fusion Manage Only row paired, with the Keep and Remove choices.

    Save the image as `docs/images/bom-paired-rows.png`, then replace this box with `![Paired rows: a replaced item](../images/bom-paired-rows.png)`.

- **Keep** the Fusion Manage line, which is renumbered to the end of the BOM, and add the new design line.
- **Remove** the Fusion Manage line from Fusion Manage and add the design's line.

A Fusion Manage Only line with no partner shows a single **Remove** button; click it again to go back to keeping the line. A line marked for removal is highlighted so you cannot miss it.

### Editing quantities

A quantity can be edited in the table. An edited cell shows a revert button that restores the original value.

### Add Items

**Add Items** (top right of the BOM) opens a picker that lists Fusion Manage items from the Items workspace so you can add items that are not in the design.

!!! example "Screenshot placeholder: Add Items picker"
    **Show:** The Add Items dialog with its list, filter box and some items ticked.

    Save the image as `docs/images/add-items.png`, then replace this box with `![Add Items picker](../images/add-items.png)`.

- The list loads 100 items at a time as you scroll and stays quick with thousands of items.
- Type to filter, change the sort direction, and tick the items to add. Selections survive filtering and paging. Items already staged are marked.
- Added lines appear in the BOM as **New** and can be taken out again with their own **Remove** button before publishing.

### What gets sent

Each change becomes one request against the parent item's BOM:

| Operation | Request |
|---|---|
| Add a line | `POST` to the parent's `bom-items` |
| Change a quantity | `PATCH` with the new quantity |
| Renumber a kept line | `PATCH` with the new BOM item number |
| Remove a line | `DELETE` |

They are ordered so a line is freed before another takes its number: remove, renumber, update, add.

All BOM requests are sent **after** every item exists, one parent at a time. A failure stops only that parent; the others carry on. Adding an item the BOM already has is reported by Fusion Manage as a duplicate and is recorded against that parent. See [Publishing Enterprise Items](#publishing) for retrying.

## STEP File

The add-in can attach a **STEP file** of a component to its Fusion Manage item, so the wider supply chain has a neutral 3D representation to work from.

!!! important "Uploaded by you, never automatic"
    Publishing an item does not attach a STEP file. STEP files are uploaded manually, one component at a time, so you stay in control of what is released, for which items, and when. If you never upload one, none is sent.

The item must already exist. Publish it first ([Item Creation](#item-creation)).

!!! example "Screenshot placeholder: Right-click menu: Upload STEP File To Fusion Manage Item"
    **Show:** The right-click menu of a component with the STEP upload entry.

    Save the image as `docs/images/step-context-menu.png`, then replace this box with `![Right-click menu: Upload STEP File To Fusion Manage Item](../images/step-context-menu.png)`.

### Upload a STEP file

The file is named after the item number, for example `PN-1001.step`.

1. In the Design workspace, select a component in the browser or canvas. With nothing selected, the open design's top-level component is used.
2. Do one of the following:
    - Right-click and choose **Upload STEP File To Fusion Manage Item**.
    - Open the item in the [Item Panel](../item-panel/index.md) and choose **Actions ▸ Upload STEP File**.
3. A small **Uploading STEP File** window shows three stages: **Find item**, **Create STEP** and **Upload**, with a percentage where one can be measured.
4. When it finishes you see a confirmation: `<name> was attached to the item in Fusion Manage`, or `A new version of <name> was uploaded to the item in Fusion Manage`.

#### New versions, not duplicates

If a file of the same name is already attached, the upload creates **a new version** of it instead of a duplicate, and the confirmation says so. You can refresh a STEP file as the design changes without cluttering the item.

!!! example "Screenshot placeholder: Upload confirmation"
    **Show:** The confirmation that the file was attached, or that a new version was uploaded.

    Save the image as `docs/images/step-uploaded.png`, then replace this box with `![Upload confirmation](../images/step-uploaded.png)`.

### Which geometry is exported

The STEP file contains the **selected component**, not the whole design.

- If the selected component is the design's **top-level component**, the whole design is exported.
- Otherwise the add-in finds the component by part number in the open design and exports just that.
- If Fusion cannot export it directly from the open design, the add-in falls back to the component's own document.

Finding a component by part number can take a while in large designs. The progress window stays responsive and you will see the percentage move.

!!! example "Screenshot placeholder: Uploading STEP File progress window"
    **Show:** The small window with the Find item, Create STEP and Upload stages and the percentage.

    Save the image as `docs/images/step-progress.png`, then replace this box with `![Uploading STEP File progress window](../images/step-progress.png)`.

### Messages you may see

- **Open the design to publish as a STEP file first.** No design is open.
- **No component with part number … in the open design.** The selected component's part number is not found, for example because the part number is empty.
- **No item exists for …** The part number has no item in Fusion Manage. Publish the item first.
- **Fusion could not export the STEP file.** Fusion refused the export; the message lists each method that was tried.

Only one upload runs at a time. Starting another reports that a file is already being uploaded.

### Seeing the result

The file appears on the **Files** tab of the item in the [Item Panel](../item-panel/index.md#files). If the panel is open it shows a success toast and re-reads the item, so the file count updates.

## Drawing Representation

The add-in can attach a **PDF of a drawing** to the Fusion Manage item of the design the drawing shows, so the supply chain has the released drawing alongside the item.

!!! important "Uploaded by you, never automatic"
    Publishing an item does not attach a drawing PDF. Drawing PDFs are uploaded manually, so you decide which drawings go to the supply chain, and when.

A drawing is **not an item of its own**. Its PDF is attached to the item of the design's top-level component. That item must already exist; publish it first ([Item Creation](#item-creation)).

!!! example "Screenshot placeholder: Fusion Manage ribbon tab in the Drawing workspace"
    **Show:** The Item panel with Open Fusion Manage Item and the drawing upload button.

    Save the image as `docs/images/ribbon-drawing.png`, then replace this box with `![Fusion Manage ribbon tab in the Drawing workspace](../images/ribbon-drawing.png)`.

### Upload a drawing PDF

1. Open the drawing. The add-in works out which item it belongs to from the design the drawing references: the Fusion Manage item of that design's **top-level component**, found by its part number.
2. Choose **Fusion Manage ▸ Item ▸ Upload Drawing Representation To Fusion Manage Item**, or right-click the top of the drawing's component tree and choose the same entry. In a drawing, the [Item Panel](../item-panel/index.md) **Actions** menu offers the same upload.
3. A PDF of every sheet of the drawing is created, named after the item number (for example `PN-1001.pdf`), and uploaded in a window with the stages **Find item**, **Create PDF** and **Upload**.

The right-click entry is offered only when the **top of the tree** is selected, not a component below it.

#### New versions, not duplicates

If a file of the same name is already attached, the upload creates **a new version** of it instead of a duplicate.

### The drawing must be loaded

A drawing takes a moment to load. Until its design reference has loaded and the top-level component's part number can be read, the drawing button and menu entry are greyed out and the tooltip says what it is waiting for, for example *The drawing has no references yet.* or *The top-level component of … has no part number.* The add-in checks again every couple of seconds, so the button enables itself.

!!! example "Screenshot placeholder: Drawing upload button greyed out with its tooltip"
    **Show:** The disabled button and the tooltip that says what the drawing is waiting for.

    Save the image as `docs/images/drawing-greyed.png`, then replace this box with `![Drawing upload button greyed out with its tooltip](../images/drawing-greyed.png)`.

### A drawing of a different item

If the item you are attaching to is not the one the drawing shows, you are asked: *The open drawing is of X, but the item is Y. Upload this drawing as Y.pdf anyway?* Choose **Yes** only if that is what you intend.

!!! example "Screenshot placeholder: Drawing of a different item prompt"
    **Show:** The question asking whether to upload the drawing as another item's PDF.

    Save the image as `docs/images/drawing-different-item.png`, then replace this box with `![Drawing of a different item prompt](../images/drawing-different-item.png)`.

### If the PDF is empty

Fusion can report an export as successful straight after a drawing opens while writing nothing. The add-in detects this and asks you to wait for the drawing to finish loading and try again.

### Seeing the result

The PDF appears on the **Files** tab of the item in the [Item Panel](../item-panel/index.md#files). If the panel is open it shows a success toast and re-reads the item, so the file count updates.
