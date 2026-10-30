"""What a piece of work on Fusion Manage is made under, taken once when it is asked for: the hub, the tenant, the connection, the Items
workspace and the sign-in. ``HubContexts`` is the one way to read them for work that spans threads or time (a publish, a load for the
Publish panel, the Item panel, an upload).

The settings can change while such work is under way (another hub opened in Fusion, a setting saved, another user signed in), so every step
of it reads this snapshot and never the live settings. What is read under it is stamped with ``HubContext.stamp``: what would reuse it (a
cached read, a publish made from a preview, an upload for an item shown) finds the stamp unchanged or starts again.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, replace
from functools import cached_property
from typing import Any, Callable, Dict, Optional, Tuple

from ..core.logging_setup import get_logger
from .config_service import ConfigService
from .models import ConnectionSettings
from .workspace_models import ITEMS_KIND, KINDS_BY_ID, WorkspaceConfig

log = get_logger("hub_context")


@dataclass(frozen=True)
class HubContext:
    """The hub, connection, Items workspace and sign-in one piece of work uses: copies, so a later change does not reach it."""

    hub_id: str
    settings: ConnectionSettings
    cfg: Optional[WorkspaceConfig]   # None for a hub whose Items workspace is not set up yet
    session: int   # which sign-in it was made under (``AuthService.session``): another user, or the same one again, is another

    @property
    def tenant(self) -> str:
        return self.settings.tenant

    @property
    def items_problem(self) -> str:
        """Why the Items workspace cannot be used yet ("" when its settings are complete)."""
        title = KINDS_BY_ID[ITEMS_KIND].title
        return self.cfg.setup_problem(title) if self.cfg else f"The {title} workspace ID is not set."

    @cached_property
    def stamp(self) -> str:
        """Identifies what a read, and the comparison with Fusion Manage that goes with it, depends on: the hub, the tenant, the whole Items
        workspace configuration (its id, mappings, default values and Component field) and the sign-in (what the user may see is theirs).
        Never empty. Worked out once: a load asks for it with every report of its progress."""
        basis = {"hub": self.hub_id, "tenant": self.tenant, "workspace": self.cfg.to_dict() if self.cfg else None, "session": self.session}
        return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def mismatch(self, payload: Dict[str, Any]) -> str:
        """Why the request does not belong to this context ("" when it does): the panel names the stamp of what it read the design under."""
        if str(payload.get("stamp") or "") == self.stamp:
            return ""
        return "The Fusion hub, its settings or the signed-in user changed since this was read. Refresh the panel and try again."


class HubContexts:
    """Takes the ``HubContext`` of the settings and sign-in active now. ``session`` gives the sign-in of a connection (``AuthService.session``)."""

    def __init__(self, config: ConfigService, session: Callable[[ConnectionSettings], int]) -> None:
        self._config, self._session = config, session

    def capture(self) -> HubContext:
        """The context as it is now. Raises what ``ConfigService.effective_settings`` raises: Shared Configuration that cannot be read."""
        hub_id = str(self._config.hub_id or "")
        settings = self._config.effective_settings()
        cfg = self._config.config.workspaces.get(ITEMS_KIND)
        return HubContext(hub_id, replace(settings, scopes=list(settings.scopes)), deepcopy(cfg) if cfg else None, self._session(settings))

    def attempt(self) -> Tuple[Optional[HubContext], str]:
        """``(context, "")``, or ``(None, why)`` when the settings cannot be read: for a caller that tells the user, or does without."""
        try:
            return self.capture(), ""
        except Exception as exc:  # noqa: BLE001 - the reason is the caller's to show
            reason = str(exc) or type(exc).__name__
            log.info("The settings could not be read: %s", reason)
            return None, reason
