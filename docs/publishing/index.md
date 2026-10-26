---
title: Publishing
---

# Publishing

**What you'll do here:** turn a released design into manufacturing items in Fusion Manage, then attach STEP files and drawings.

Items and BOMs are sent by **Publish**. STEP files and drawing PDFs are different: they are **never sent by a publish** and are uploaded one at a time by you. See [Technical representations are manual](#technical-representations-are-manual).

## Quick steps

1. Open the saved design.
2. Right-click the top-level component and choose **Publish Fusion Manage Item**.
3. Check the BOM and the **New** or **Update** marks in the Details Panel.
4. Click **Publish**, and follow it in the [Job Queue](../job-queue/index.md).
5. Optional: attach a [STEP file](#step-file) or [drawing PDF](#drawing-representation).

Review the result in the [Item Panel](../item-panel/index.md).

## In this page

| Section | Read it when |
|---|---|
| [Open the Publish panel](#open-the-publish-panel) and [Publish](#publish) | You are publishing for the first time. |
| [Item Creation](#item-creation) and [Item Update](#item-update) | You want to know what is created, changed or never overwritten. |
| [Bill of Materials](#bill-of-materials) | You are comparing or editing the BOM. |
| [STEP File](#step-file) and [Drawing Representation](#drawing-representation) | You are attaching files. |

## Before you start

- You are signed in and the Items workspace is configured ([Installation and Authentication](../getting-started/installation.md), [Item Workspace](../configuration/index.md#item-workspace)).
- The design is saved and its components have item numbers. Items in Fusion Manage are matched by item number.
- Your Fusion Manage user holds the permissions listed in the Items workspace: View Items, Add Items, Edit Items, View BOM, Add To BOM and Edit BOM. Otherwise the panel shows a "no access" message naming what is missing.

## Open the Publish panel

Publishing always starts from the top of the design, so open the design first (a drawing cannot be published). There is no Publish button on the ribbon. Use either of these:

1. **From the design.** Right-click the top-level component in the browser and choose **Publish Fusion Manage Item**. The entry is offered on the top-level component only.
2. **From the Item panel.** Select the component and choose **Open Fusion Manage Item**, then do one of the following:
    - If the item is not in Fusion Manage yet, click **Publish**.
    - If it already exists, open the **Actions** (**...**) menu and choose **Republish**.
    - If the tab's pill shows **Out of date**, click it to open the report, then click **Republish**.

    The Item panel closes as the Publish panel opens.

The panel shows the design's thumbnail and summary, and below it the **Bill of Materials** of the design compared with Fusion Manage. The thumbnail arrives a moment after the rest, so you can start on the BOM while it loads. Click a row to open the **Details Panel** beside it, which shows the item, a status pill at its top right, and a table of its properties with the value in Fusion, the value in Fusion Manage and a status dot for each. Hover a dot to see what publishing will do for that property. A row's details are read when you open it, and the design's own row reads its properties the first time you open it.

![The Publish panel: the design's thumbnail and numbers, the Bill of Materials with its Fusion and Manage ticks and quantities, and the pills and Publish button at the bottom](../images/publish-panel.png){ width="900" height="465" }

### Status in the Details Panel

The pill at the top right of the Details Panel shows what publishing will do for the component:

| Status | Meaning |
|---|---|
| **New** | No item exists in Fusion Manage yet; publishing creates it. See [Item Creation](#item-creation). |
| **Update** | The Fusion Manage value differs; publishing changes it. See [Item Update](#item-update). |
| **Up to date** | The values already match. |
| **Choose item** | Several Fusion Manage items have this number; pick the right one. |
| **Error** | Fusion Manage could not be read for this item. |

Properties with no mapping are listed as not published. Mapped properties are listed first so you see what will change.

![The Details Panel beside the Bill of Materials: the Up to date pill, and each property with its value in Fusion, its value in Fusion Manage and a status dot](../images/details-panel.png){ width="900" height="466" }

## Publish

1. Review the BOM and details. **Refresh** reads the design and Fusion Manage again.
2. Optionally use **Add Existing Items** to include existing Fusion Manage items in the BOM (see [Bill of Materials](#add-existing-items)).
3. Click **Publish**. The button is enabled once the BOM has loaded.

A progress dialog appears. You can close it; the run continues in the background and you can keep working in Fusion, even in another design. Use **Cancel publish** to stop: items already processed are kept in the run's folder, the rest are not published.

The dialog shows a progress bar with the count of items done and the time elapsed, and a tally of **Successful**, **Failed** and **Pending** items.

![The progress dialog over the Publish panel: the bar at 2 of 12 items, the Successful, Failed and Pending counts, and the Cancel publish and Close buttons](../images/publish-progress.png){ width="900" height="465" }

### What a run does

1. Reads each item's properties from the Data Model and compares them with Fusion Manage (up to five items at once).
2. Downloads the thumbnail, for an item that has something to send and a thumbnail mapped to an image field.
3. Writes a request file for each item, then sends it: a `POST` creates an item, a `PATCH` updates one.
4. Once **every** item exists, sends the BOM changes of each parent assembly. BOMs go last so that new parents and children already have IDs.

When the run ends, the progress dialog turns into the result. It reads **Publish complete** when every item went through, **Completed with errors** when some failed (see the [Job Queue](../job-queue/index.md) for the reasons), **Publish cancelled** after **Cancel publish**, or **Publish failed** when the run could not finish.

![The Publish complete dialog: 12 of 12 items on a full green bar, 12 Successful, 0 Failed and 0 Pending, with a pointer to the Job Queue](../images/publish-complete.png){ width="900" height="465" }

If you closed the dialog, Fusion shows a message box instead when the run ends, with **Total Items Processed**, **Total Items Created** and **Total Items Updated**, and, for any failure, the item and the reason.

The run itself is shown in the [Job Queue](../job-queue/index.md), and if something fails you can send it again with [Request Files and Retry](../job-queue/index.md#request-files-and-retry).

## Technical representations are manual

A publish sends item data, the BOM and the thumbnail. It does **not** attach a STEP file or a drawing PDF. Those are uploaded manually, so you decide what goes to the supply chain, for which items, and when. See [STEP File](#step-file) and [Drawing Representation](#drawing-representation).

## What is and is not sent

- Mapped properties with no value in the Data Model are not sent; the run records "No value in the Data Model, not sent" with the field names.
- Properties are only ever added or changed. The add-in does not delete items, and removes a BOM line only when you choose **Remove** on it.
- A component whose item number is shared with another component is not published. See [Shared item numbers](#shared-item-numbers).

## Item Creation

When a component has no item in Fusion Manage yet, publishing **creates** one.

### When an item is created

For each component in the Publish panel, the add-in searches the Items workspace for an item with the component's **item number**. If nothing is found, the **Details Panel** shows **New** for it and a publish creates it. A design that is not in Fusion Manage at all has no status on its BOM lines, because there is nothing to compare them with. If an item is found, see [Item Update](#item-update).

The search is by item number only. Make sure your workspace maps **Item Number** to the Fusion Manage field that holds it (`NUMBER` in the default mapping). In Fusion Manage, that field must also be part of the Items workspace's item descriptor, or existing items are not found. See [The item number](../configuration/index.md#the-item-number).

### What a new item receives

A new item is created with:

| Content | Where it comes from |
|---|---|
| Every **mapped property** that has a value | The Manufacturing Data Model, through your [field mapping](../configuration/index.md#item-workspace) |
| Every **default value** | Your workspace settings. Default values are set on every new item |
| The **thumbnail** | The Data Model, when the thumbnail is mapped to an image field |
| The **component link** | The Fusion Manage component for the part, when a linking field is chosen |

How values are prepared:

- **Picklist fields** receive the matching option. A value that matches no option is left out and recorded, and the rest of the item is still created. See [Picklists](../configuration/index.md#picklists).
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
- **Default values the item does not hold.** A default value is sent again when the item's field does not hold it, so a value someone changed in Fusion Manage is set back to the default. A field already holding the default is left alone.
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

The add-in asks Fusion Manage for items whose descriptor matches the component's item number, and does not narrow the answer down itself. It uses the item when exactly one comes back. When more than one comes back it does not guess. This happens when:

- **Two items in the workspace carry the same item number.** Fusion Manage does not stop that, for example when items were created by hand or imported.
- **The search also returns items whose descriptor merely resembles the number.** The descriptor holds the number followed by other text (for example `PN-1001 - Housing`), and Fusion Manage may return other descriptors for the same search.

In that case the status is **Choose item**, with a message such as *3 Fusion Manage items match PN-1001. Choose one.* You can pick the item in the Details Panel. If you have not, clicking **Publish** stops before anything is sent and asks **Which item do you mean?**, with the items listed under each shared number. Choose one for each and click **Publish** again to carry on. **Cancel** sends nothing. The choice is used for that run and the Details Panel remembers it while the panel stays open.

The [Item Panel](../item-panel/index.md#when-several-items-share-the-number) asks in the same way, and remembers the item you pick. The Publish panel's choice is its own: picking an item in one does not pick it in the other. The right-click STEP upload, the drawing upload and the Export window use the Item panel's choice; when several items match and none was chosen they stop with a message and attach nothing.

A BOM line of an assembly that matches several items is left without a status for the same reason. Fix it by removing the duplicate in Fusion Manage, or choose the item in the Details Panel.

### Permission needed

Updating an item needs **Edit Items** in the Items workspace.

### After the update

The run reports **Total Items Updated**. Open the item in the [Item Panel](../item-panel/index.md) to check the result.

## Bill of Materials

The Publish panel compares the design's BOM with the BOM already in Fusion Manage, line by line, and sends only the differences. You decide how to handle anything that is in Fusion Manage but not in the design.

### Large designs

The panel reads the BOM one level at a time, so a large assembly opens quickly. At first it shows the design and the lines directly under it. Click an assembly's chevron to read the lines under it: a spinner replaces the chevron and grey rows hold the place until they arrive. If one assembly cannot be read, its rows show **Could not read this level** with a **Retry** button, and the rest of the table stays.

**Expand all** reads every level that is not read yet and opens everything; **Collapse all** closes every assembly except the design itself.

**Publish covers what is open.** It publishes the design and the lines of every assembly you have opened, exactly as the table shows them, and nothing under a closed assembly. The pills at the bottom left count what that is, and update as you open and close assemblies:

| Pill | Counts |
|---|---|
| **Items** | The design and every component in view: each is checked against Fusion Manage when you publish, and created or updated where it differs. |
| **Lines Skipped** | Lines with no item number (and what is below them): nothing is published for them. |
| **Shared Item Numbers** | Lines whose item number another component also carries (and what is below them): see [Shared item numbers](#shared-item-numbers). |
| **Sub Assemblies Skipped** | Closed sub assemblies in view. What is under them is not published; open them, or use **Expand all**, to include them. |

A line that needs a choice (**Review**) holds **Publish** back only while it is in view.

Each read is made a page of 250 lines at a time, and the panel shows how many lines it has read so far. The add-in never shows part of a BOM as if it were all of it. The filter counts and the check button cover only the levels read so far, and say so. If a design is bigger than the add-in can read, the panel says so instead of showing a table:

- More than **25,000 lines**.
- Nested **50 levels deep or more**.
- A component that contains itself.

### How lines are compared

For each parent assembly, the lines of the design are matched to the Fusion Manage lines under that same parent by item number. Repeated item numbers pair one to one in order. Each line gets a status:

| Status | Meaning | Publishing does |
|---|---|---|
| **New** | The design has the line; Fusion Manage does not. | Adds the line. |
| **Update** | Same item, different quantity. | Updates the quantity in Fusion Manage. |
| *(no chip)* | Same item and quantity. | Nothing. |
| **Fusion Manage Only** | Fusion Manage has a line the design does not. | **Keeps it** unless you choose **Remove**. |
| **Added** | You picked the item with [Add Existing Items](#add-existing-items). | Adds the line to the end of the Fusion Manage BOM. |
| **Skipped** | The component has no item number, shares one with another component, or sits below such a line. | Nothing: no item is created and no BOM line is added. |

If an assembly inside the design does not exist in Fusion Manage yet, every child of it is **New**. If the design itself is not in Fusion Manage, its lines show no status: the panel says publishing creates the design, and does not look up every component. When you publish, each component is searched for by item number, an item that exists is used, and one that does not is created.

Fusion Manage often extends the design BOM with manufacturing lines such as oil or panels. For that reason lines found only in Fusion Manage are never deleted automatically.

Each line reads **Item Number - Part Name**. A component with no item number is **Skipped**: no item can be created for it. Its quantity box is greyed out and cannot be edited, and the **i** on its chip explains why when you hover it. Everything below a skipped assembly is skipped too, because it has no item to join in the Fusion Manage BOM.

### Shared item numbers

If two different components carry the same item number, they would both write to the one Fusion Manage item, each overwriting the other. The add-in does not publish either. Both lines are **Skipped**, with the names of the others in the tooltip, and so is everything below them. The same component appearing on several lines is not a clash. Give each component its own item number in Fusion, save, and refresh.

!!! example "Screenshot placeholder: BOM table with New, Changed, Skipped and Fusion Manage Only rows"
    **Show:** The BOM table with status chips, including a Skipped row, and the Filters drop-down and the collapse and expand buttons above it.

    Save the image as `docs/images/bom-statuses.png`, then replace this box with `![BOM table with New, Changed, Skipped and Fusion Manage Only rows](../images/bom-statuses.png)`.

### Filters

The **Filters** drop-down above the table (top left) narrows it to rows of one status (**Review**, **New**, **Added**, **Update**, **Fusion Manage Only** or **Skipped**); tick any number at once. **Show Hidden Components** is separate: it adds the components that are hidden in the Fusion component tree, marked with a crossed eye. Each filter shows how many lines it holds, and its tooltip explains what it shows. **Clear filters** unticks them all. Next to it, at the right, **Collapse all** and **Expand all** fold the whole tree.

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

### Add Existing Items

**Add Existing Items** (top right of the BOM) opens a picker that searches the Items workspace so you can add items that are not in the design.

!!! example "Screenshot placeholder: Add Existing Items picker"
    **Show:** The Add Existing Items dialog with its property filters, results and some items ticked.

    Save the image as `docs/images/add-items.png`, then replace this box with `![Add Existing Items picker](../images/add-items.png)`.

- With nothing typed the picker lists every item of the workspace; **Search** applies the search box and the filters.
- The search box matches the item descriptor. The **Filter** pane on the left narrows the results by property: choose a property and a value (a drop-down for properties with a fixed list). **Add Row** adds another property to the group and **Add Group** starts a new group. Rows of a group, and groups, are joined by **AND** or **OR**; the Items workspace is always applied on top.
- Results load 50 at a time as you scroll. Tick the items to add; selections survive searching and paging, and **Clear** unticks them all.
- The bar under the list shows how many items are selected. **Show only selected** narrows the list to the ticked items, so you can review them before adding. **Cancel** closes the picker without adding anything.
- Items the Bill of Materials already holds, or that you have already added in the panel, are hidden. Turn on **Show hidden items** to see them ticked, greyed out and locked.
- Added lines appear in the BOM as **Added** and can be taken out again with their own **Remove** button before publishing.

### What gets sent

Each change becomes one request against the parent item's BOM:

| Operation | Request |
|---|---|
| Add a line | `POST` to the parent's `bom-items` |
| Change a quantity | `PATCH` with the new quantity |
| Renumber a kept line | `PATCH` with the new BOM item number |
| Remove a line | `DELETE` |

They are ordered so a line is freed before another takes its number: remove, renumber, update, add.

All BOM requests are sent **after** every item exists, one parent at a time. A failure stops only that parent; the others carry on. Adding an item the BOM already has is reported by Fusion Manage as a duplicate and is recorded against that parent. See [Request Files and Retry](../job-queue/index.md#request-files-and-retry) for sending it again.

## The Export Window

**Export** (in the **Export** panel of the **Manage** tab) opens one small window for every file the add-in can attach. You choose two things:

1. **Attach to.** Two cards, at the top. **Item** attaches the file to the item of the part in the Items workspace. **Component** attaches it to the part's record in the Components workspace: its **working version**, when the part has several revisions. When the window opens it checks, in Fusion Manage, that you may attach files to each workspace (**View Items**, **Add Attachments** and **Edit Attachments**; the last is for a new version of a file already there). A card you may not use is greyed out and says why. If the Items workspace is not set up in Preferences, **Item** says *Item is not configured* and **Component** is chosen for you.
2. **File format.** What the open document can be exported as: a **design** makes a **STEP** file; a **drawing** makes a **PDF**, **DWG** or **DXF**. The window names what is being exported: the selected component of a design (else the whole design), or the top of a drawing.

The window starts with what is being exported: its item number (a grey bar stands there while it is read from Fusion Manage), and under it the description of the design. The attachment card shows whether the file already in Fusion Manage is **Up to date**, with the date the component was last modified, the file's version, size and who changed it.

Choose **Export** and the window stays open and shows the progress: **Find item**, the file being made, and **Upload**, with a percentage where one can be measured. It then says how it went. On success it reads *Export complete* with where the file went, and **Done** closes it. On a failure it reads *Export failed* with the reason; **Try again** takes you back to the choices, and **Close** closes the window. The file is named after the item number and a file of the same name is replaced by a new version. See [STEP File](#step-file) and [Drawing Representation](#drawing-representation).

The **Actions** menu of the [Item Panel](../item-panel/index.md) and the right-click entries do not open this window: they export in one step and always attach to the item.

## STEP File

The add-in can attach a **STEP file** of a component to its Fusion Manage item, so the wider supply chain has a neutral 3D representation to work from.

!!! important "Uploaded by you, never automatic"
    Publishing an item does not attach a STEP file. STEP files are uploaded manually, one component at a time, so you stay in control of what is released, for which items, and when. If you never upload one, none is sent.

The item must already exist. Publish it first ([Item Creation](#item-creation)).

!!! example "Screenshot placeholder: Right-click menu: Export STEP File"
    **Show:** The right-click menu of a component with the STEP upload entry.

    Save the image as `docs/images/step-context-menu.png`, then replace this box with `![Right-click menu: Export STEP File](../images/step-context-menu.png)`.

### Upload a STEP file

The file is named after the item number, for example `PN-1001.step`.

1. In the Design workspace, select a component in the browser or canvas. With nothing selected, the open design's top-level component is used.
2. Do one of the following:
    - Right-click and choose **Export STEP File** (offered on any component, not only the top).
    - Open the item in the [Item Panel](../item-panel/index.md) and choose **Actions ▸ Export STEP File**.
3. A small **Uploading STEP File** window shows three stages: **Find item**, **Create STEP** and **Upload**, with a percentage where one can be measured.
4. When it finishes you see a confirmation: `<name> was attached to the item in Fusion Manage.` or `A new version of <name> was uploaded to the item in Fusion Manage.` It appears as a message box, or as a toast when the Item panel is open.

#### New versions, not duplicates

If a file of the same name is already attached, the upload creates **a new version** of it instead of a duplicate, and the confirmation says so. You can refresh a STEP file as the design changes without cluttering the item.

!!! example "Screenshot placeholder: Upload confirmation"
    **Show:** The confirmation that the file was attached, or that a new version was uploaded.

    Save the image as `docs/images/step-uploaded.png`, then replace this box with `![Upload confirmation](../images/step-uploaded.png)`.

### Which geometry is exported

The STEP file contains the **selected component**, not the whole design.

- If the selected component is the design's **top-level component**, the whole design is exported.
- Otherwise the add-in finds the component in the open design by its **part number** (the one you selected is tried first) and exports just that.
- If Fusion cannot export it directly from the open design, the add-in falls back to the component's own document.

The part number only locates the component in Fusion. The item it is attached to is found by the component's **item number**, read from the Data Model. Finding a component by part number can take a while in large designs. The progress window stays responsive and you will see the percentage move.

!!! example "Screenshot placeholder: Uploading STEP File progress window"
    **Show:** The small window with the Find item, Create STEP and Upload stages and the percentage.

    Save the image as `docs/images/step-progress.png`, then replace this box with `![Uploading STEP File progress window](../images/step-progress.png)`.

### Messages you may see

- **Open the design to publish as a STEP file first.** No design is open.
- **No component with part number … in the open design.** The selected component's part number is not found, for example because the part number is empty.
- **No item exists for …** No item in Fusion Manage has that item number. Publish the item first.
- **… Fusion Manage items match … Open the item in the Item panel and choose one first.** Several items share the item number. Open the item from the Item panel, pick one from the list, and try again.
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

1. Open the drawing. The add-in works out which item it belongs to from the design the drawing references: the part number of that design's **top-level component** is read, then its item number from the Data Model, and the item with that number is the one used.
2. Choose **Manage ▸ Export ▸ Export** and pick PDF, or right-click the top of the drawing's component tree and choose **Export PDF**. In a drawing, the [Item Panel](../item-panel/index.md) **Actions** menu offers the same upload.
3. A PDF of every sheet of the drawing is created, named after the item number (for example `PN-1001.pdf`), and uploaded in a window with the stages **Find item**, **Create PDF** and **Upload**.

The Export window and the Item Panel's **Actions** menu can also make a **DWG** or a **DXF** of the drawing, attached the same way, as `PN-1001.dwg` or `PN-1001.dxf`. The right-click entry makes the PDF only. A Fusion that cannot export those formats says so.

The right-click entry is offered only when the **top of the tree** is selected, not a component below it.

#### New versions, not duplicates

If a file of the same name is already attached, the upload creates **a new version** of it instead of a duplicate.

### The drawing must be loaded

A drawing takes a moment to load. Until its design reference has loaded and the top-level component's part number can be read, the drawing button and menu entry are greyed out and the tooltip says what it is waiting for, for example *The drawing has no references yet.* or *The top-level component of … has no part number.* The add-in checks again every couple of seconds, so the button enables itself.

!!! example "Screenshot placeholder: Drawing upload button greyed out with its tooltip"
    **Show:** The disabled button and the tooltip that says what the drawing is waiting for.

    Save the image as `docs/images/drawing-greyed.png`, then replace this box with `![Drawing upload button greyed out with its tooltip](../images/drawing-greyed.png)`.

### A drawing of a different item

If the item you are attaching to is not the one the drawing shows, you are asked: *The open drawing is of X, but the item is Y (its part number). Upload this drawing as Y.pdf anyway?* Choose **Yes** only if that is what you intend.

!!! example "Screenshot placeholder: Drawing of a different item prompt"
    **Show:** The question asking whether to upload the drawing as another item's PDF.

    Save the image as `docs/images/drawing-different-item.png`, then replace this box with `![Drawing of a different item prompt](../images/drawing-different-item.png)`.

### If the PDF is empty

Fusion can report an export as successful straight after a drawing opens while writing nothing. The add-in detects this and asks you to wait for the drawing to finish loading and try again.

### Seeing the result

The PDF appears on the **Files** tab of the item in the [Item Panel](../item-panel/index.md#files). If the panel is open it shows a success toast and re-reads the item, so the file count updates.
