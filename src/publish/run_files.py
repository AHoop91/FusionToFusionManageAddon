"""The one temporary folder the add-in writes its working files into, and the only code that removes them.

Publish runs and uploads both write into ``MfgToFm`` in the system's temporary folder, each in a folder of its own directly inside
it. Nothing here ever deletes outside it: every removal first checks that the path is a folder directly inside that root, and is not a
link. A run's files go when it ends clean or is cleared from the Job Queue (a run that failed or was cancelled keeps them, for Retry); an
upload's go as soon as the file has been read.
"""

import os
import shutil
import tempfile
from typing import Optional

from ..core.logging_setup import get_logger

log = get_logger("run_files")

FOLDER_NAME = "MfgToFm"


def temp_root() -> str:
    """The folder publish runs and uploads write into: ``MfgToFm`` in the system's temporary folder."""
    return os.path.join(tempfile.gettempdir(), FOLDER_NAME)


def _inside(root: str, path: str) -> bool:
    """Is ``path`` a folder directly inside ``root`` (neither ``root`` itself, nor deeper, nor a link)? Compared by real path, so ``..`` and
    links cannot lead out of ``root``."""
    if not root or not path or os.path.islink(path):
        return False
    real_root, real_path = os.path.realpath(root), os.path.realpath(path)
    return os.path.dirname(real_path) == real_root and os.path.basename(real_path) not in ("", ".", "..") and os.path.isdir(real_path)


def remove_run(root: Optional[str], path: str) -> bool:
    """Remove the folder of one run or upload, only when it is directly inside ``root``. Never raises: a failure is logged and the folder stays. Returns
    whether it was removed."""
    try:
        if root is None or not _inside(root, path):
            log.warning("Not removing %s: it is not a run folder inside %s", path, root)
            return False
        shutil.rmtree(path, ignore_errors=True)
        return not os.path.exists(path)
    except Exception:   # noqa: BLE001 - tidying up must never stop the add-in
        log.exception("Could not remove the run folder %s", path)
        return False
