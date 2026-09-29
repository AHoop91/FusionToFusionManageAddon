"""Configuration data models.

Connection settings are non-secret. Tokens and any secret material are never
stored here; see ``auth.token_store``.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .workspace_models import WorkspaceSettings

MODE_LOCAL = "local"
MODE_COMPANY = "company"

# data:search is needed by the Manufacturing Data Model (custom properties).
DEFAULT_SCOPES = ["data:read", "data:write", "data:search"]
DEFAULT_CALLBACK_PORT = 8765


@dataclass
class ConnectionSettings:
    """Everything needed to sign in to and address Fusion Manage."""

    client_id: str = ""
    tenant: str = ""
    callback_port: int = DEFAULT_CALLBACK_PORT
    scopes: List[str] = field(default_factory=lambda: list(DEFAULT_SCOPES))

    @property
    def callback_url(self) -> str:
        """Redirect URI; must be registered on the APS application."""
        return f"http://localhost:{self.callback_port}/callback"

    def validate(self) -> List[str]:
        """Return human-readable problems; empty list means valid."""
        problems = []
        if not self.client_id.strip():
            problems.append("Client ID is required.")
        if not self.tenant.strip():
            problems.append("Tenant is required.")
        if not (1024 <= int(self.callback_port) <= 65535):
            problems.append("Callback port must be between 1024 and 65535.")
        if not self.scopes:
            problems.append("At least one scope is required.")
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "local": self.local.to_dict(),
            "workspaces": self.workspaces.to_dict(),
            "company": {"source": self.company_source},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        mode = data.get("mode", MODE_LOCAL)
        local = data.get("local", {})
        # Older files kept the workspace id under ``local.workspace_id``.
        workspaces = data.get("workspaces") or {"items_workspace_id": local.get("workspace_id", "")}
        return cls(
            mode=mode if mode in (MODE_LOCAL, MODE_COMPANY) else MODE_LOCAL,
            local=ConnectionSettings.from_dict(local),
            workspaces=WorkspaceSettings.from_dict(workspaces),
            company_source=str(data.get("company", {}).get("source", "")),
        )
