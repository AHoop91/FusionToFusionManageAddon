# Developer notes

This folder holds notes for people who change the add-in. It is not part of the published documentation: `docs/` is the public user site that mkdocs builds, and nothing in `dev/` is built or shipped.

The notes describe components that already exist, so a new feature uses them instead of writing a second copy.

## The rule

Before you write a new form, field control, list, view table, error display or drop-down, read the matching note below and reuse the component. If the component cannot do what you need, extend it (and update the note) rather than copy it.

## Start here

[glossary.md](glossary.md) lists what is already built, by what you need to do. Read it before you write anything new. The notes below go deeper on one topic each.

## Notes

| Note | Read it before you build |
| --- | --- |
| [pickers.md](pickers.md) | A drop-down, combo box, searchable list or chip box |
| [workspace-forms.md](workspace-forms.md) | A form for the items of a Fusion Manage workspace, or any field control |
| [tableaus.md](tableaus.md) | A table of a workspace's rows, a filters or columns panel, or anything that reads a view |
| [validation.md](validation.md) | A place that shows what Fusion Manage refused, or checks a value before it is sent |
| [permissions.md](permissions.md) | A control that depends on what the user may do in a workspace, or on being a Hub Admin |
| [manufacturing-data-model.md](manufacturing-data-model.md) | Anything that reads a design from the Manufacturing Data Model: components, properties, the BOM, thumbnails, hubs |
| [finding-items.md](finding-items.md) | Any search for an item or component in Fusion Manage, or any code that needs an item number |

## Keeping the notes true

- A note says only what the code does now. When you change a component, change its note in the same commit.
- Each note ends its description with a "What Fusion Manage answers" section (the refusal note has "The refusal Fusion Manage sends"). Every key there is marked Seen (in a real answer in the add-in log at `%LOCALAPPDATA%\MfgToFm\logs`) or Assumed (the code or tests rely on it). When you see a new real answer, move its shape to Seen. Do not add a key you have not seen.
