"""A configuration for tests of what is made under a hub context: the active hub, a tenant, and an Items workspace that is set up."""

from unittest import mock

from src.config.hub_context import HubContexts, HubContext
from src.config.models import ConnectionSettings
from src.config.workspace_models import ITEM_NUMBER_SOURCE, ITEMS_KIND, LEGACY_NUMBER_FIELD, FieldMapping, WorkspaceConfig


def items_workspace(workspace_id="242"):
    """An Items workspace that is set up (when ``workspace_id`` is not empty)."""
    return WorkspaceConfig(workspace_id=workspace_id, mappings=[FieldMapping(ITEM_NUMBER_SOURCE, LEGACY_NUMBER_FIELD)])


def config_of(hub="hub1", tenant="acme", workspace="242"):
    """A configuration whose active hub, tenant and Items workspace are those given; a test changes them to change the active hub."""
    config = mock.Mock(hub_id=hub)
    config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant=tenant)
    config.config.workspaces = {ITEMS_KIND: items_workspace(workspace)}
    return config


def auth_of(session=1):
    """A sign-in as ``AuthService`` tells it: ``session`` is the session of every connection."""
    return mock.Mock(session=mock.Mock(return_value=session))


def capture(config, session=1) -> HubContext:
    """The context of ``config`` under the sign-in ``session``."""
    return HubContexts(config, lambda _settings: session).capture()
