"""Logging configuration.

Logs go to a rotating file in the user profile so support can collect them
without needing Fusion's text command window.

What is logged about an API call is its method, endpoint (no query string), status, duration, a request id, the size of the answer and the
fields of ``ALLOWED_FIELDS``: never the body. A body holds business and personal data, and no pattern can name every secret in one, so
bodies are written only when verbose logging is switched on (see ``verbose``). Secrets (tokens, client secrets) must also never be passed to
the logger; as a safety net, anything that looks like one is masked before it is written (``RedactingFormatter``), in verbose logs too.
"""

import copy
import json
import logging
import logging.handlers
import os
import re
import uuid
from typing import Any, List, Union

from .constants import ADDIN_NAME
from .paths import DataDirError, inside_temp, log_dir, temp_dir

_CONFIGURED = False

LOG_DIR_ENV = "MFGTOFM_LOG_DIR"   # puts the logs in this folder of the temporary folder instead of the user profile (the tests use it)
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


# What a log may say of an answer's content. Each key is one seen in a real answer (``dev/validation.md``) and holds a code, not data. A value
# is kept only when it has the shape that key's codes have (``CODE_SHAPES``): a number for ``statusCode``, ``GEN_INVALID_INPUT_SCHEMA`` for
# ``errorCode``, ``APIError`` for ``errorClass``, ``errors.required``, ``FHQ-403`` or ``DATA_NOT_READY`` for ``code``. Free text, a name or an
# item number under one of the keys is left out (an upper-case code needs an underscore, so a surname in capitals is not one). What still
# passes is a word that happens to have the shape: the keys, not the shapes, are what keep data out.
ALLOWED_FIELDS = ("statusCode", "errorCode", "errorClass", "code")
ALLOWED_NESTED = ("errors", "extensions")   # the objects and lists that hold more of ``ALLOWED_FIELDS``
CODE_SHAPES = {
    "statusCode": re.compile(r"[1-5][0-9]{2}"),
    "errorCode": re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,7}"),
    "errorClass": re.compile(r"[A-Z][A-Za-z]{0,40}(?:Error|Exception)"),
    "code": re.compile(r"errors(?:\.[a-z]+){1,3}|FHQ-[0-9]{3}|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+){1,7}"),
}
MAX_ALLOWED = 8   # fields kept from one answer
MAX_NESTED = 5   # entries of a list read
MAX_DEPTH = 3


def allowed_code(key: str, value: Any) -> bool:
    """Whether ``value`` may be logged as the ``key`` of an answer: a text or whole number of the shape that key's codes have."""
    return not isinstance(value, bool) and isinstance(value, (str, int)) and key in CODE_SHAPES and bool(CODE_SHAPES[key].fullmatch(str(value)))


def _collect(node: Any, prefix: str, found: List[str], depth: int) -> None:
    """Add the allowed fields of the object ``node``, and of the objects in the ``ALLOWED_NESTED`` keys, to ``found`` named from ``prefix``."""
    if depth > MAX_DEPTH or not isinstance(node, dict):
        return
    for key in ALLOWED_FIELDS:
        value = node.get(key)
        if allowed_code(key, value) and len(found) < MAX_ALLOWED:
            found.append(f"{prefix}{key}={value}")
    for key in ALLOWED_NESTED:
        child = node.get(key)
        if isinstance(child, dict):
            _collect(child, f"{prefix}{key}.", found, depth + 1)
        elif isinstance(child, list):
            _collect_list(child, f"{prefix}{key}", found, depth)


def _collect_list(items: List[Any], name: str, found: List[str], depth: int) -> None:
    """Add the allowed fields of the first ``MAX_NESTED`` objects in the list ``items`` (the key ``name``) to ``found``."""
    for index, item in enumerate(items[:MAX_NESTED]):
        _collect(item, f"{name}[{index}].", found, depth + 1)


def allowed_fields(raw: Union[bytes, str, None]) -> str:
    """The fields of ``ALLOWED_FIELDS`` in a JSON answer as ``key=value`` words ("" when it has none, is empty or is not JSON)."""
    try:
        data = json.loads(raw or b"")
    except (ValueError, RecursionError):   # not JSON, or nested so deep it cannot be read: a log line must not be what fails
        return ""
    found: List[str] = []
    _collect(data, "", found, 0)
    return " ".join(found)


def describe_body(raw: Union[bytes, str, None]) -> str:
    """What a log says of an answer or a request body: its size and its allowed fields, never its content."""
    size = len(raw or b"")
    return " ".join(part for part in (f"{size} bytes", allowed_fields(raw)) if part)


