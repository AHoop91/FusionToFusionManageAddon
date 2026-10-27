"""Palette action that tells whether the signed-in user is an admin of the active hub."""

import threading
import time
from typing import Any, Dict, Tuple

import adsk.core

from ...config.config_service import ConfigService
from ...core.logging_setup import get_logger
from ...fusion_mfg.fusion_graphql_client import FusionGraphQlClient
from ...fusion_mfg.hub_role import HubRole, read_hub_role
from ...fusion_mfg.properties import HUBS_QUERY, find_hub_id
from ..message_bridge import MessageBridge

log = get_logger("hub_actions")

PENDING, ADMIN, MEMBER, UNKNOWN = "pending", "admin", "member", "unknown"
KEPT_SECONDS = 600   # a clear answer is used for this long, then asked for again: a role can change while Fusion stays open
RETRY_AFTER_SECONDS = 15   # an answer that could not be had is reported as unknown for this long, so the panel stops asking; then it asks again


def register_hub_actions(bridge: MessageBridge, config: ConfigService) -> None:
    """Register ``get_hub_role``.

    The role is read from the Data Model on a worker thread, which pushes the answer to the panel when it has it (the action itself answers
    ``pending`` meanwhile), so Fusion's thread is never blocked. A clear answer is kept for ``KEPT_SECONDS``, per hub and user; one that
    could not be had (the network, the service) is not, so the next call asks again.
    """

    kept: Dict[Tuple[str, str], Tuple[HubRole, float]] = {}   # (hub id, email) -> role, and when it was read
    hub_ids: Dict[str, str] = {}   # hub id in Fusion -> the Data Model's id of the hub
    running: Dict[Tuple[str, str], bool] = {}
    failed_at: Dict[Tuple[str, str], float] = {}   # when a read last ended without an answer
    lock = threading.Lock()

    def answer(role: HubRole) -> Dict[str, Any]:
        if not role.known:
            return {"state": UNKNOWN, "role": ""}
        return {"state": ADMIN if role.admin else MEMBER, "role": role.role}

    def tell_panels(key: Tuple[str, str]) -> None:
        """Push the outcome of a read to the panels, unless the user has moved to another hub since it began."""
        if config.hub_id != key[0]:
            return
        with lock:
            fresh = kept.get(key)
            result = answer(fresh[0]) if fresh else {"state": UNKNOWN, "role": ""}
        bridge.push("get_hub_role", result)

    def read(key: Tuple[str, str], hub_name: str) -> None:
        try:
            client = FusionGraphQlClient()   # Fusion's own sign-in: the role is known before any Client ID exists
            with lock:
                known = hub_ids.get(key[0])
            if known is None:
                known = find_hub_id(client.query(HUBS_QUERY), hub_name)
                with lock:
                    hub_ids[key[0]] = known
            role = read_hub_role(client, known, key[1])
            log.info("Role in hub %r: %s", hub_name, f"{role.role or 'not an admin'}" if role.known else "could not be found out")
            with lock:
                if role.known:
                    kept[key] = (role, time.monotonic())
                else:
                    failed_at[key] = time.monotonic()
        except Exception:  # noqa: BLE001 - never leave the panel waiting
            log.exception("Could not read the hub role")
            with lock:
                failed_at[key] = time.monotonic()
        finally:
            with lock:
                running.pop(key, None)
        tell_panels(key)

    def get_hub_role(payload: Dict[str, Any]) -> Dict[str, Any]:
        email = str(adsk.core.Application.get().currentUser.email or "")   # Fusion's user: read here, on Fusion's thread
        key = (config.hub_id, email.strip().lower())
        if not key[0] or not key[1]:
            return {"state": UNKNOWN, "role": ""}
        with lock:
            if payload.get("refresh"):   # the panel was opened or came back: a role may have changed since it was read
                kept.pop(key, None)
                failed_at.pop(key, None)
            if key in kept and time.monotonic() - kept[key][1] < KEPT_SECONDS:
                return answer(kept[key][0])
            if key in running:
                return {"state": PENDING, "role": ""}
            if time.monotonic() - failed_at.get(key, -RETRY_AFTER_SECONDS) < RETRY_AFTER_SECONDS:
                return {"state": UNKNOWN, "role": ""}
            running[key] = True
            threading.Thread(target=read, args=(key, config.hub_name), daemon=True).start()
            return {"state": PENDING, "role": ""}

    bridge.register("get_hub_role", get_hub_role)

    try:   # start the read now, while the add-in loads: by the time Preferences is opened the answer is usually there
        get_hub_role({})
    except Exception:  # noqa: BLE001 - a head start, nothing more
        log.exception("Could not start reading the hub role")
