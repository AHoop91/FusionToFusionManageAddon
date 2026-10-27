"""The hub's Configuration File: checked, and used as the hub's settings for a member who is not a Hub Admin."""

import json
import os
import tempfile
import unittest

from src.config.config_envelope import FORMAT_ID, FORMAT_VERSION, MAX_CONFIG_BYTES, ConfigTransferError, parse_envelope
from src.config.config_service import ConfigService
from src.config.config_transfer import config_file_bytes, config_from_hub_file
from src.config.models import MODE_LOCAL, AppConfig, ConnectionSettings

HUB_A, HUB_B = "a.hub-a", "a.hub-b"


def file_bytes(hub=None, tenant="acme", client_id="admins-client") -> bytes:
    config = AppConfig(local=ConnectionSettings(client_id=client_id, tenant=tenant, callback_port=9000, scopes=["data:read"]))
    envelope = {"format": FORMAT_ID, "version": FORMAT_VERSION, "config": config.to_dict()}
    if hub:
        envelope["hub"] = hub
    return json.dumps(envelope).encode("utf-8")


class ParseTests(unittest.TestCase):
    def test_bytes_with_a_byte_order_mark_are_read(self):
        self.assertEqual(parse_envelope(b"\xef\xbb\xbf" + file_bytes())["format"], FORMAT_ID)

    def test_a_file_that_is_too_large_is_refused(self):
        with self.assertRaises(ConfigTransferError):
            parse_envelope(b" " * (MAX_CONFIG_BYTES + 1))

    def test_bytes_that_are_not_json_are_refused(self):
        with self.assertRaises(ConfigTransferError):
            parse_envelope(b"\xff\xfe not json")

    def test_a_file_that_is_not_ours_is_refused(self):
        with self.assertRaises(ConfigTransferError):
            parse_envelope(b'{"hello": "world"}')


class HubOfTheFileTests(unittest.TestCase):
    def test_a_file_from_this_hub_is_accepted(self):
        config = config_from_hub_file(file_bytes({"id": HUB_A, "name": "Hub A"}), HUB_A, "Hub A")
        self.assertEqual(config.local.tenant, "acme")

    def test_a_file_without_a_hub_is_accepted(self):
        self.assertEqual(config_from_hub_file(file_bytes(), HUB_A, "Hub A").local.tenant, "acme")

    def test_a_file_from_another_hub_is_refused(self):
        with self.assertRaises(ConfigTransferError) as caught:
            config_from_hub_file(file_bytes({"id": HUB_B, "name": "Hub B"}), HUB_A, "Hub A")
        self.assertIn("Hub B", str(caught.exception))


class SavedFileTests(unittest.TestCase):
    def test_a_file_an_admin_saves_is_read_back_by_a_member_of_the_same_hub_only(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        admin = ConfigService(os.path.join(folder.name, "config.json"), hub_aware=True)
        admin.use_hub(HUB_A, "Hub A")
        admin.update(MODE_LOCAL, ConnectionSettings(client_id="admins-client", tenant="acme"), admin.config.workspaces, "")
        saved = config_file_bytes(admin)
        self.assertEqual(config_from_hub_file(saved, HUB_A, "Hub A").local.tenant, "acme")
        with self.assertRaises(ConfigTransferError):
            config_from_hub_file(saved, HUB_B, "Hub B")


class ApplyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "config.json")
        self.service = ConfigService(self.path, hub_aware=True)
        self.service.use_hub(HUB_A, "Hub A")
        self.ref = {"project_id": "p", "item_id": "i", "name": "config.json", "read_at": "2026-10-19T10:00:00"}

    def test_the_tenant_comes_from_the_file_and_the_sign_in_stays_the_users(self):
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client", tenant="old"), self.service.config.workspaces, "")
        imported = config_from_hub_file(file_bytes(tenant="acme", client_id="admins-client"), HUB_A, "Hub A")
        self.assertEqual(self.service.apply_hub_file(imported, self.ref), [])
        local = self.service.config.local
        self.assertEqual((local.client_id, local.tenant, local.callback_port), ("my-client", "acme", 8765))   # the admin's port is not taken
        self.assertEqual(self.service.config.hub_file["name"], "config.json")

    def test_the_file_it_came_from_outlasts_a_restart(self):
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client"), self.service.config.workspaces, "")
        self.service.apply_hub_file(config_from_hub_file(file_bytes(), HUB_A, "Hub A"), self.ref)
        again = ConfigService(self.path, hub_aware=True)
        again.use_hub(HUB_A, "Hub A")
        self.assertEqual(again.config.hub_file, self.ref)

    def test_what_the_hub_said_of_the_file_outlasts_a_restart(self):
        ref = dict(self.ref, project_name="Resources", modified="2026-10-27T14:20:25", modified_by="Fabio", version="2")
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client"), self.service.config.workspaces, "")
        self.service.apply_hub_file(config_from_hub_file(file_bytes(), HUB_A, "Hub A"), ref)
        again = ConfigService(self.path, hub_aware=True)
        again.use_hub(HUB_A, "Hub A")
        self.assertEqual(again.config.hub_file, ref)

    def test_only_the_hub_that_read_the_file_has_it(self):
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client"), self.service.config.workspaces, "")
        self.service.apply_hub_file(config_from_hub_file(file_bytes(), HUB_A, "Hub A"), self.ref)
        self.service.use_hub(HUB_B, "Hub B")
        self.assertIsNone(self.service.config.hub_file)
        self.assertEqual(self.service.config.local.tenant, "")

    def test_a_member_without_a_client_id_signs_in_with_the_files(self):
        problems = self.service.apply_hub_file(config_from_hub_file(file_bytes(), HUB_A, "Hub A"), self.ref)
        self.assertEqual(problems, [])
        local = self.service.config.local
        self.assertEqual((local.client_id, local.tenant, local.callback_port), ("admins-client", "acme", 9000))
        self.assertEqual(self.service.config.hub_file["name"], "config.json")

    def test_a_file_without_a_client_id_is_not_applied_to_a_member_who_has_none(self):
        problems = self.service.apply_hub_file(config_from_hub_file(file_bytes(client_id=""), HUB_A, "Hub A"), self.ref)
        self.assertEqual(len(problems), 1)
        self.assertIsNone(self.service.config.hub_file)

    def test_saving_by_hand_forgets_the_file(self):
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client"), self.service.config.workspaces, "")
        self.service.apply_hub_file(config_from_hub_file(file_bytes(), HUB_A, "Hub A"), self.ref)
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client", tenant="mine"), self.service.config.workspaces, "")
        self.assertIsNone(self.service.config.hub_file)


if __name__ == "__main__":
    unittest.main()
