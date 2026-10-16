"""Bridge actions exposed to the palette.

Each module registers one feature area on the ``MessageBridge``:

* ``settings_actions``: read and save connection settings.
* ``auth_actions``: sign-in state, login, logout and the user profile.
* ``workspace_actions``: Fusion Manage workspace validation.
* ``tenant_actions``: find the Fusion Manage tenant from the open design's linked item.
* ``property_actions``: the hub's custom properties for field mapping.
* ``publish_actions``: the open model for the Publish Item panel.
* ``search_actions``: the Add Items picker: search matches, filterable fields and picklist options.
* ``transfer_actions``: export and import the configuration file.

``register_actions`` is the only function the add-in entry point needs.
"""

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ..file_dialogs import FileDialogs
from ..message_bridge import MessageBridge
from ..job_alerts import JobAlerts
from ..jobs_badge import JobsBadge
from .auth_actions import register_auth_actions
from .search_actions import register_search_actions
from .property_actions import register_property_actions
from .publish_actions import register_publish_actions
from .publish_run_actions import register_publish_run_actions
from .settings_actions import register_settings_actions
from .tenant_actions import register_tenant_actions
from .transfer_actions import register_transfer_actions
from .workspace_actions import register_workspace_actions


def register_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService,
                     dialogs: FileDialogs, badge: JobsBadge, alerts: JobAlerts) -> None:
    """Register every palette action on ``bridge``."""
    register_settings_actions(bridge, config)
    register_auth_actions(bridge, config, auth)
    register_workspace_actions(bridge, config, auth)
    register_tenant_actions(bridge, config, auth)
    register_property_actions(bridge, config, auth)
    register_publish_actions(bridge, config, auth)
    register_publish_run_actions(bridge, config, auth, dialogs, badge, alerts)
    register_search_actions(bridge, config, auth)
    register_transfer_actions(bridge, config, dialogs)
