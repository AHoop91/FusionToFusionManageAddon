---
title: BOM Synchronisation
---

# BOM Synchronisation

The Publish panel compares the design's BOM with the BOM already in Fusion Manage, line by line, and sends only the differences. You decide how to handle anything that is in Fusion Manage but not in the design.

## How lines are compared

For each parent assembly, the lines of the design are matched to the Fusion Manage lines under that same parent by item number. Repeated item numbers pair one to one in order. Each line gets a status:

| Status | Meaning | Publishing does |
|---|---|---|
| **New** | The design has the line; Fusion Manage does not. | Adds the line. |
| **Changed** (quantity differs) | Same item, different quantity. | Updates the quantity in Fusion Manage. |
| **Match** | Same item and quantity. | Nothing. Shown as a quiet dash. |
| **Extra** (**Fusion Manage Only**) | Fusion Manage has a line the design does not. | **Keeps it** unless you choose **Remove**. |

If a parent does not exist in Fusion Manage yet, every child is **New**.

Fusion Manage often extends the design BOM with manufacturing lines such as oil or panels. For that reason lines found only in Fusion Manage are never deleted automatically.

## Filters

Filter buttons above the table narrow it to rows of one status, such as **New** or **Fusion Manage Only**. Each filter's tooltip explains what it shows.

## Paired rows: a replaced item

When a **New** design line and a **Fusion Manage Only** line sit under the same parent, they are shown **paired**, one above the other, each carrying the other's item number. The item number differs at that position, which may mean an item was replaced, so the add-in asks you to decide rather than guessing. For a pair you can choose:

- **Keep** the Fusion Manage line, which is renumbered to the end of the BOM, and add the new design line.
- **Remove** the Fusion Manage line from Fusion Manage and add the design's line.

A Fusion Manage Only line with no partner shows a single **Remove** button; click it again to go back to keeping the line. A line marked for removal is highlighted so you cannot miss it.

## Editing quantities

A quantity can be edited in the table. An edited cell shows a revert button that restores the original value.

## Add Items

**Add Items** (top right of the BOM) opens a picker that lists Fusion Manage items from the Items workspace so you can add items that are not in the design.

- The list loads 100 items at a time as you scroll and stays quick with thousands of items.
- Type to filter, change the sort direction, and tick the items to add. Selections survive filtering and paging. Items already staged are marked.
- Added lines appear in the BOM as **New** and can be taken out again with their own **Remove** button before publishing.

## What gets sent

Each change becomes one request against the parent item's BOM:

| Operation | Request |
|---|---|
| Add a line | `POST` to the parent's `bom-items` |
| Change a quantity | `PATCH` with the new quantity |
| Renumber a kept line | `PATCH` with the new BOM item number |
| Remove a line | `DELETE` |

They are ordered so a line is freed before another takes its number: remove, renumber, update, add.

All BOM requests are sent **after** every item exists, one parent at a time. A failure stops only that parent; the others carry on. Adding an item the BOM already has is reported by Fusion Manage as a duplicate and is recorded against that parent. See [Publishing Enterprise Items](06-publishing-enterprise-items.md) for retrying.
