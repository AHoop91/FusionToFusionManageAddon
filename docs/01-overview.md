---
title: Overview
---

# Overview

This add-in is vault-inspired item management for Fusion, powered by Fusion Manage. It carries a **released engineering definition** from Fusion into **independently managed manufacturing items and BOMs** in Fusion Manage, with the representations and information the wider supply chain needs.

Engineering components and manufactured items are kept separate, so each has its own lifecycle. The add-in is the bridge between them. Fusion and Fusion Manage keep doing their own jobs. See the [End-to-End Workflow](02-end-to-end-workflow.md) for how this works in practice.

Technically, it reads the design's components, properties and thumbnails from the Manufacturing Data Model, compares them with what already exists in Fusion Manage, and sends only what needs to be created or changed.

## What it does

| Capability | Where to read more |
|---|---|
| Sign in to Fusion Manage from Fusion using your Autodesk account | [Installation and Authentication](03-installation-and-authentication.md) |
| Read components, properties and BOMs from the Manufacturing Data Model | [Manufacturing Data Model](04-manufacturing-data-model.md) |
| Map those properties to Fusion Manage fields | [Workspace and Field Mapping](05-workspace-and-field-mapping.md) |
| Create and update items in a Fusion Manage workspace | [Publishing Enterprise Items](06-publishing-enterprise-items.md) |
| Compare and synchronise the design BOM with the Fusion Manage BOM | [BOM Synchronisation](07-bom-synchronisation.md) |
| Attach a STEP file of a component, or a PDF of a drawing, to an item, manually and only when you choose to | [Technical Representation](08-technical-representation.md) |
| Browse an item's fields, files, BOM, where-used and workflows inside Fusion | [Item Review & Release](09-item-review-and-release.md) |

To see how these fit together in practice, from engineering release through to release in Fusion Manage, read the [End-to-End Workflow](02-end-to-end-workflow.md).

## How it fits together

The add-in takes what the design says in the Manufacturing Data Model, compares it with Fusion Manage, and sends only the difference.

```mermaid
flowchart LR
    DESIGN["<b>Fusion</b><br/>Design and drawing"]
    MDM["<b>Manufacturing Data Model</b><br/>Properties, thumbnails,<br/>part numbers"]
    ADDIN["<b>Fusion Manage add-in</b><br/>Preview, compare, publish"]
    FM["<b>Fusion Manage</b><br/>Items, BOMs, attachments"]

    DESIGN -->|"1. Saved to the cloud"| MDM
    MDM -->|"2. Properties read"| ADDIN
    DESIGN -->|"3. STEP and PDF exported"| ADDIN
    ADDIN <-->|"4. Compared, then created or updated"| FM

    classDef source fill:#f1f5f9,stroke:#94a3b8,color:#0f172a
    classDef addin fill:#4f46e5,stroke:#3730a3,color:#ffffff
    classDef target fill:#ecfdf5,stroke:#059669,color:#064e3b
    class DESIGN,MDM source
    class ADDIN addin
    class FM target
```

| Step | What happens |
|---|---|
| **1** | Engineering saves the design. Fusion stores its components and properties in the Manufacturing Data Model. |
| **2** | The add-in reads each component's properties, thumbnail and part number from the Manufacturing Data Model. |
| **3** | When you attach a technical representation, the add-in has Fusion export a STEP file or a drawing PDF. |
| **4** | The add-in reads the matching items and BOMs in Fusion Manage, shows you the differences, and on your command creates or updates items, BOM lines and attachments. |

One sign-in covers both the Data Model and Fusion Manage. It is explained step by step in [Installation and Authentication](03-installation-and-authentication.md#how-sign-in-works).

Items are matched by **item number**, which the add-in takes from the component's part number. If an item with that number already exists in Fusion Manage it is updated; otherwise it is created.

## The user interface

The add-in adds a **Fusion Manage** tab to the ribbon in the **Design** and **Drawing** workspaces.

| Panel | Button | Purpose |
|---|---|---|
| Item | Open Fusion Manage Item | Show the Fusion Manage item of the selected component, or of the open design or drawing. |
| Item | Publish Fusion Manage Item (Design only) | Preview and publish the open design. |
| Item | Upload Drawing Representation To Fusion Manage Item (Drawing only) | Attach a PDF of the open drawing. |
| Administration | Job Queue | See publishes that are waiting, running and finished. |
| Administration | Preferences | Sign in, set the connection and the workspace mapping. |

Most buttons stay greyed out until the Items workspace is configured (see [Workspace and Field Mapping](05-workspace-and-field-mapping.md)). The tooltip of a greyed-out button says why.

The same actions are available from the right-click menu of a component in the browser or canvas: **Open Fusion Manage Item**, **Publish Fusion Manage Item** (top-level component only), **Upload STEP File To Fusion Manage Item** and, in a drawing, **Upload Drawing Representation To Fusion Manage Item**.

## Requirements

- Autodesk Fusion on Windows or macOS.
- A Fusion Manage tenant and a user with permission to work in the target workspace.
- An Autodesk Platform Services (APS) application registered for sign-in (see [Installation and Authentication](03-installation-and-authentication.md)).

## Scope of this release

This is version 0.1.0. It works with a single Fusion Manage workspace, **Items**. See [Troubleshooting and Limitations](10-troubleshooting-and-limitations.md) for what is not yet supported.
