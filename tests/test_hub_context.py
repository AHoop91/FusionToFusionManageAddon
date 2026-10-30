"""The snapshot a publish is made under: hub, connection and Items workspace, taken together and kept apart from later changes."""

import unittest

from src.config.models import ConnectionSettings
from src.config.workspace_models import ITEMS_KIND, FieldMapping, StaticValue
from src.config.hub_context import capture_context
from tests.hub_fixtures import config_of


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

    def test_a_request_made_under_its_stamp_belongs_to_it_and_any_other_does_not(self):
        context = capture_context(config_of())
        self.assertEqual(context.mismatch({"stamp": context.stamp}), "")
        self.assertIn("settings changed", context.mismatch({"stamp": "other"}))
        self.assertIn("settings changed", context.mismatch({}))

    def test_the_stamp_is_the_same_for_the_same_hub_tenant_and_workspace(self):
        self.assertEqual(capture_context(config_of()).stamp, capture_context(config_of()).stamp)
        self.assertTrue(capture_context(config_of()).stamp)

    def test_the_stamp_differs_when_the_hub_the_tenant_or_the_workspace_differs(self):
        stamps = {capture_context(config_of()).stamp, capture_context(config_of(hub="hub2")).stamp,
                  capture_context(config_of(tenant="other")).stamp, capture_context(config_of(workspace="999")).stamp}
        self.assertEqual(len(stamps), 4)

    def test_the_stamp_differs_when_a_mapping_or_default_value_of_the_workspace_differs(self):
        base = config_of()
        mapped = config_of()
        mapped.config.workspaces[ITEMS_KIND].mappings = [FieldMapping(source="description", fm_field_id="DESCRIPTION")]
        defaulted = config_of()
        defaulted.config.workspaces[ITEMS_KIND].static_values = [StaticValue(fm_field_id="X", value="1")]
        self.assertEqual(len({capture_context(c).stamp for c in (base, mapped, defaulted)}), 3)

    def test_the_stamp_ignores_what_does_not_change_the_target_of_a_read(self):
        other = config_of()
        other.effective_settings.return_value = ConnectionSettings(client_id="another", tenant="acme", callback_port=9000)
        self.assertEqual(capture_context(config_of()).stamp, capture_context(other).stamp)

    def test_a_hub_without_the_items_workspace_has_a_stamp_of_its_own(self):
        none = config_of()
        none.config.workspaces = {}
        self.assertNotEqual(capture_context(none).stamp, capture_context(config_of()).stamp)

    def test_a_hub_without_the_items_workspace_has_a_context_without_one(self):
        config = config_of()
        config.config.workspaces = {}
        self.assertIsNone(capture_context(config).cfg)


if __name__ == "__main__":
    unittest.main()
