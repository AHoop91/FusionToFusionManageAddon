"""Configuration data models.

Connection settings are non-secret. Tokens and any secret material are never
stored here; see ``auth.token_store``.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .export_models import ExportSettings
from .hub import tenant_code
from .problems import Problem
from .workspace_models import WorkspaceSettings

MODE_LOCAL = "local"
MODE_COMPANY = "company"

# data:search is needed by the Manufacturing Data Model (custom properties); user-profile:read, by the avatar (the Identity API).
DEFAULT_SCOPES = ["data:read", "data:write", "data:search", "user-profile:read"]
DEFAULT_CALLBACK_PORT = 8765


@dataclass
class ConnectionSettings:
    """Everything needed to sign in to and address Fusion Manage."""

    client_id: str = ""
    tenant: str = ""   # found from a linked item by the Preferences panel, or typed
    callback_port: int = DEFAULT_CALLBACK_PORT
    scopes: List[str] = field(default_factory=lambda: list(DEFAULT_SCOPES))

    @property
    def callback_url(self) -> str:
        """Redirect URI; must be registered on the APS application."""
        return f"http://localhost:{self.callback_port}/callback"

    def validate(self, require_tenant: bool = True) -> List[str]:
        """Return human-readable problems; empty list means valid.

        ``require_tenant`` is False for the saved settings, which may be saved before the tenant is known (sign-in does not need it).
        """
        problems: List[str] = []
        if not self.client_id.strip():
            problems.append(Problem("Client ID: enter the Client ID of your Autodesk app.", input="f-client-id"))
        if self.tenant.strip() and not tenant_code(self.tenant):
            problems.append(Problem("Tenant: enter a single name such as mycompany, not an address.", input="f-tenant"))
        elif require_tenant and not self.tenant.strip():
            problems.append(Problem("Tenant: use Find in Preferences ▸ Connection, or enter it.", input="f-tenant"))
        if not (1024 <= int(self.callback_port) <= 65535):
            problems.append(Problem("Callback port: enter a number between 1024 and 65535.", input="f-port"))
        if not self.scopes:
            problems.append(Problem("Scopes: enter at least one scope.", input="f-scopes"))
        return problems

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectionSettings":
        """Build from stored JSON, ignoring unknown keys and bad types."""
        defaults = cls()
        try:
            port = int(data.get("callback_port", defaults.callback_port))
        except (TypeError, ValueError):
            port = defaults.callback_port
        scopes = data.get("scopes")
        return cls(
            client_id=str(data.get("client_id", "")).strip(),
            tenant=str(data.get("tenant", "")).strip(),
            callback_port=port,
            scopes=[str(s) for s in scopes] if isinstance(scopes, list) and scopes
            else list(DEFAULT_SCOPES),
        )


@dataclass
class AppConfig:
    """Top-level persisted configuration."""

    mode: str = MODE_LOCAL
    local: ConnectionSettings = field(default_factory=ConnectionSettings)
    workspaces: WorkspaceSettings = field(default_factory=WorkspaceSettings)
    # Placeholder for company mode. ``source`` will later hold a UNC path or
    # HTTPS URL to the shared JSON. Not used yet.
    company_source: str = ""
    exports: ExportSettings = field(default_factory=ExportSettings)
    # The Configuration File in the Fusion Hub that this hub's settings were taken from (a member of the hub, not a Hub Admin, has no
    # other source): ``project_id``, ``item_id``, ``name`` and ``read_at``. None when the settings are the user's own.
    hub_file: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "mode": self.mode,
            "local": self.local.to_dict(),
            "workspaces": self.workspaces.to_dict(),
            "exports": self.exports.to_dict(),
            "company": {"source": self.company_source},
        }
        if self.hub_file:
            data["hub_file"] = dict(self.hub_file)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        mode = data.get("mode", MODE_LOCAL)
        local = data.get("local", {})
        # Older files kept the workspace id under ``local.workspace_id``.
        workspaces = data.get("workspaces") or {"items_workspace_id": local.get("workspace_id", "")}
        kept = data.get("hub_file")
        hub_file = {key: str(kept.get(key, "")) for key in ("project_id", "item_id", "name", "read_at")} \
            if isinstance(kept, dict) and kept.get("item_id") else None
        return cls(
            mode=mode if mode in (MODE_LOCAL, MODE_COMPANY) else MODE_LOCAL,
            local=ConnectionSettings.from_dict(local),
            workspaces=WorkspaceSettings.from_dict(workspaces),
            company_source=str(data.get("company", {}).get("source", "")),
            exports=ExportSettings.from_dict(data.get("exports")),
            hub_file=hub_file,
        )
