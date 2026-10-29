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
    links cannot lead out of ``root``, and by file identity, so the letter case of a name does not matter where the filesystem ignores it
    (Windows, and macOS by default)."""
    if not root or not path or os.path.islink(path):
        return False
    real_path = os.path.realpath(path)
    try:
        # a drive's or the filesystem's own root is its own parent: it would pass the first test, so the second one is needed
        return (os.path.isdir(real_path) and os.path.samefile(os.path.dirname(real_path), root)
                and not os.path.samefile(real_path, root))
    except OSError:   # ``root`` is not there, or one of them went while it was being looked at
        return False


def remove_run(root: Optional[str], path: str) -> bool:
    """Remove the folder of one run or upload, only when it is directly inside ``root``. Never raises: a failure is logged and the folder stays
    (or what could not be removed of it). Returns whether it was removed; a folder that is not there already is not an error, and not removed."""
    try:
        if not path or not os.path.exists(path):   # cleared before: a run that ended clean has its files removed, and is cleared later
            log.debug("Not removing %s: it is not there", path)
            return False
        if root is None or not _inside(root, path):
            log.warning("Not removing %s: it is not a run folder inside %s", path, root)
            return False
        shutil.rmtree(path, ignore_errors=True)
        if os.path.exists(path):   # a file in use, say: what could be removed was
            log.warning("Could not remove all of %s", path)
            return False
        return True
    except Exception:   # noqa: BLE001 - tidying up must never stop the add-in
        log.exception("Could not remove the run folder %s", path)
        return False
