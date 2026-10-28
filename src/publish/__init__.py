"""Publishing: turn the compared design into Fusion Manage requests and files.

* ``item_requests`` and ``bom_requests``: the Fusion Manage requests (pure functions, no I/O), with ``placeholders`` for the ids only Fusion
  Manage knows.
* ``writer``: the output folder and its ``manifest.json``; ``run_files``: removing a run's folder.
* ``exporters``: files made with the Fusion API (STEP), for uploads.
* ``runner`` and ``read_ahead``: the steps of one publish run, which sends each request as it is written.
* ``sender``: sending requests, and sending a finished folder again (a retry).
* ``job_state`` and ``job_queue``: the jobs both runs are, and the queue that runs them; ``reports``: the message box text.
* ``panel_sections``: what the Publish panel reads of the design.
"""
