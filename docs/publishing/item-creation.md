---
title: Item Creation
---

# Item Creation

When a component has no item in Fusion Manage yet, publishing **creates** one.

## When an item is created

For each component in the Publish panel, the add-in searches the Items workspace for an item with the component's **item number**, which is its part number in Fusion. If nothing is found, the item is marked **New** and a publish creates it. If an item is found, see [Item Update](item-update.md).

!!! example "Screenshot placeholder: Publish panel with a component marked New"
    **Show:** A BOM row or property marked New, before publishing.

    Save the image as `docs/images/item-new.png`, then replace this box with `![Publish panel with a component marked New](../images/item-new.png)`.

The search is by item number only. Make sure your workspace maps the part number to the item number field (`NUMBER` in the default mapping). See [Workspace and Field Mapping](../configuration/field-mapping.md#default-fields).

## What a new item receives

A new item is created with:

| Content | Where it comes from |
|---|---|
| Every **mapped property** that has a value | The Manufacturing Data Model, through your [field mapping](../configuration/field-mapping.md) |
| Every **static value** | Your workspace settings. Static values are set on every new item |
| The **thumbnail** | The Data Model, when the thumbnail is mapped to an image field |
| The **component link** | The Fusion Manage component for the part, when a linking field is chosen |

How values are prepared:

- **Picklist fields** receive the matching option. A value that matches no option is left out and recorded, and the rest of the item is still created. See the `Type` example in [Default fields](../configuration/field-mapping.md#the-type-field-and-its-picklist).
- **Number fields** are rounded to the precision the Fusion Manage field takes.
- **Empty values** are not sent. The run records *No value in the Data Model, not sent*, with the field names.

## Order of creation

Every component is created or updated first, **then** the BOM lines are sent. A BOM line needs both the parent and the child to exist, so BOMs always go last. See [Bill of Materials](bill-of-materials.md).

If an item fails to be created, the other items carry on. The failed item's BOM is skipped, because the item is not there for it. You can retry from the [Job Queue](../job-queue/request-files-and-retry.md): what Fusion Manage already accepted is skipped, so nothing is created twice.

## Permission needed

Creating an item needs **Add Items** in the Items workspace.

## What does not happen

Creating an item does not attach a STEP file or a drawing PDF. Those are uploaded by you afterwards, only for the items you choose. See [STEP File](step-file.md) and [Drawing Representation](drawing-representation.md).

## After creation

The run reports **Total Items Created**. Open the new item in the [Item Panel](../item-panel/index.md) to check it.
