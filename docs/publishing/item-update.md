---
title: Item Update
---

# Item Update

When a component already has an item in Fusion Manage, publishing **updates** it, and only where something differs. Publishing the same design twice is safe.

## When an item is updated

The add-in searches the Items workspace for the component's item number.

| Result of the search | What happens |
|---|---|
| One item found | The item is compared with the design and updated where needed |
| No item found | The item is created. See [Item Creation](item-creation.md) |
| Several items found | The status is **Choose item**. Pick the right one in the Details Panel before you publish |

## What an update sends

An update sends only what has changed:

- **Mapped properties whose values differ.** These are the ones marked **Update** in the Details Panel.
- **Static values the item does not hold yet.** A static value that is already set is left alone.
- **The component link, if the item lacks it.**
- **The thumbnail.** Images cannot be compared, so the thumbnail goes along with an update that already has a difference. It is not sent on its own.

If nothing differs, **no request is sent** and the run records *Fusion Manage already has the same values*. Such an item is not counted as updated.

Numbers are compared at the precision of the Fusion Manage field. If the field already holds the number at its precision, it is not sent again.

## What is never overwritten

An update never changes:

- **Fields you have not mapped.** Anything entered in Fusion Manage that is not part of the mapping is untouched. This is how the manufacturing information added after publishing survives a later publish.
- **The item's lifecycle state and workflow.** Fusion Manage owns them.
- **BOM lines that only Fusion Manage has.** They are kept unless you choose to remove them. See [Bill of Materials](bill-of-materials.md).

!!! tip "Engineering changes"
    When a design changes after it was published, publish again. Items that still match are skipped, items that differ are updated, and what Manufacturing added in Fusion Manage is preserved.

## Choosing between several matches

If more than one Fusion Manage item has the same item number, the add-in does not guess. The row shows **Choose item** and a message such as *3 Fusion Manage items match PN-1001. Choose one.* Pick the item to update in the Details Panel. Until you do, that item cannot be published.

!!! example "Screenshot placeholder: Choose item status"
    **Show:** A row showing Choose item and the candidate items to pick from.

    Save the image as `docs/images/item-choose.png`, then replace this box with `![Choose item status](../images/item-choose.png)`.

## Permission needed

Updating an item needs **Edit Items** in the Items workspace.

## After the update

The run reports **Total Items Updated**. Open the item in the [Item Panel](../item-panel/index.md) to check the result.
