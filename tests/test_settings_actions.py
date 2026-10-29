"""Reading and saving the settings from the panel. Run: python -m unittest discover tests"""

import unittest
from types import SimpleNamespace
from unittest import mock

from src.config.config_service import SharedStatus
from src.config.export_models import ExportSettings
from src.config.models import AppConfig, ConnectionSettings
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import settings_actions
    from src.ui.actions.settings_actions import HUB_CHANGED, register_settings_actions, save_settings, settings_payload
    from src.ui.message_bridge import MessageBridge


def config_service(stored=None, hub_id="hub-1"):
    service = mock.Mock()
    service.config = stored or AppConfig()
    service.hub_id, service.hub_name = hub_id, "Hub One"
    service.shared_status = SharedStatus()
    service.update.return_value = []
    return service


class SettingsPayloadTests(unittest.TestCase):
    def test_it_has_what_the_panel_fills_its_forms_with(self):
        stored = AppConfig(local=ConnectionSettings(client_id="cid", tenant="acme"))
        payload = settings_payload(config_service(stored))
        self.assertEqual((payload["mode"], payload["local"]["client_id"], payload["local"]["tenant"]), ("local", "cid", "acme"))
        self.assertEqual(payload["hub"], {"id": "hub-1", "name": "Hub One"})
        self.assertEqual(payload["shared"], {"state": "off", "message": ""})
        self.assertEqual(payload["callback_url"], stored.local.callback_url)
        for key in ("workspaces", "exports", "catalog", "company_source", "hub_file"):
            self.assertIn(key, payload)


class SaveSettingsTests(unittest.TestCase):
    def setUp(self):
        self.stored = AppConfig(local=ConnectionSettings(client_id="cid", tenant="acme"))
        self.service = config_service(self.stored)
        self.full = {"hub_id": "hub-1", "mode": "local", "local": {"client_id": "new", "tenant": "beta"},
                     "workspaces": {"items": {"workspace_id": "242"}}, "exports": {"destinations": {}}}

    def saved(self):
        return self.service.update.call_args[0]

    def test_a_full_request_saves_each_part_and_answers_the_settings(self):
        answer = save_settings(self.service, self.full)
        mode, local, workspaces, source, exports = self.saved()
        self.assertEqual((mode, local.client_id, local.tenant), ("local", "new", "beta"))
        self.assertEqual(workspaces.get("items").workspace_id, "242")
        self.assertIsInstance(exports, ExportSettings)
        self.assertEqual(answer["local"]["client_id"], "cid")   # the answer is the settings as the service now holds them

    def test_a_part_the_request_leaves_out_stays_as_it_is(self):
        save_settings(self.service, {"hub_id": "hub-1"})
        mode, local, workspaces, source, exports = self.saved()
        self.assertEqual(mode, "local")
        self.assertIs(local, self.stored.local)
        self.assertIs(workspaces, self.stored.workspaces)
        self.assertEqual(source, self.stored.company_source)
        self.assertIsNone(exports)

    def test_a_mode_left_out_is_the_current_one(self):
        self.stored.mode = "company"
        save_settings(self.service, {"hub_id": "hub-1"})
        self.assertEqual(self.saved()[0], "company")

    def test_the_company_source_is_trimmed(self):
        save_settings(self.service, dict(self.full, company_source="  \\\\share\\file.json  "))
        self.assertEqual(self.saved()[3], "\\\\share\\file.json")

    def test_problems_are_answered_for_the_panel_and_the_settings_are_not(self):
        self.service.update.return_value = ["Enter a Client ID."]
        with mock.patch.object(settings_actions, "problem_payload", return_value=[{"field": "client_id"}]) as shaped:
            answer = save_settings(self.service, self.full)
        self.assertEqual(answer, {"problems": [{"field": "client_id"}]})
        shaped.assert_called_once_with(["Enter a Client ID."])

    def test_a_page_that_shows_another_hub_is_refused_and_nothing_is_saved(self):
        with self.assertRaisesRegex(ValueError, "active hub has changed"):
            save_settings(self.service, dict(self.full, hub_id="hub-2"))
        self.service.update.assert_not_called()

    def test_a_request_that_does_not_say_which_hub_is_refused(self):
        del self.full["hub_id"]
        with self.assertRaisesRegex(ValueError, HUB_CHANGED[:30]):
            save_settings(self.service, self.full)
        self.service.update.assert_not_called()

    def test_with_no_hub_open_a_request_without_one_goes_on_to_the_service_to_say_so(self):
        service = config_service(hub_id="")
        service.update.return_value = ["No hub is active."]
        save_settings(service, {"mode": "local"})
        service.update.assert_called_once()

    def test_a_mode_that_is_not_one_is_refused_and_nothing_is_saved(self):
        with self.assertRaisesRegex(ValueError, "'shared' is not a mode"):
            save_settings(self.service, dict(self.full, mode="shared"))
        self.service.update.assert_not_called()

    def test_a_part_that_is_not_an_object_is_refused_and_nothing_is_saved(self):
        for key in ("local", "workspaces", "exports"):
            for bad in (None, "x", ["a"], 5):
                with self.assertRaisesRegex(ValueError, f"'{key}' must be an object"):
                    save_settings(self.service, dict(self.full, **{key: bad}))
        self.service.update.assert_not_called()


class RegisterTests(unittest.TestCase):
    def test_the_actions_read_and_save(self):
        service = config_service()
        bridge = MessageBridge()
        register_settings_actions(bridge, service)
        self.assertEqual(bridge.dispatch("get_settings", "")["result"]["hub"]["id"], "hub-1")
        self.assertTrue(bridge.dispatch("save_settings", '{"hub_id": "hub-1"}')["ok"])
        refused = bridge.dispatch("save_settings", '{"hub_id": "other"}')
        self.assertEqual((refused["ok"], refused["error"]), (False, HUB_CHANGED))


if __name__ == "__main__":
    unittest.main()
