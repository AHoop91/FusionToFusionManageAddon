"""Palette action that tells whether the signed-in user is an admin of the active hub."""

import threading
import time
from typing import Any, Callable, Dict, Set, Tuple

from ...config.config_service import ConfigService
from ...core.logging_setup import get_logger
from ...fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ...fusion_mfg.hub_lookup import read_hub_id
from ...fusion_mfg.hub_role import UNKNOWN as ROLE_UNKNOWN, HubRole, read_hub_role
from ..message_bridge import MessageBridge
from .background import Runner, in_thread

log = get_logger("hub_actions")

ACTION = "get_hub_role"
PENDING, ADMIN, MEMBER, UNKNOWN = "pending", "admin", "member", "unknown"
KEPT_SECONDS = 600   # a clear answer is used for this long, then asked for again: a role can change while Fusion stays open
RETRY_AFTER_SECONDS = 15   # an answer that could not be had is reported as unknown for this long, so the panel stops asking; then it asks again

Key = Tuple[str, str]   # (hub id in Fusion, the user's email in lower case)


def _fusion_user_email() -> str:
    import adsk.core   # Fusion's module is loaded when asked, so this file imports without Fusion
    return str(adsk.core.Application.get().currentUser.email or "")


def _answer(role: HubRole) -> Dict[str, Any]:
    if not role.known:
        return {"state": UNKNOWN, "role": ""}
    return {"state": ADMIN if role.admin else MEMBER, "role": role.role}


class HubRoles:
    """The user's role in the active hub.

    The role is read from the Data Model on a worker thread, which pushes the answer to the panel when it has it (``get`` answers ``pending``
    meanwhile), so Fusion's thread is never blocked. A clear answer is kept for ``KEPT_SECONDS``, per hub and user; one that could not be had
    (the network, the service) is not, so a later call asks again. Any thread may use it, but ``get`` reads Fusion's user: call it on Fusion's.
    """

    def __init__(self, bridge: MessageBridge, config: ConfigService, user_email: Callable[[], str] = _fusion_user_email,
                 run: Runner = in_thread, clock: Callable[[], float] = time.monotonic) -> None:
        self._bridge, self._config, self._user_email, self._run, self._clock = bridge, config, user_email, run, clock
        self._kept: Dict[Key, Tuple[HubRole, float]] = {}   # key -> role, and when it was read
        self._hub_ids: Dict[str, str] = {}   # hub id in Fusion -> the Data Model's id of the hub
        self._running: Set[Key] = set()
        self._failed_at: Dict[Key, float] = {}   # when a read last ended without an answer
        self._lock = threading.Lock()

    def get(self, refresh: bool = False) -> Dict[str, Any]:
        """The role, ``pending`` while it is read, or ``unknown`` when there is no hub or user, or a read just failed.

        ``refresh``: the panel was opened or came back, and a role may have changed since it was read, so it is read again.
        """
        email = self._user_email()   # Fusion's user: read here, on Fusion's thread
        key = (self._config.hub_id, email.strip().lower())
        if not key[0] or not key[1]:
            return _answer(ROLE_UNKNOWN)
        with self._lock:
            if refresh:
                self._kept.pop(key, None)
                self._failed_at.pop(key, None)
            now = self._clock()
            kept = self._kept.get(key)
            if kept and now - kept[1] < KEPT_SECONDS:
                return _answer(kept[0])
            if key in self._running:
                return {"state": PENDING, "role": ""}
            failed_at = self._failed_at.get(key)
            if failed_at is not None and now - failed_at < RETRY_AFTER_SECONDS:
                return _answer(ROLE_UNKNOWN)
            self._running.add(key)
            hub_name = self._config.hub_name
        self._run(lambda: self._read(key, hub_name))   # outside the lock: a runner may do the work at once, and the read takes the lock
        return {"state": PENDING, "role": ""}

    def _data_model_hub_id(self, client: FusionGraphQlClient, fusion_hub_id: str, hub_name: str) -> str:
        """The Data Model's id of the hub, asked for once."""
        with self._lock:
            known = self._hub_ids.get(fusion_hub_id)
        if not known:
            known = read_hub_id(client, hub_name)
            if known:
                with self._lock:
                    self._hub_ids[fusion_hub_id] = known
        return known

    def _read(self, key: Key, hub_name: str) -> None:
        role = ROLE_UNKNOWN
        try:
            client = FusionGraphQlClient()
            role = read_hub_role(client, self._data_model_hub_id(client, key[0], hub_name), key[1])
            log.info("Role in hub %r: %s", hub_name, (role.role or "not an admin") if role.known else "could not be found out")
        except Exception:  # noqa: BLE001 - never leave the panel waiting
            log.exception("Could not read the hub role")
        with self._lock:
            if role.known:
                self._kept[key] = (role, self._clock())
            else:
                self._failed_at[key] = self._clock()
            self._running.discard(key)
        if self._config.hub_id == key[0]:   # not if the user has moved to another hub since the read began
            self._bridge.push(ACTION, _answer(role))


def register_hub_actions(bridge: MessageBridge, config: ConfigService) -> None:
    """Register ``get_hub_role``."""
    roles = HubRoles(bridge, config)
    bridge.register(ACTION, lambda payload: roles.get(bool(payload.get("refresh"))))

    try:   # start the read now, while the add-in loads: by the time Preferences is opened the answer is usually there
        roles.get()
    except Exception:  # noqa: BLE001 - a head start, nothing more
        log.exception("Could not start reading the hub role")
