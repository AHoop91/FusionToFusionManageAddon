"""Logging configuration.

Logs go to a rotating file in the user profile so support can collect them
without needing Fusion's text command window. Secrets (tokens, client
secrets) must never be passed to the logger; as a safety net, anything that
looks like one is masked before it is written (``RedactingFormatter``).
"""

import logging
import logging.handlers
import os
import re

from .constants import ADDIN_NAME

_CONFIGURED = False

LOG_DIR_ENV = "MFGTOFM_LOG_DIR"   # puts the logs in this folder instead of the user profile (the tests use it)
DEBUG_ENV = "MFGTOFM_DEBUG"
DEBUG_FLAG_FILE = "debug.flag"   # an empty file of this name in the log directory switches verbose logging on


MASK = "[redacted]"
_SECRETS = re.compile(
    r'(?i)(?:'
    r'(?P<q>[?&;]|\b)(?P<key>x-amz-[a-z-]+|x-goog-[a-z-]+|awsaccesskeyid|signature|sig|token|access_token|refresh_token|id_token|client_secret|password)=[^&"\'\s]+'   # signed links and forms
    r'|(?P<cq>[?&])code=[^&"\'\s]+'   # the sign-in code of a redirect (only in a query: "status code=404" is not one)
    r'|(?P<jkey>"(?:access_token|refresh_token|id_token|client_secret|password|token)"\s*:\s*)"[^"]*"?'   # JSON bodies
    r'|(?P<scheme>\b(?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]+'   # authorization headers
    r'|(?P<cookie>\b(?:set-)?cookie\s*:\s*)[^\r\n]+'   # cookies, whole line
    r'|(?P<jwt>\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}(?:\.[A-Za-z0-9_-]*)?)'   # a JSON web token wherever it turns up
    r')')


def redact(text: str) -> str:
    """``text`` with tokens, signatures and passwords masked: signed links (an S3 address carries its access in the query), JSON
    token fields, bearer and basic headers, cookies and bare JSON web tokens. A value cut short by a clip is masked to its end.
    Only what looks like a secret is masked: an unlabelled opaque secret is not found."""
    def mask(match: "re.Match[str]") -> str:
        if match.group("key"):
            return f"{match.group('q')}{match.group('key')}={MASK}"
        if match.group("cq"):
            return f"{match.group('cq')}code={MASK}"
        if match.group("jkey"):
            return f'{match.group("jkey")}"{MASK}"'
        if match.group("scheme"):
            return f"{match.group('scheme')}{MASK}"
        if match.group("cookie"):
            return f"{match.group('cookie')}{MASK}"
        return MASK
    return _SECRETS.sub(mask, text)


class RedactingFormatter(logging.Formatter):
    """The log line format, with secrets masked in the message and in any traceback."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def log_directory() -> str:
    """Return (and create) the log directory: ``MFGTOFM_LOG_DIR`` when set, else the per-user one."""
    path = os.environ.get(LOG_DIR_ENV) or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/Library/Logs"), ADDIN_NAME, "logs")
    os.makedirs(path, exist_ok=True)
    return path


def verbose() -> bool:
    """True when verbose (development) logging is on: ``MFGTOFM_DEBUG=1``, or a ``debug.flag`` file in the log directory.

    Verbose logs carry full request and response bodies, so they may hold business data: never share them unreviewed.
    Read when the add-in starts; restart it after changing the flag.
    """
    if os.environ.get(DEBUG_ENV, "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return os.path.exists(os.path.join(log_directory(), DEBUG_FLAG_FILE))


def get_logger(name: str = ADDIN_NAME) -> logging.Logger:
    """Return a logger, configuring the file handler on first use."""
    global _CONFIGURED
    root = logging.getLogger(ADDIN_NAME)
    if not _CONFIGURED:
        root.setLevel(logging.DEBUG if verbose() else logging.INFO)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_directory(), f"{ADDIN_NAME}.log"),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        _CONFIGURED = True
        if root.level == logging.DEBUG:
            root.debug("Verbose logging is on")
    return root if name == ADDIN_NAME else root.getChild(name)


def shutdown_logging() -> None:
    """Close handlers so the log file is released when the add-in stops."""
    global _CONFIGURED
    root = logging.getLogger(ADDIN_NAME)
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    _CONFIGURED = False
