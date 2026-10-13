---
title: End-to-End Workflow
---

# End-to-End Workflow

## The short version

Engineers design and release a product in **Fusion**. Manufacturing and the supply chain need a managed **item** for that product in **Fusion Manage**: a record with its own bill of materials (BOM), files, approvals and release. The add-in moves the released design across, so nobody has to re-key it.

In three sentences:

1. **Engineering releases** the component and drawing in Fusion, exactly as before.
2. **Manufacturing publishes** the released design with the add-in. This creates or updates the matching item and BOM in Fusion Manage.
3. **Manufacturing completes, reviews and releases** the item in Fusion Manage, on its own schedule.

The add-in does nothing on its own. It only acts when someone chooses to publish or upload.

## Who does what

| | Fusion | The add-in | Fusion Manage |
|---|---|---|---|
| **Purpose** | Engineering design | Carries the design across | Manufacturing item management |
| **Holds** | The CAD component, the drawing and the engineering release | Nothing. It compares and sends | The item, its BOM, its files and its release workflow |
| **Released by** | Engineering | Not applicable | Manufacturing release approvers |

The two sides are linked by the **part number**. A component's part number in Fusion is the item number in Fusion Manage. If an item with that number exists it is updated. Otherwise it is created.

## Two lifecycles, kept separate

A released component and a manufactured item are not the same thing, so they do not have to move together.

- Engineering can revise a component, and the item does not change until someone publishes.
- Manufacturing can add to the item, such as extra BOM lines or production-only fields, without touching the CAD design.
- The item is released through its own workflow in Fusion Manage.

## The workflow at a glance

Read the diagram left to right. Engineering designs and releases in Fusion. The add-in then carries the released design across, with STEP and PDF files as an optional extra. Manufacturing enriches the item, reviews it and releases it in Fusion Manage. The five stages below cover the same path.

```mermaid
%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 40, "rankSpacing": 60, "padding": 16}}}%%
flowchart LR
    subgraph ENG["<b>ENGINEERING</b> &nbsp;·&nbsp; Fusion"]
        E1("<b>Design</b><br/>Model, draw and<br/>review the design")
        E2("<b>Released</b><br/>Component and<br/>drawing released")
    end

    subgraph ADD["<b>THE ADD-IN</b> &nbsp;·&nbsp; Fusion"]
        A1("<b>Publish</b><br/>Send the released<br/>design when ready")
        A2("<b>Upload files</b><br/>STEP and drawing PDF<br/><i>Optional, manual</i>")
    end

    subgraph MFG["<b>MANUFACTURING</b> &nbsp;·&nbsp; Fusion Manage"]
        M1("<b>Manufacturing item</b><br/>Item and BOM<br/>created or updated")
        M2("<b>Enrich</b><br/>Add production lines,<br/>fields and items")
        M3("<b>Review</b><br/>Engineering, Quality and<br/>Manufacturing check")
        M4("<b>Released</b><br/>Item released by<br/>its own workflow")
    end

    E1 --> E2 ==> A1 ==> M1 --> M2 --> M3 --> M4
    A1 -.-> A2 -.->|"attached to<br/>the item"| M1
    E2 -.->|"Engineering change:<br/>publish again"| A1

    classDef eng fill:#3b82c426,stroke:#3b82c4,stroke-width:1.5px
    classDef add fill:#1d4f9126,stroke:#1d4f91,stroke-width:3px
    classDef opt fill:#1d4f9110,stroke:#1d4f91,stroke-width:1.5px,stroke-dasharray:5 4
    classDef mfg fill:#0596691f,stroke:#059669,stroke-width:1.5px
    class E1,E2 eng
    class A1 add
    class A2 opt
    class M1,M2,M3,M4 mfg
    style ENG fill:transparent,stroke:#94a3b8,stroke-dasharray:4 4
    style ADD fill:transparent,stroke:#94a3b8,stroke-dasharray:4 4
    style MFG fill:transparent,stroke:#94a3b8,stroke-dasharray:4 4
    linkStyle default stroke:#64748b,stroke-width:1.5px
```

