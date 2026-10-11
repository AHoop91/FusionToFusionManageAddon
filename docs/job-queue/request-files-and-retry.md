---
title: Request Files and Retry
---

# Request Files and Retry

## What a run keeps

Every publish keeps its files, in a `publishes` folder in your user profile. The path is listed in [Troubleshooting and Limitations](../reference/troubleshooting.md#where-files-are-kept). Each run has its own folder, containing:

| File | What it holds |
|---|---|
| Per-item request JSON | The exact request written for each item, a create or an update |
| Thumbnails | The images downloaded for the items |
| `bom/` | The BOM requests for each parent assembly |
| `manifest.json` | A summary of the run |
| `send-log.json` | A record of every request Fusion Manage accepted |

The files are a record of what was sent, and what the retry below works from.

## Retry a failed run, or send after review

1. Open the [Job Queue](index.md).
2. Click **Send to Fusion Manage**.
3. Choose the run's folder.
4. Read the confirmation, then confirm.

The confirmation shows:

- the tenant and workspace;
- how many items will be created and updated;
- how many BOM requests there are;
- how many requests an earlier try already sent, which will be skipped.

!!! warning
    This changes real data in Fusion Manage. Check the tenant and workspace in the confirmation.

### Nothing is sent twice

**What Fusion Manage already accepted is skipped.** The `send-log.json` in the folder records each accepted request, so sending a folder again carries on from where it stopped instead of creating items twice.

An item whose creation failed is not there for its BOM, so that BOM fails too. The other items carry on. After you fix the cause and send the folder again, the item and then its BOM go through.

### Folders it will not send

The add-in refuses a folder that is not a publish folder (it has no `manifest.json`), or that was written by an older version. In that case, publish again. A folder with no requests in it reports that there is nothing to send.
