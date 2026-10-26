---
title: Overview
---

# Overview

**In one sentence:** the add-in copies a released design from Fusion into Fusion Manage, as a manufacturing item with its parts list (BOM) and files, when you tell it to.

Engineers keep working in Fusion. Manufacturing, purchasing and quality teams work from the item in Fusion Manage. Unfamiliar words are explained in the [Glossary](glossary.md).

## What you can do

- **Sign in** to Fusion Manage from Fusion with your Autodesk account ([Installation](installation.md)).
- **Choose which design properties fill which Fusion Manage fields** ([Configuration](../configuration/index.md)).
- **Create and update items** from a design, matched by item number ([Publishing](../publishing/index.md)).
- **Compare and synchronise the BOM** between the design and Fusion Manage ([Bill of Materials](../publishing/index.md#bill-of-materials)).
- **Attach a STEP file or drawing PDF** to an item, only when you choose to ([STEP File](../publishing/index.md#step-file), [Drawing Representation](../publishing/index.md#drawing-representation)).
- **Review an item inside Fusion**: fields, files, BOM, where-used and workflows ([Item Panel](../item-panel/index.md)).
- **Follow your publishes** and retry a failed one ([Job Queue](../job-queue/index.md)).

## Why it exists

Engineering and the enterprise work to different rhythms. Engineers iterate on designs, while manufacturing, purchasing, quality and supply chain teams need a stable, controlled record of what is to be built. Mixing the two forces one side to inherit the other's pace and permissions.

The add-in keeps them separate by design:

- **Engineering components** stay in Fusion, where design work continues and revisions are managed.
- **Manufactured items** live in Fusion Manage, each with its own lifecycle, approvals and release status.
- **The add-in is the controlled bridge between them.** Fusion and Fusion Manage each keep doing their own job, and information crosses only when you choose to publish.

The result is a single, traceable path from a released design to an item the enterprise can rely on, without re-keying data or maintaining parallel spreadsheets. The [End-to-End Workflow](workflow.md) shows how this works in practice.

## How it works

The add-in reads a design's components, BOM structure, properties, thumbnails and part numbers from the Manufacturing Data Model and compares them with what already exists in Fusion Manage. It shows you the differences before anything changes, then sends **only what needs to be created or updated**. Nothing is overwritten blindly, and you stay in control of every publish.

## How it fits together

The add-in takes what the design says in the Manufacturing Data Model, compares it with Fusion Manage, and sends only the difference.

<div class="fm-diagram" style="max-width:1120px;margin:0 auto">
<svg viewBox="0 0 1000 402" role="img" aria-label="How it fits together: Fusion saves the design to the Manufacturing Data Model in Autodesk Platform Services. The add-in reads it, can also export STEP and PDF files from Fusion once the item has been published, and compares and updates items in Fusion Manage." style="width:100%;height:auto;color:var(--md-default-fg-color);font-family:inherit;font-size:13px">
<defs>
<marker id="fm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="currentColor"/></marker>
</defs>
<rect x="340" y="14" width="320" height="150" rx="6" fill="#7c3aed" fill-opacity="0.06" stroke="#7c3aed" stroke-opacity="0.5"/>
<text x="356" y="38" font-weight="700" font-size="14" fill="#7c3aed">AUTODESK PLATFORM SERVICES</text>
<path d="M380 62 v72 a120 11 0 0 0 240 0 v-72 z" fill="#7c3aed" fill-opacity="0.2" stroke="#7c3aed" stroke-width="2"/>
<ellipse cx="500" cy="62" rx="120" ry="11" fill="#7c3aed" fill-opacity="0.2" stroke="#7c3aed" stroke-width="2"/>
<g text-anchor="middle" fill="currentColor"><text x="500" y="92" font-weight="700">Manufacturing Data Model</text><text x="500" y="110">BOM, properties, thumbnails,</text><text x="500" y="126">part numbers</text></g>
<rect x="20" y="240" width="230" height="150" rx="6" fill="#2563eb" fill-opacity="0.06" stroke="#2563eb" stroke-opacity="0.5"/>
<text x="36" y="264" font-weight="700" font-size="14" fill="#2563eb">FUSION</text>
<rect x="45" y="290" width="180" height="80" rx="8" fill="#3b82c4" fill-opacity="0.2" stroke="#3b82c4" stroke-width="2"/>
<g text-anchor="middle" fill="currentColor"><text x="135" y="318" font-weight="700">Design and drawing</text><text x="135" y="336">Components and</text><text x="135" y="352">part numbers</text></g>
<rect x="385" y="240" width="230" height="150" rx="6" fill="#ea580c" fill-opacity="0.06" stroke="#ea580c" stroke-opacity="0.5"/>
<text x="401" y="264" font-weight="700" font-size="14" fill="#ea580c">ADD-IN</text>
<path d="M430 290 H570 L590 330 L570 370 H430 L410 330 z" fill="#f97316" fill-opacity="0.2" stroke="#ea580c" stroke-width="3" stroke-linejoin="round"/>
<g text-anchor="middle" fill="currentColor"><text x="500" y="318" font-weight="700">Fusion Manage add-in</text><text x="500" y="336">Preview, compare,</text><text x="500" y="352">publish</text></g>
<rect x="750" y="240" width="230" height="150" rx="6" fill="#059669" fill-opacity="0.06" stroke="#059669" stroke-opacity="0.5"/>
<text x="766" y="264" font-weight="700" font-size="14" fill="#059669">FUSION MANAGE</text>
<rect x="775" y="290" width="180" height="80" rx="8" fill="#059669" fill-opacity="0.2" stroke="#059669" stroke-width="2"/>
<g text-anchor="middle" fill="currentColor"><text x="865" y="318" font-weight="700">Items</text><text x="865" y="336">BOMs and</text><text x="865" y="352">attachments</text></g>
<g fill="none" stroke="currentColor" stroke-opacity="0.75" stroke-width="1.5">
<path d="M135 290 V100 H378" marker-end="url(#fm-arrow)"/>
<path d="M500 146 V288" marker-end="url(#fm-arrow)"/>
<path d="M225 330 H407" stroke-dasharray="2 4" marker-end="url(#fm-arrow)"/>
<path d="M592 330 H773" marker-start="url(#fm-arrow)" marker-end="url(#fm-arrow)"/>
</g>
<g>
<circle cx="250" cy="100" r="11" fill="currentColor"/><circle cx="500" cy="205" r="11" fill="currentColor"/><circle cx="317" cy="330" r="11" fill="currentColor"/><circle cx="682" cy="330" r="11" fill="currentColor"/>
</g>
<g fill="var(--md-default-bg-color)" font-weight="700" font-size="12" text-anchor="middle">
<text x="250" y="104.5">1</text><text x="500" y="209.5">2</text><text x="317" y="334.5">3</text><text x="682" y="334.5">4</text>
</g>
<g fill="currentColor" fill-opacity="0.8" font-size="12" text-anchor="middle">
<text x="250" y="124">Saved to cloud</text>
<text x="518" y="209" text-anchor="start">Properties read</text>
<text x="317" y="354">STEP and PDF, only</text><text x="317" y="369">once the item is</text><text x="317" y="384">published</text>
<text x="682" y="354">Compare, create,</text><text x="682" y="369">and update</text>
</g>
</svg>
</div>

| Step | What happens |
|---|---|
| **1** | Engineering saves the design. Fusion stores its components, BOM and properties in the Manufacturing Data Model. |
| **2** | The add-in reads the BOM and each component's properties, thumbnail and part number from the Manufacturing Data Model. |
| **3** | **Only after the item has been published.** When you attach a technical representation, the add-in has Fusion export a STEP file or a drawing PDF and attaches it to the item. |
| **4** | The add-in reads the matching items and BOMs in Fusion Manage, shows you the differences, and on your command creates or updates items, BOM lines and attachments. |

One sign-in covers both the Data Model and Fusion Manage. It is explained step by step in [Installation and Authentication](installation.md#how-sign-in-works).

Items are matched by **item number**, which the add-in reads from the component's Item Number in the Manufacturing Data Model. If an item with that number already exists in Fusion Manage it is updated; otherwise it is created.

## The user interface

The add-in adds an **Export** panel and an **Item Management** panel to the **Manage** tab of the ribbon in the **Design** and **Drawing** workspaces. **Administration** is a submenu of **Item Management**; its buttons are pinned to the ribbon.

| Panel | Button | Purpose |
|---|---|---|
| Export | Export | Open the Export window: export the open design or drawing and attach the file to its item or component |
| Item Management | Open Fusion Manage Item | Show the item of the selected component, or of the open design or drawing |
| Item Management | Publish Fusion Manage Item (Design only) | Preview and publish the open design |
| Item Management ▸ Administration | Job Queue | See publishes that are waiting, running and finished |
| Item Management ▸ Administration | Preferences | Sign in, set the connection and the workspace mapping |

Most buttons stay greyed out until the Items workspace is configured (see [Item Workspace](../configuration/index.md#item-workspace)). The tooltip of a greyed-out button says why.

![Fusion Manage ribbon tab in the Design workspace](../images/ribbon-design.png){ width="1834" height="168" }

### Using the right-click menu

The same actions are available from the context (right-click) menu of a component, so you can work without leaving the model.

1. In the **Browser** (or on the canvas), find the component you want to work with.
2. **Right-click** the component to open its context menu.
3. Choose one of the Fusion Manage entries:

    | Menu entry | What it does |
    | --- | --- |
    | **Open Fusion Manage Item** | Opens the component's linked item in Fusion Manage. |
    | **Publish Fusion Manage Item** | Publishes the component and its structure. Available on the top-level component only. |
    | **Export STEP File** | Exports the component as a STEP file. |
    | **Export PDF** | Exports the drawing as a PDF. Shown only when a drawing is open. |

!!! note
    Entries that don't apply to the selected component, or that are unavailable until the Items workspace is configured, are greyed out or hidden.

## Requirements

- Autodesk Fusion on Windows or macOS.
- A Fusion Manage tenant and a user with permission to work in the target workspace.
- An Autodesk Platform Services (APS) application registered for sign-in (see [Installation and Authentication](installation.md)).

## Scope

The add-in works with a single Fusion Manage workspace, **Items**. See [Troubleshooting and Limitations](../reference/troubleshooting.md#limitations) for what is not yet supported. Get the latest version from the [Releases page](https://github.com/AHoop91/FusionToFusionManageAddon/releases/latest).

## Next step

[Install the add-in and sign in](installation.md).
