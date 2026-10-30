"""What a publish is made under, taken once when it is asked for: the hub, the tenant, the connection and the Items workspace.

The settings can change while a publish is being checked and queued (another hub opened in Fusion, a setting saved), so every step of it
reads this snapshot and never the live settings. What the panel read is stamped with ``PublishContext.stamp``: a publish made from it,
and a load that would reuse it, find the stamp unchanged or start again.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

from ..config.config_service import ConfigService
from ..config.models import ConnectionSettings
from ..config.workspace_models import ITEMS_KIND, WorkspaceConfig


@dataclass(frozen=True)
class PublishContext:
    """The hub, connection and Items workspace one publish uses: copies, so a later change to the settings does not reach it."""

    hub_id: str
    settings: ConnectionSettings
    cfg: Optional[WorkspaceConfig]   # None for a hub whose Items workspace is not set up yet

    @property
    def tenant(self) -> str:
        return self.settings.tenant

    @property
    def stamp(self) -> str:
        """Identifies what a read of the design, and the comparison with Fusion Manage that goes with it, depends on: the hub, the tenant and
        the whole Items workspace configuration (its id, mappings, default values and Component field). Never empty."""
        basis = {"hub": self.hub_id, "tenant": self.tenant, "workspace": self.cfg.to_dict() if self.cfg else None}
        return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def mismatch(self, payload: Dict[str, Any]) -> str:
        """Why the request does not belong to this context ("" when it does): the panel names the stamp of what it read the design under."""
        if str(payload.get("stamp") or "") == self.stamp:
            return ""
        return "The Fusion hub or its settings changed since this was read. Refresh the panel and publish again."


def capture_context(config: ConfigService) -> PublishContext:
    """The active hub with its connection and Items workspace, as they are now (``cfg`` is None when the workspace is not set up). Raises
    what ``effective_settings`` raises: Shared Configuration that cannot be read."""
    hub_id = str(config.hub_id or "")
    settings = config.effective_settings()
    cfg = config.config.workspaces.get(ITEMS_KIND)
    return PublishContext(hub_id, replace(settings, scopes=list(settings.scopes)), deepcopy(cfg) if cfg else None)
