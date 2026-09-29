"""Bridge actions exposed to the palette.

Each module registers one feature area on the ``MessageBridge``:

* ``settings_actions``: read and save connection settings.
* ``auth_actions``: sign-in state, login, logout and the user profile.
* ``workspace_actions``: Fusion Manage workspace validation.
* ``property_actions``: the hub's custom properties for field mapping.
* ``publish_actions``: the open model for the Publish Item panel.
* ``transfer_actions``: export and import the configuration file.

``register_actions`` is the only function the add-in entry point needs.
"""

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ..file_dialogs import FileDialogs
from ..message_bridge import MessageBridge
from .auth_actions import register_auth_actions
from .property_actions import register_property_actions
from .publish_actions import register_publish_actions
from .settings_actions import register_settings_actions
from .transfer_actions import register_transfer_actions
from .workspace_actions import register_workspace_actions


def register_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService,
                     dialogs: FileDialogs) -> None:
    """Register every palette action on ``bridge``."""
    # Diagnostic round trip used to verify the palette bridge is alive.
    bridge.register("ping", lambda _payload: {"message": "pong"})
    register_settings_actions(bridge, config)
    register_auth_actions(bridge, config, auth)
    register_workspace_actions(bridge, config, auth)
    register_property_actions(bridge, config, auth)
    register_publish_actions(bridge, config, auth)
    register_transfer_actions(bridge, config, dialogs)
