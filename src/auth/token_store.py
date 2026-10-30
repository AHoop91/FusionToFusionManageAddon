"""Encrypted token persistence.

Fusion's embedded Python does not ship the ``keyring`` package, so the
operating system's own facilities are used instead, one backend per platform:

* Windows: DPAPI (CryptProtectData) bound to the signed-in user; ciphertext
  is written to a file in the user profile.
* macOS: the login Keychain via the ``security`` command line tool.

Backends store opaque bytes; ``TokenStore`` handles the JSON encoding. Tokens
are never written to config or logs.
"""

import base64
import ctypes
import json
import os
import subprocess
import sys
from ctypes import wintypes
from typing import Any, Dict, Optional

from ..core.constants import ADDIN_NAME
from ..core.paths import data_dir

_KEYCHAIN_SERVICE = f"{ADDIN_NAME}.tokens"


# ---- Windows backend --------------------------------------------------------

class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_ENTROPY = f"{ADDIN_NAME}.tokens.v1".encode("utf-8")   # a program that only calls DPAPI as this user cannot read the file; one that knows this value can


def _dpapi(data: bytes, encrypt: bool, entropy: Optional[bytes] = _ENTROPY) -> bytes:
    """Run DPAPI encrypt/decrypt on ``data`` for the current user, with ``entropy`` mixed in (None for none)."""
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    extra = ctypes.create_string_buffer(entropy, len(entropy)) if entropy else None
    blob_extra = _DataBlob(len(entropy), ctypes.cast(extra, ctypes.POINTER(ctypes.c_char))) if entropy else None
    func = ctypes.windll.crypt32.CryptProtectData if encrypt \
        else ctypes.windll.crypt32.CryptUnprotectData
    args = [ctypes.byref(blob_in), None, ctypes.byref(blob_extra) if entropy else None, None, None, 0, ctypes.byref(blob_out)]
    if not func(*args):
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


class _DpapiBackend:
    """One DPAPI-encrypted file per client id under the user profile."""

    def __init__(self) -> None:
        self._dir = data_dir()   # raises when %LOCALAPPDATA% is not usable: the tokens are never kept anywhere else

    def _file(self, client_id: str) -> str:
        os.makedirs(self._dir, exist_ok=True)
        safe = "".join(c for c in client_id if c.isalnum())[:32] or "default"
        return os.path.join(self._dir, f"tokens_{safe}.bin")

    def save(self, client_id: str, payload: bytes) -> None:
        path = self._file(client_id)
        tmp_path = path + ".tmp"   # written whole, then swapped in, so a crash cannot leave a half-written file
        with open(tmp_path, "wb") as handle:
            handle.write(_dpapi(payload, True))
        os.replace(tmp_path, path)

    def load(self, client_id: str) -> Optional[bytes]:
        path = self._file(client_id)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as handle:
            blob = handle.read()
        try:
            return _dpapi(blob, False)
        except OSError:
            payload = _dpapi(blob, False, None)   # kept by an earlier version, without entropy: read it, then keep it the new way
            self.save(client_id, payload)
            return payload

    def clear(self, client_id: str) -> None:
        path = self._file(client_id)
        if os.path.exists(path):
            os.remove(path)


# ---- macOS backend ----------------------------------------------------------

def _quote(text: str) -> str:
    """``text`` as one double-quoted word of a ``security -i`` command line."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _KeychainBackend:
    """One login-Keychain generic password per client id."""

    def save(self, client_id: str, payload: bytes) -> None:
        # The command goes in on stdin (``security -i``), not on the command line, where any program could read the tokens from the process list.
        if any(ord(c) < 32 for c in client_id):
            raise ValueError("The Client ID holds a control character.")
        command = (f"add-generic-password -U -s {_quote(_KEYCHAIN_SERVICE)} -a {_quote(client_id)} "
                   f"-w {_quote(base64.b64encode(payload).decode('ascii'))}\n")
        subprocess.run(["security", "-i"], input=command, text=True, check=True, capture_output=True)

    def load(self, client_id: str) -> Optional[bytes]:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE,
             "-a", client_id, "-w"],
            check=True, capture_output=True, text=True,
        )
        return base64.b64decode(result.stdout.strip())

    def clear(self, client_id: str) -> None:
        subprocess.run(
            ["security", "delete-generic-password", "-s", _KEYCHAIN_SERVICE,
             "-a", client_id],
            capture_output=True,
        )


# ---- Public store -----------------------------------------------------------

class TokenStore:
    """Stores one token bundle (access/refresh/expiry) per client id."""

    def __init__(self, backend: Any = None) -> None:
        self._backend = backend or (_DpapiBackend() if sys.platform == "win32"
                                    else _KeychainBackend())

    def save(self, client_id: str, tokens: Dict[str, Any]) -> None:
        self._backend.save(client_id, json.dumps(tokens).encode("utf-8"))

    def load(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored bundle or None if absent/unreadable."""
        try:
            payload = self._backend.load(client_id)
            return json.loads(payload) if payload else None
        except (OSError, ValueError, subprocess.CalledProcessError):
            return None

    def clear(self, client_id: str) -> None:
        self._backend.clear(client_id)
