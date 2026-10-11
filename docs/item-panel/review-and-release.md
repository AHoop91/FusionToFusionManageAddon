---
title: Review and Release
---

# Review and Release

## Review after a publish

Open the item in the [Item Panel](index.md) and work through the tabs:

1. Check the **Item** tab fields against the design.
2. Check **Files** for the STEP file or drawing PDF you attached.
3. Check **Bill of Materials** against the design BOM you published.
4. Check **Where Used** to confirm the item sits in the right assembly.
5. Check **Associated Workflows** to see whether a change order already covers the item and where it is.

Each tab is described in [Tabs](tabs.md). Anyone without the add-in can review the same item in Fusion Manage directly.

If the review finds a problem, correct it at its source. A design problem is fixed in Fusion, released, and published again. A manufacturing problem is fixed in Fusion Manage. Then review again.

## Release happens in Fusion Manage

!!! example "Screenshot placeholder: Item in Fusion Manage with its workflow actions"
    **Show:** The item open in Fusion Manage in the browser, showing the workflow action used to release it.

    Save the image as `docs/images/fm-item-workflow.png`, then replace this box with `![Item in Fusion Manage with its workflow actions](../images/fm-item-workflow.png)`.

The manufactured item is released through **its own workflow in Fusion Manage**, independent of the engineering release in Fusion. The add-in does not move an item through its workflow.

1. In the Item Panel, click **Open in browser** to go straight to the item.
2. In Fusion Manage, run the workflow action your organisation uses to release the item.
3. Back in Fusion, click **Refresh** to see the new state, or check the **Associated Workflows** tab for the workflow's progress.

For how this fits into the wider process, see the [End-to-End Workflow](../getting-started/workflow.md#5-the-enterprise-item-is-released-in-fusion-manage).
