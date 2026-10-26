"""Publishing: turn the compared design into Fusion Manage requests and files.

* ``item_requests`` and ``bom_requests``: the Fusion Manage requests (pure functions, no I/O).
* ``writer``: the output folder and its ``manifest.json``.
* ``exporters``: files made with the Fusion API (STEP).
* ``runner``: the steps of one publish run, which sends each request as it is written.
* ``sender``: sending requests, and sending a finished folder again (a retry).
"""
