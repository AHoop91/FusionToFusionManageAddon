"""The snapshot a publish is made under: hub, connection and Items workspace, taken together and kept apart from later changes."""

import unittest

from src.config.models import ConnectionSettings
from src.config.workspace_models import ITEMS_KIND, FieldMapping, StaticValue
from src.config.hub_context import HubContexts
from tests.hub_fixtures import capture, config_of


class ContextTests(unittest.TestCase):
    def test_it_holds_the_hub_tenant_and_workspace_together(self):
        context = capture(config_of())
        self.assertEqual((context.hub_id, context.tenant, context.cfg.workspace_id), ("hub1", "acme", "242"))

    def test_a_later_change_to_the_settings_does_not_reach_it(self):
        config = config_of()
        context = capture(config)
        config.effective_settings.return_value.tenant = "other"
        config.config.workspaces[ITEMS_KIND].workspace_id = "999"
        self.assertEqual((context.tenant, context.cfg.workspace_id), ("acme", "242"))

    def test_a_request_made_under_its_stamp_belongs_to_it_and_any_other_does_not(self):
        context = capture(config_of())
        self.assertEqual(context.mismatch({"stamp": context.stamp}), "")
        self.assertIn("changed since this was read", context.mismatch({"stamp": "other"}))
        self.assertIn("changed since this was read", context.mismatch({}))

    def test_the_stamp_is_the_same_for_the_same_hub_tenant_and_workspace(self):
        self.assertEqual(capture(config_of()).stamp, capture(config_of()).stamp)
        self.assertTrue(capture(config_of()).stamp)

    def test_the_stamp_differs_when_the_hub_the_tenant_or_the_workspace_differs(self):
        stamps = {capture(config_of()).stamp, capture(config_of(hub="hub2")).stamp,
                  capture(config_of(tenant="other")).stamp, capture(config_of(workspace="999")).stamp}
        self.assertEqual(len(stamps), 4)

    def test_the_stamp_differs_when_a_mapping_or_default_value_of_the_workspace_differs(self):
        base = config_of()
        mapped = config_of()
        mapped.config.workspaces[ITEMS_KIND].mappings = [FieldMapping(source="description", fm_field_id="DESCRIPTION")]
        defaulted = config_of()
        defaulted.config.workspaces[ITEMS_KIND].static_values = [StaticValue(fm_field_id="X", value="1")]
        self.assertEqual(len({capture(c).stamp for c in (base, mapped, defaulted)}), 3)

    def test_the_stamp_ignores_what_does_not_change_the_target_of_a_read(self):
        other = config_of()
        other.effective_settings.return_value = ConnectionSettings(client_id="another", tenant="acme", callback_port=9000)
        self.assertEqual(capture(config_of()).stamp, capture(other).stamp)

    def test_the_stamp_differs_when_the_sign_in_differs(self):
        self.assertEqual(capture(config_of(), session=1).stamp, capture(config_of(), session=1).stamp)
        self.assertNotEqual(capture(config_of(), session=1).stamp, capture(config_of(), session=2).stamp)

    def test_the_session_is_asked_for_the_connection_of_the_context(self):
        asked = []
        HubContexts(config_of(tenant="acme"), lambda settings: asked.append(settings.tenant) or 7).capture()
        self.assertEqual(asked, ["acme"])
        self.assertEqual(HubContexts(config_of(), lambda _settings: 7).capture().session, 7)

    def test_a_context_is_attempted_without_raising(self):
        context, reason = HubContexts(config_of(), lambda _settings: 1).attempt()
        self.assertEqual((context.tenant, reason), ("acme", ""))

    def test_settings_that_cannot_be_read_are_a_reason_not_an_error(self):
        config = config_of()
        config.effective_settings.side_effect = RuntimeError("shared file unreadable")
        self.assertEqual(HubContexts(config, lambda _settings: 1).attempt(), (None, "shared file unreadable"))
        config.effective_settings.side_effect = RuntimeError()
        self.assertEqual(HubContexts(config, lambda _settings: 1).attempt(), (None, "RuntimeError"))   # a failure with no message is named
        with self.assertRaises(RuntimeError):
            HubContexts(config, lambda _settings: 1).capture()

    def test_a_hub_without_the_items_workspace_has_a_stamp_of_its_own(self):
        none = config_of()
        none.config.workspaces = {}
        self.assertNotEqual(capture(none).stamp, capture(config_of()).stamp)

    def test_a_hub_without_the_items_workspace_has_a_context_without_one(self):
        config = config_of()
        config.config.workspaces = {}
        self.assertIsNone(capture(config).cfg)


if __name__ == "__main__":
    unittest.main()
