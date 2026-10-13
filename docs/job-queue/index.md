---
title: Job Queue
---

# Job Queue

Every publish is a **job**. The Job Queue shows the jobs that are waiting, running and finished, so you can see what the add-in is doing without keeping the Publish panel open.

Open it with **Manage ▸ Item Management ▸ Administration ▸ Job Queue**.


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
- **Retry** appears on a job that failed or has failed rows. It sends the failed requests again. See [Request Files and Retry](#request-files-and-retry).

## Knowing when something ends

!!! example "Screenshot placeholder: Job Queue ribbon button states"
    **Show:** The ribbon button in its idle, running and error looks.

    Save the image as `docs/images/job-queue-button.png`, then replace this box with `![Job Queue ribbon button states](../images/job-queue-button.png)`.

You do not have to watch the panel.

- The **Job Queue** button on the ribbon changes its icon: one for a job that is working, another when a listed job has failed.
- When a job ends, a message box reports the result. A publish that completed shows **Total Items Processed**, **Total Items Created** and **Total Items Updated**. A failure lists the items that failed and why. This appears even if the Publish and Job Queue panels are closed.

## A failed job

Open the Job Queue and read the reason on each failed row. Fix the cause, then click **Retry** on the job. What Fusion Manage already accepted is skipped. For common causes, see [Troubleshooting and Limitations](../reference/troubleshooting.md#publishing).

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

### Retry a failed run

1. Open the [Job Queue](#job-queue).
2. Click **Retry** on the failed job.

The retry replaces the failed job in the list and sends the run's folder again, as a new job. It does not ask for confirmation, because it sends the same requests the run already wrote.

#### Nothing is sent twice

**What Fusion Manage already accepted is skipped.** The `send-log.json` in the folder records each accepted request, so sending a folder again carries on from where it stopped instead of creating items twice.

An item whose creation failed is not there for its BOM, so that BOM fails too. The other items carry on. After you fix the cause and click **Retry**, the item and then its BOM go through.

#### Folders it will not send

If the run's folder is missing or cannot be read (for example the run failed before it wrote its files), Retry says why in a message box. In that case, publish again.
