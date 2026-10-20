"""Each hub has its own settings, and being signed in belongs to a Client ID, not to the add-in as a whole."""

import json
import os
import tempfile
import unittest

from src.auth.auth_service import STATE_SIGNED_IN, STATE_SIGNED_OUT, AuthService
from src.config.config_service import ConfigService
from src.config.models import MODE_LOCAL, ConnectionSettings

HUB_A, HUB_B = "a.hub-a", "a.hub-b"


class FakeStore:
    """Tokens by Client ID, in memory."""

    def __init__(self, *client_ids):
        self.saved = {client_id: {"access_token": "x"} for client_id in client_ids}

    def load(self, client_id):
        return self.saved.get(client_id)

    def save(self, client_id, tokens):
        self.saved[client_id] = tokens

    def clear(self, client_id):
        self.saved.pop(client_id, None)


class HubConfigTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "config.json")

    def service(self) -> ConfigService:
        return ConfigService(self.path, hub_aware=True)

    def save(self, service: ConfigService, client_id: str, tenant: str) -> None:
        problems = service.update(MODE_LOCAL, ConnectionSettings(client_id=client_id, tenant=tenant), service.config.workspaces, "")
        self.assertEqual(problems, [])

    def test_each_hub_keeps_its_own_settings(self):
        service = self.service()
        service.use_hub(HUB_A, "Hub A")
        self.save(service, "id-a", "tenant-a")
        service.use_hub(HUB_B, "Hub B")
        self.assertEqual(service.config.local.client_id, "")   # a hub with nothing saved starts empty
        self.save(service, "id-b", "tenant-b")
        service.use_hub(HUB_A, "Hub A")
        self.assertEqual((service.config.local.client_id, service.config.local.tenant), ("id-a", "tenant-a"))
        service.use_hub(HUB_B, "Hub B")
        self.assertEqual((service.config.local.client_id, service.config.local.tenant), ("id-b", "tenant-b"))

    def test_the_settings_outlast_a_restart(self):
        service = self.service()
        service.use_hub(HUB_A, "Hub A")
        self.save(service, "id-a", "tenant-a")
        again = self.service()
        again.use_hub(HUB_A, "Hub A")
        self.assertEqual(again.config.local.client_id, "id-a")
        again.use_hub(HUB_B, "Hub B")
        self.assertEqual(again.config.local.client_id, "")
        with open(self.path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["hubs"][HUB_A]["name"], "Hub A")

    def test_nothing_is_saved_while_no_hub_is_known(self):
        service = self.service()
        problems = service.update(MODE_LOCAL, ConnectionSettings(client_id="x"), service.config.workspaces, "")
        self.assertEqual(len(problems), 1)
        self.assertFalse(os.path.exists(self.path))

    def test_settings_saved_before_hubs_go_to_the_first_hub_seen(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"mode": "local", "local": {"client_id": "old-id", "tenant": "old-tenant"}}, handle)
        service = self.service()
        self.assertEqual(service.config.local.client_id, "")   # no hub yet: nothing is in use
        service.use_hub(HUB_A, "Hub A")
        self.assertEqual(service.config.local.client_id, "old-id")
        service.use_hub(HUB_B, "Hub B")
        self.assertEqual(service.config.local.client_id, "")
        self.assertTrue(os.path.exists(self.path + ".bak"))   # the old file is kept as it was
        with open(self.path + ".bak", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["local"]["client_id"], "old-id")

    def test_changing_hub_tells_the_listeners_once(self):
        service = self.service()
        heard = []
        service.on_change(lambda: heard.append(service.hub_id))
        service.use_hub(HUB_A, "Hub A")
        service.use_hub(HUB_A, "Hub A")
        service.use_hub(HUB_B, "Hub B")
        self.assertEqual(heard, [HUB_A, HUB_B])

    def test_a_service_not_told_of_a_hub_has_one_configuration(self):
        service = ConfigService(self.path)
        self.assertEqual(service.update(MODE_LOCAL, ConnectionSettings(client_id="x"), service.config.workspaces, ""), [])
        self.assertEqual(ConfigService(self.path).config.local.client_id, "x")


class SignInPerClientIdTests(unittest.TestCase):
    def test_being_signed_in_follows_the_client_id(self):
        auth = AuthService(FakeStore("id-a"))
        self.assertEqual(auth.status(ConnectionSettings(client_id="id-a"))["state"], STATE_SIGNED_IN)
        self.assertEqual(auth.status(ConnectionSettings(client_id="id-b"))["state"], STATE_SIGNED_OUT)   # another hub's connection
        self.assertEqual(auth.status(ConnectionSettings(client_id="id-a"))["state"], STATE_SIGNED_IN)
        self.assertEqual(auth.status(ConnectionSettings(client_id=""))["state"], STATE_SIGNED_OUT)


if __name__ == "__main__":
    unittest.main()
