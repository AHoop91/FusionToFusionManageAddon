"""What a publish is made under, taken once when it is asked for: the hub, the tenant, the connection and the Items workspace.

The settings can change while a publish is being checked and queued (another hub opened in Fusion, a setting saved), so every step of it
reads this snapshot and never the live settings, and a request the panel made under another hub is refused.
"""

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

    def mismatch(self, payload: Dict[str, Any]) -> str:
        """Why the request does not belong to this context ("" when it does): the panel names the hub it read the design under."""
        asked = str(payload.get("hub_id") or "")
        if asked == self.hub_id:
            return ""
        return "The Fusion hub changed since this was read. Refresh the panel and publish again."


def capture_context(config: ConfigService) -> PublishContext:
    """The active hub with its connection and Items workspace, as they are now (``cfg`` is None when the workspace is not set up). Raises
    what ``effective_settings`` raises: Shared Configuration that cannot be read."""
    hub_id = str(config.hub_id or "")
    settings = config.effective_settings()
    cfg = config.config.workspaces.get(ITEMS_KIND)
    return PublishContext(hub_id, replace(settings, scopes=list(settings.scopes)), deepcopy(cfg) if cfg else None)
