---
title: Job Queue
---

# Job Queue

Every publish is a **job**. The Job Queue shows the jobs that are waiting, running and finished, so you can see what the add-in is doing without keeping the Publish panel open.

Open it with **Fusion Manage ▸ Administration ▸ Job Queue**.

## Request Files and Retry

What each run keeps on disk, and how to send a folder again. [Read more](request-files-and-retry.md).


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
- **Send to Fusion Manage** sends a folder you choose. See [Request Files and Retry](request-files-and-retry.md).

## Knowing when something ends

!!! example "Screenshot placeholder: Job Queue ribbon button states"
    **Show:** The ribbon button in its idle, running and error looks.

    Save the image as `docs/images/job-queue-button.png`, then replace this box with `![Job Queue ribbon button states](../images/job-queue-button.png)`.

You do not have to watch the panel.

- The **Job Queue** button on the ribbon changes its icon: one for a job that is working, another when a listed job has failed.
- When a job ends, a message box reports the result. A publish that completed shows **Total Items Processed**, **Total Items Created** and **Total Items Updated**. A failure lists the items that failed and why. This appears even if the Publish and Job Queue panels are closed.

## A failed job

Open the Job Queue and read the reason on each failed row. Fix the cause, then use **Send to Fusion Manage** on the job's folder to retry. What Fusion Manage already accepted is skipped. For common causes, see [Troubleshooting and Limitations](../reference/troubleshooting.md#publishing).
