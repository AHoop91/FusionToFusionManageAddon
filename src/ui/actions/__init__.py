"""Bridge actions exposed to the palette.

Each module registers one feature area on the ``MessageBridge``:

* ``settings_actions``: read and save connection settings.
* ``auth_actions``: sign-in state, login, logout and the user profile.
* ``workspace_actions``: Fusion Manage workspace validation.
* ``tenant_actions``: find the Fusion Manage tenant from the open design's linked item.
* ``property_actions``: the hub's custom properties for field mapping.
* ``help_actions``: the Help button, which opens the documentation.
* ``publish_actions``: the open model for the Publish Item panel.
* ``search_actions``: the Add Items picker: search matches, filterable fields and picklist options.
* ``product_actions``: the Assign Product panel: the products of the Portfolio Management workspace, and creating one.
* ``item_create_actions``: the Publish panel's side panel: a new manufacturing item, and a bought version of an item.
* ``hub_actions``, ``hub_file_actions``, ``hub_save_actions``: the user's role in the hub, and finding or saving its Configuration File.

``register_actions`` is the only function the add-in entry point needs.
"""

from typing import Callable, Optional

from ...auth.auth_service import AuthService
from ...config.config_service import ConfigService
from ...config.hub_languages import HubLanguages
from ..file_dialogs import FileDialogs
from ..message_bridge import MessageBridge
from ..job_alerts import JobAlerts
from ..jobs_badge import JobsBadge
from .auth_actions import register_auth_actions
from .hub_actions import MEMBER, HubRoles, register_hub_actions
from .help_actions import register_help_actions
from .hub_file_actions import register_hub_file_actions
from .hub_save_actions import register_hub_save_actions
from .item_create_actions import register_item_create_actions
from .product_actions import register_product_actions
from .search_actions import register_search_actions
from .property_actions import register_property_actions
from .publish_actions import register_publish_actions
from .publish_run_actions import register_publish_run_actions
from .settings_actions import register_settings_actions
from .tenant_actions import register_tenant_actions
from .workspace_actions import register_workspace_actions


def register_actions(bridge: MessageBridge, config: ConfigService, auth: AuthService,
                     dialogs: FileDialogs, badge: JobsBadge, alerts: JobAlerts, post: Callable[[Callable[[], None]], None],
                     languages: Optional[HubLanguages] = None) -> HubRoles:
    """Register every palette action on ``bridge``; ``post`` queues work on Fusion's main thread; ``languages`` is what keeps the languages
    a hub shares. Answers the hub roles."""
    roles = register_hub_actions(bridge, config)
    register_settings_actions(bridge, config, lambda: roles.get()["state"] == MEMBER)   # a member may not change Make or buy
    register_help_actions(bridge)
    register_auth_actions(bridge, config, auth)
    register_workspace_actions(bridge, config, auth)
    register_tenant_actions(bridge)
    register_hub_file_actions(bridge, config, post, languages)
    register_hub_save_actions(bridge, config, languages)
    register_property_actions(bridge)
    register_publish_actions(bridge, config, auth)
    register_publish_run_actions(bridge, config, auth, dialogs, badge, alerts)
    register_search_actions(bridge, config, auth)
    register_product_actions(bridge, config, auth)
    register_item_create_actions(bridge, config, auth)
    return roles
