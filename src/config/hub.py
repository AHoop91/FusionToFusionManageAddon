"""The Fusion Manage tenant, taken from the hub that is active in Fusion.

The tenant is never read from settings or an imported file: it decides which host the access token is sent to, so it comes
only from the hub the user has open. Fusion's API may be called from its main thread only, so ``refresh`` reads the hub
there and the other threads read the kept value with ``current``.
"""

import re
import threading

from ..core.logging_setup import get_logger

log = get_logger("hub")

_TENANT = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def tenant_code(name: object) -> str:
    """The tenant a hub name stands for, lower case ("" when it is not a plain host name label, so it cannot redirect a request)."""
    text = str(name or "").strip().lower()
    return text if _TENANT.fullmatch(text) else ""


class HubTenant:
    """Keeps the tenant of the active hub for any thread to read."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tenant = ""

    def current(self) -> str:
        with self._lock:
            return self._tenant

    def refresh(self) -> None:
        """Read the active hub from Fusion. Main thread only."""
        tenant = ""
        try:
            import adsk.core
            hub = adsk.core.Application.get().data.activeHub
            tenant = tenant_code(hub.name) if hub else ""
        except Exception:  # noqa: BLE001 - keep what was known rather than fail an event handler
            log.exception("Could not read the active hub")
            return
        with self._lock:
            if tenant != self._tenant:
                log.info("Active hub tenant: %r", tenant)
            self._tenant = tenant
