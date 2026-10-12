"""The tests log to a throwaway folder, so they never write into the add-in's own log.

Run them from the repository root with ``python -m unittest discover -s tests -t .``: the ``-t .`` makes ``tests`` a package, which is
what runs this file before anything else is imported.
"""

import atexit
import os
import shutil
import tempfile

_logs = tempfile.mkdtemp(prefix="mfgtofm-test-logs-")
os.environ["MFGTOFM_LOG_DIR"] = _logs
atexit.register(shutil.rmtree, _logs, ignore_errors=True)
