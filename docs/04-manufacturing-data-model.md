---
title: Manufacturing Data Model
---

# Manufacturing Data Model

The Manufacturing Data Model is where Fusion stores your design's components and their properties in the cloud. The add-in reads it through the Autodesk Platform Services Manufacturing Data Model GraphQL API, and **maps** each property you care about onto a field of a Fusion Manage workspace. That mapping is configured on the **Workspaces** tab of **Preferences**.

## The Items workspace

The add-in currently works with one workspace kind, **Items** ("Manufacturing items created in Fusion Manage"). On the **Workspaces** tab you will find a card for it with:

1. **Items Workspace ID**: the numeric ID of the workspace in your tenant, for example `83`.
2. **Validate**: checks the workspace and loads its field list so the pickers below can show real field names. The mapping controls stay disabled until the workspace validates (a tick appears next to the ID).
3. **Component linking**: optional, see below.
4. **Field mapping**: which Data Model property fills which Fusion Manage field.
5. **Static values**: fields set to a fixed value on every published item.

Click **Save** when you are done. Saving is refused while the settings have problems, and the message says what to fix.

## Field mapping

Each row of **Mapped fields** pairs a Data Model source (left) with a Fusion Manage field (right):

| Column | Meaning |
|---|---|
| **Fusion field** | The source: a Data Model property. |
| **Manage field** | The Fusion Manage field it fills, shown with its title and ID. |
| **Key** | The *match key*: the one mapping used to find an existing item so it is updated rather than duplicated. |

**Add default fields** replaces the mappings with the standard set:

| Source | Fusion Manage field ID | Notes |
|---|---|---|
| Part number | `NUMBER` | Match key |
| Name | `TITLE` | |
| Description | `DESCRIPTION` | |
| Thumbnail | `IMAGE` | Image of the component, sent as a file |
| Material | `MATERIAL` | Read from the Data Model's `materialName` |

### Available sources

- **Built-in fields**: Part number, Name, Description, Revision, Material, Lifecycle state and Thumbnail.
- **Custom and base properties**: any property defined on your Manufacturing Data Model items can be mapped by name.
- **Physical properties**: Mass, Volume, Area, Density, Length, Width and Height (Length, Width and Height are the bounding box). They are read only when a mapping uses them.

### Rules the settings enforce

- The workspace ID must be a number.
- Every row needs both a source and a Fusion Manage field.
- A source can be mapped only once, and a Fusion Manage field can be filled only once, whether by a mapping, a static value or the component-linking field.
- Exactly one mapping must be the **Key**. Only property values can be the key; the thumbnail and physical properties cannot.

### Picklist and number fields

If the target field is a picklist, the add-in looks up the picklist's options and sends the matching option. A value with no matching option is left out and reported (see [Troubleshooting and Limitations](09-troubleshooting-and-limitations.md)). Numeric values are rounded to the precision the Fusion Manage field takes.

## Static values

A static value sets a Fusion Manage field to the same value on every published item, regardless of the design. Pick the field, then enter or choose the value (a picklist field offers its options). For an existing item, a static value is applied when the item lacks it.

## Component linking

If your Items workspace has a field that links an item to a record in the Fusion Manage components picklist, choose it under **Component linking** (**Choose the linking field…**). When publishing, the add-in links each item to its component: first through the link stored in the Data Model, and if there is none, by searching the component picklist for the item number. If neither finds it, the item is still published and the step is recorded as a failed "component link" in the run's files.

## When the buttons light up

The ribbon and context-menu buttons, other than **Preferences**, stay disabled until the Items workspace is usable: a workspace ID is set, the mappings are valid, and a match key is chosen. The tooltip says what is still missing.
