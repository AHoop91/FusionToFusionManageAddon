---
title: Job Queue
---

# Job Queue

Every publish is a **job**. The Job Queue shows the jobs that are waiting, running and finished, so you can see what the add-in is doing without keeping the Publish panel open.

Open it with **Fusion Manage ▸ Administration ▸ Job Queue**.


## How jobs run

Jobs go through a **single queue, one after another**. A publish returns at once, and the work happens in the background, so Fusion stays responsive and you can keep working, even in another design. A job that is waiting shows its place, for example *Waiting, number 2 in the queue*.

## Reading the queue

The panel lists every job, newest first, with one row per item. Each row shows a status icon, and hovering it shows the reason when there is one.

!!! example "Screenshot placeholder: Job Queue with a completed and a failed run"
    **Show:** Job cards with status icons, one row per item, and the Cancel button on an active job.

    Save the image as `docs/images/job-queue-panel.png`, then replace this box with `![Job Queue with a completed and a failed run](../images/job-queue-panel.png)`.

| Status | Meaning |
|---|---|
| **Queued** | Waiting for earlier jobs to finish |
| **Running** | Being prepared or sent |
| **Done** | Completed |
| **Error** | Failed. The full reason is on the row |
| **Cancelled** | Stopped before it finished |

Each BOM sent for a parent assembly also has its own row, after the items.

## Actions

- **Cancel** stops a job that is waiting or running. Items already processed are kept in the run's folder, and the rest are not published.
- **Clear finished** removes finished jobs from the list. A job that finished with every row done removes itself.
- **Send to Fusion Manage** sends a folder you choose. See [Request Files and Retry](#).

## Knowing when something ends

!!! example "Screenshot placeholder: Job Queue ribbon button states"
    **Show:** The ribbon button in its idle, running and error looks.

    Save the image as `docs/images/job-queue-button.png`, then replace this box with `![Job Queue ribbon button states](../images/job-queue-button.png)`.

You do not have to watch the panel.

- The **Job Queue** button on the ribbon changes its icon: one for a job that is working, another when a listed job has failed.
- When a job ends, a message box reports the result. A publish that completed shows **Total Items Processed**, **Total Items Created** and **Total Items Updated**. A failure lists the items that failed and why. This appears even if the Publish and Job Queue panels are closed.

## A failed job

Open the Job Queue and read the reason on each failed row. Fix the cause, then use **Send to Fusion Manage** on the job's folder to retry. What Fusion Manage already accepted is skipped. For common causes, see [Troubleshooting and Limitations](../reference/troubleshooting.md#publishing).

## Request Files and Retry

### What a run keeps

Every publish keeps its files, in a `publishes` folder in your user profile. The path is listed in [Troubleshooting and Limitations](../reference/troubleshooting.md#where-files-are-kept). Each run has its own folder, containing:

!!! example "Screenshot placeholder: A run's folder in File Explorer"
    **Show:** The folder of a run with the request files, bom folder, manifest.json and send-log.json.

    Save the image as `docs/images/publish-folder.png`, then replace this box with `![A run's folder in File Explorer](../images/publish-folder.png)`.

| File | What it holds |
|---|---|
| Per-item request JSON | The exact request written for each item, a create or an update |
| Thumbnails | The images downloaded for the items |
| `bom/` | The BOM requests for each parent assembly |
| `manifest.json` | A summary of the run |
| `send-log.json` | A record of every request Fusion Manage accepted |

The files are a record of what was sent, and what the retry below works from.

### Retry a failed run, or send after review

!!! example "Screenshot placeholder: Send to Fusion Manage confirmation"
    **Show:** The confirmation with the tenant, workspace, creates, updates, BOM requests and already-sent count.

    Save the image as `docs/images/send-confirmation.png`, then replace this box with `![Send to Fusion Manage confirmation](../images/send-confirmation.png)`.

1. Open the [Job Queue](#job-queue).
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

#### Nothing is sent twice

**What Fusion Manage already accepted is skipped.** The `send-log.json` in the folder records each accepted request, so sending a folder again carries on from where it stopped instead of creating items twice.

An item whose creation failed is not there for its BOM, so that BOM fails too. The other items carry on. After you fix the cause and send the folder again, the item and then its BOM go through.

#### Folders it will not send

The add-in refuses a folder that is not a publish folder (it has no `manifest.json`), or that was written by an older version. In that case, publish again. A folder with no requests in it reports that there is nothing to send.
