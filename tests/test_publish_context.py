"""The snapshot a publish is made under: hub, connection and Items workspace, taken together and kept apart from later changes."""

import unittest
from unittest import mock

from src.config.models import ConnectionSettings
from src.config.workspace_models import ITEMS_KIND, WorkspaceConfig
from src.publish.context import capture_context


def config_of(hub="hub1", tenant="acme", workspace="242"):
    config = mock.Mock(hub_id=hub)
    config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant=tenant)
    config.config.workspaces = {ITEMS_KIND: WorkspaceConfig(workspace_id=workspace)}
    return config


class ContextTests(unittest.TestCase):
    def test_it_holds_the_hub_tenant_and_workspace_together(self):
        context = capture_context(config_of())
        self.assertEqual((context.hub_id, context.tenant, context.cfg.workspace_id), ("hub1", "acme", "242"))

    def test_a_later_change_to_the_settings_does_not_reach_it(self):
        config = config_of()
        context = capture_context(config)
        config.effective_settings.return_value.tenant = "other"
        config.config.workspaces[ITEMS_KIND].workspace_id = "999"
        self.assertEqual((context.tenant, context.cfg.workspace_id), ("acme", "242"))

    def test_a_request_from_another_hub_does_not_belong_to_it(self):
        context = capture_context(config_of())
        self.assertEqual(context.mismatch({"hub_id": "hub1"}), "")
        self.assertIn("hub changed", context.mismatch({"hub_id": "hub2"}))
        self.assertIn("hub changed", context.mismatch({}))

    def test_a_hub_without_the_items_workspace_has_a_context_without_one(self):
        config = config_of()
        config.config.workspaces = {}
        self.assertIsNone(capture_context(config).cfg)


if __name__ == "__main__":
    unittest.main()
