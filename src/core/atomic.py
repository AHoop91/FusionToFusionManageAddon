"""Writing a file whole or not at all.

The data goes to a file beside the target, which is then swapped in, so a crash or a full disk leaves the old file or the new one and
never half of one.
"""

import os
import time

REPLACE_TRIES = 8   # a file that is replaced while a scanner or indexer has the old one open is refused for a moment (Windows)
REPLACE_WAIT = 0.02   # seconds, and more with each try


def write_atomically(path: str, data: bytes) -> None:
    """Write ``data`` as the whole of the file at ``path`` (its folder is there already). Raises ``OSError`` when it cannot be written."""
    temporary = path + ".tmp"
    with open(temporary, "wb") as handle:
        handle.write(data)
    replace_file(temporary, path)


def replace_file(source: str, target: str) -> None:
    """Put ``source`` in place of ``target``, trying again for a moment if the system refuses (a scanner or indexer has ``target`` open)."""
    for attempt in range(1, REPLACE_TRIES + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES:
                raise
            time.sleep(REPLACE_WAIT * attempt)