!!! tip "When to publish"
    Publish when the design is **released and ready for manufacturing**. Publish again whenever engineering changes the design and Manufacturing needs the item brought up to date. Repeating a publish is safe: only the differences are sent, and anything Manufacturing added in Fusion Manage is kept.

## The five stages

| Stage | Who | Where | What happens |
|---|---|---|---|
| [1. Engineering releases the component](#1-engineering-releases-the-component-and-drawing) | Engineering | Fusion | Normal release. Nothing changes for engineers. |
| [2. Manufacturing publishes the item](#2-manufacturing-publishes-the-enterprise-item) | Design Engineer or Manufacturing Engineer | Fusion, using the add-in | Released definition becomes manufacturing items and BOMs. |
| [3. Complete the manufacturing package](#3-complete-the-manufacturing-package) | Manufacturing | Fusion and Fusion Manage | Representations are attached and the BOM is completed. |
| [4. Review](#4-engineering-quality-and-manufacturing-review) | Engineering, Quality, Manufacturing | Fusion or Fusion Manage | Each group checks the item against the design. |
| [5. Release the item](#5-the-enterprise-item-is-released-in-fusion-manage) | Release approvers | Fusion Manage | The item is released through its own workflow. |

!!! note "The add-in does not enforce this process"
    It will publish any design you open, whatever its state, and it does not release items or start workflows. The sequence below is how it is meant to be used. Your organisation's own release rules still apply.

## Before you start

One-time setup:

- The add-in is installed and you are signed in ([Installation and Authentication](installation.md)).
- The Items workspace is configured, with field mappings ([Workspace and Field Mapping](../configuration/index.md#workspace-and-field-mapping)).
- Every user who publishes holds the Fusion Manage permissions listed in [Installation and Authentication](installation.md#permissions-in-fusion-manage).

---

## 1. Engineering releases the component and drawing

**Who:** Engineering, the designers who do the CAD work. **Where:** Fusion.

Engineers model the component, create its drawing, and release both **exactly as they normally would**. The add-in asks nothing more of them, and does not take part in this step.

What the next stage depends on:

- The design and drawing are saved and released.
- The Manufacturing Data Model has finished processing the design.
- Every component that should become an item has a **part number**, including the top-level one.
- The drawing references the released design.

!!! tip "Engineers are not blocked"
    Because the manufactured item has its own lifecycle, engineers release and revise in Fusion without waiting on Fusion Manage. The item is published when the Design Engineer or Manufacturing Engineer is ready.

## 2. Manufacturing publishes the enterprise item

**Who:** the Design Engineer or the Manufacturing Engineer. **Where:** Fusion. **Add-in:** Publish Fusion Manage Item.

This is the step that crosses the bridge. Either role can publish: the Design Engineer who released the component, or the Manufacturing Engineer who takes it on. It needs the Fusion Manage permissions listed under [Before you start](#before-you-start), so whoever publishes must hold them.

1. Open the released design.
2. Choose **Manage ▸ Item Management ▸ Publish Fusion Manage Item**.
3. Review the BOM and each component's properties in the Details Panel. Anything marked **New** or **Update** will change in Fusion Manage.
4. Click **Publish**.

The add-in creates an item for each component that does not have one, updates those that do, and synchronises the BOMs. Progress is shown in the **Job Queue**.

What crosses, and what does not:

| Crosses from engineering to the item | Stays independent |
|---|---|
| The properties you have mapped (part number, name, description, material, custom and physical properties) | Fields you have not mapped, which the add-in never overwrites |
| The thumbnail | The item's lifecycle state and workflow, which Fusion Manage owns |
| | STEP files and drawing PDFs, which are never sent by a publish. You upload them yourself in [stage 3](#3-complete-the-manufacturing-package) |
| The design's BOM structure and quantities | BOM lines that only Fusion Manage has, which are **kept** unless you choose to remove them |

!!! tip "Keep engineering and manufacturing state separate"
    Mapping Fusion's **Revision** or **Lifecycle state** is optional. If you do, map them to informational fields, for example a text field recording the engineering revision, and not to the field that drives the item's own lifecycle. Otherwise the two lifecycles are tied together again.

For the full procedure see [Publishing](../publishing/index.md) and [Bill of Materials](../publishing/index.md#bill-of-materials).

**Outcome:** every component exists as a manufacturing item in the Items workspace, with its properties, thumbnail and BOM.

## 3. Complete the manufacturing package

**Who:** Manufacturing. **Where:** Fusion and Fusion Manage.

The published item is the foundation. This stage adds what the supply chain needs to make or buy it.

!!! important "Representations are never added automatically"
    Publishing an item does **not** attach a STEP file, a drawing PDF or any other representation. Each one is uploaded manually, one at a time, from a menu command. You decide which representations go to the supply chain, for which items, and when. If you never upload one, none is sent.

| Task | How |
|---|---|
| Attach a STEP file of a component | Select the component and choose **Export STEP File** ([STEP File](../publishing/index.md#step-file)). |
| Attach a PDF of the drawing | Open the drawing and choose **Export PDF** ([Drawing Representation](../publishing/index.md#drawing-representation)). |
| Add items that are not in the design | Use **Add Items** in the Publish panel, then publish again ([Bill of Materials](../publishing/index.md#add-items)). |
| Keep or change manufacturing lines that only Fusion Manage has | Review the **Fusion Manage Only** lines. They are kept unless you remove them. |
| Complete information that engineering does not supply | Edit it in Fusion Manage. |

The drawing is not an item of its own. Its PDF is attached to the item of the design it shows. Uploading a file that is already attached creates a **new version**, so the package can be refreshed as the design changes.

!!! tip "When engineering changes the design later"
    Publish again. Items that already match are left alone, only the differences are sent, and what Manufacturing added in Fusion Manage is kept. Repeating a publish is safe.

**Outcome:** each item carries its STEP file, its drawing PDF and a complete BOM.

## 4. Engineering, Quality and Manufacturing review

**Who:** Engineering, Quality and Manufacturing. **Where:** Fusion, or Fusion Manage in a browser.

Each group checks the item against the design. In Fusion, open the **Item panel** (**Open Fusion Manage Item**) on the component. Anyone without the add-in, or who prefers the web, can review the same item in Fusion Manage directly.

| Review | Look at |
|---|---|
| Engineering: does the item match the design and drawing? | **Item** tab fields against the design's properties; **Bill of Materials** tab against the design BOM. |
| Quality: is the documentation present? | **Files** tab for the STEP file and drawing PDF. **Item** tab for the recorded revision. |
| Manufacturing: is the package complete? | **Bill of Materials** tab, including the manufacturing lines; **Where Used** for the assemblies that hold the item. |
| Everyone: is anything already in flight? | **Associated Workflows** tab for change orders that reference the item and their current state. |

See [Item Panel Tabs](../item-panel/index.md#tabs) for what each tab shows, and [Review and Release](../item-panel/index.md#review-and-release) for the routine.

If the review finds a problem, correct it at its source. A design problem is fixed in Fusion, released, and published again. A manufacturing problem is fixed in Fusion Manage. Then review again.

**Outcome:** the item is agreed to be correct and complete.

## 5. The enterprise item is released in Fusion Manage

**Who:** Release approvers. **Where:** Fusion Manage.

The manufactured item is released through **its own workflow in Fusion Manage**, independent of the engineering release in Fusion. The add-in does not move an item through its workflow.

1. In the Item panel, click **Open in browser** to go straight to the item.
2. In Fusion Manage, run the workflow action your organisation uses to release the item.
3. Back in Fusion, click **Refresh** in the Item panel to see the new state, or check the **Associated Workflows** tab for the workflow's progress.

**Outcome:** the manufactured item is released and available to the wider supply chain.

---

## Quick reference

| I want to… | Use |
|---|---|
| Create or update items from a released design | **Publish Fusion Manage Item** |
| See whether a publish succeeded | **Job Queue** |
| Retry after a failure | **Retry** on the job in the Job Queue |
| Attach a STEP file | **Export STEP File** |
| Attach a drawing PDF | **Export PDF** |
| Review an item | **Open Fusion Manage Item** |
| Release an item | Fusion Manage, via **Open in browser** |