DEBUG_BODY_CHARS = 20000   # of a body a verbose log keeps


def log_body(logger: logging.Logger, what: str, content: Any, address: str = "") -> None:
    """Write a body (or any content of an answer) to ``logger``, only in a verbose log, clipped. Every body that is logged goes through here,
    so switching verbose logging off is what keeps them out of the log."""
    if logger.isEnabledFor(logging.DEBUG):
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        logger.debug("%s %s: %s", what, address, text[:DEBUG_BODY_CHARS])


def endpoint(address: str) -> str:
    """``address`` (a url or a path) without its query string or fragment, which hold search terms and signed access."""
    return re.split(r"[?#]", address, maxsplit=1)[0]


def new_request_id() -> str:
    """A short id to tie together the lines one call logs (its tries, its failure, its end)."""
    return uuid.uuid4().hex[:8]


def _loggable(value: Any) -> Any:
    """What a log says for ``value``: an error that carries server text gives ``log_text`` (its status and allowed fields) instead."""
    text = getattr(value, "log_text", None)
    return text if isinstance(text, str) else value


def _one_line(text: str) -> str:
    """``text`` with its line breaks made visible, so a message that quotes outside text (a redirect's ``error_description`` is chosen by whoever
    called the address) cannot start a line of its own that looks like another log entry."""
    return text.replace("\r", "\\r").replace("\n", "\\n")


MIN_REPLACED_CHARS = 8   # an error message shorter than this is not looked for in a traceback: it would match unrelated text


def _text_of(error: BaseException) -> str:
    try:
        return str(error)
    except Exception:   # noqa: BLE001 - an error whose text cannot be made must not make the log line fail
        return ""


class RedactingFormatter(logging.Formatter):
    """The log line format, with secrets masked in the message and in any traceback.

    An argument that has a ``log_text`` (``FmApiError``, ``MfgApiError``) is written as that, not as its message, which may quote what the
    server answered; the same goes for the message in a traceback.
    """

    def format(self, record: logging.LogRecord) -> str:
        record = copy.copy(record)   # the record is shared with the other handlers: what is changed here is for this one
        if isinstance(record.args, tuple):
            record.args = tuple(_loggable(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _loggable(v) for k, v in record.args.items()}
        record.msg, record.args = _one_line(record.getMessage()), None
        record.exc_text = None   # made again below, so a traceback another handler formatted first (with the real messages) is not reused
        return redact(super().format(record))

    def formatException(self, exc_info: Any) -> str:
        """The traceback with the message of every error in its chain (``raise ... from``, and the one being handled) that has a ``log_text``
        written as that. The longest messages go first, so one that holds another's message is replaced whole."""
        text = super().formatException(exc_info)
        chain: List[BaseException] = []
        pending = [exc_info[1]]
        while pending:
            error = pending.pop()
            if error is None or any(error is seen for seen in chain):
                continue
            chain.append(error)
            pending += [error.__cause__, error.__context__]
        for error in sorted(chain, key=lambda e: len(_text_of(e)), reverse=True):
            safe, message = getattr(error, "log_text", None), _text_of(error)
            if isinstance(safe, str) and len(message) >= MIN_REPLACED_CHARS:
                text = text.replace(message, safe)
        return text


def log_directory() -> str:
    """Return (and create) the log directory: ``MFGTOFM_LOG_DIR`` when it is a folder in the system's temporary folder, else the per-user one
    (the add-in's own folder in the temporary folder when the user's is not usable)."""
    path = os.environ.get(LOG_DIR_ENV, "")
    if not inside_temp(path):   # the variable is for the tests: it cannot send the logs anywhere else
        try:
            path = log_dir()
        except DataDirError:
            path = os.path.join(temp_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def verbose() -> bool:
    """True when verbose (development) logging is on: ``MFGTOFM_DEBUG=1``, or a ``debug.flag`` file in the log directory.

    Only verbose logs carry request and response bodies, so they may hold business and personal data: never share them unreviewed. Nothing
    else switches bodies on, and the others log none (see ``describe_body``).
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
            root.warning("Verbose logging is on: request and response bodies are written to this log. Do not share it unreviewed.")
    return root if name == ADDIN_NAME else root.getChild(name)


def shutdown_logging() -> None:
    """Close handlers so the log file is released when the add-in stops."""
    global _CONFIGURED
    root = logging.getLogger(ADDIN_NAME)
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    _CONFIGURED = False
