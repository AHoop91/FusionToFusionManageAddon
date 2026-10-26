"""The hub's Configuration File: read from the Fusion Hub, checked, and used as the hub's settings for a member who is not a Hub Admin."""

import json
import os
import tempfile
import unittest

from src.config.config_envelope import FORMAT_ID, FORMAT_VERSION, MAX_CONFIG_BYTES, ConfigTransferError, parse_envelope
from src.config.config_service import ConfigService
from src.config.config_transfer import config_file_bytes, config_from_hub_file
from src.config.models import MODE_LOCAL, AppConfig, ConnectionSettings
from src.fusion_mfg.hub_files import API, HubFiles, HubFilesError

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

    def test_only_the_hub_that_read_the_file_has_it(self):
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client"), self.service.config.workspaces, "")
        self.service.apply_hub_file(config_from_hub_file(file_bytes(), HUB_A, "Hub A"), self.ref)
        self.service.use_hub(HUB_B, "Hub B")
        self.assertIsNone(self.service.config.hub_file)
        self.assertEqual(self.service.config.local.tenant, "")

    def test_without_a_client_id_nothing_is_applied(self):
        problems = self.service.apply_hub_file(config_from_hub_file(file_bytes(), HUB_A, "Hub A"), self.ref)
        self.assertEqual(problems, ["Client ID: enter the Client ID of your Autodesk app."])
        self.assertIsNone(self.service.config.hub_file)

    def test_saving_by_hand_forgets_the_file(self):
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client"), self.service.config.workspaces, "")
        self.service.apply_hub_file(config_from_hub_file(file_bytes(), HUB_A, "Hub A"), self.ref)
        self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-client", tenant="mine"), self.service.config.workspaces, "")
        self.assertIsNone(self.service.config.hub_file)


class FakeHub(HubFiles):
    """A hub's REST answers by the end of the address; records which calls were made with the access token."""

    def __init__(self, answers):
        super().__init__(None, None)
        self.answers, self.calls = answers, []

    def _open(self, url, authorised=True, headers=None):
        self.calls.append((url, authorised))
        for tail, body in self.answers.items():
            if tail in url:
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise AssertionError("unexpected address " + url)


def entry(kind, identifier, name):
    return {"type": kind, "id": identifier, "attributes": {"displayName": name}}


class BrowseTests(unittest.TestCase):
    def test_folders_and_files_are_told_apart_and_sorted(self):
        hub = FakeHub({"/contents": {"data": [entry("items", "i2", "b.json"), entry("folders", "f1", "Zeta"), entry("items", "i1", "A.json"),
                                              entry("folders", "f2", "alpha")]}})
        found = hub.contents("p", "urn:folder")
        self.assertEqual([f["name"] for f in found.folders], ["alpha", "Zeta"])
        self.assertEqual([f["name"] for f in found.files], ["A.json", "b.json"])

    def test_a_listing_is_followed_over_its_pages(self):
        class Paged(FakeHub):
            def _open(self, url, authorised=True, headers=None):
                if "page2" in url:
                    return json.dumps({"data": [entry("items", "i2", "two.json")]}).encode()
                return json.dumps({"data": [entry("items", "i1", "one.json")], "links": {"next": {"href": API + "/page2"}}}).encode()
        found = Paged({}).contents("p", "f")
        self.assertEqual([f["name"] for f in found.files], ["one.json", "two.json"])

    def test_the_projects_of_the_hub_are_listed_by_name(self):
        hub = FakeHub({"/projects": {"data": [{"id": "p2", "attributes": {"name": "Beta"}}, {"id": "p1", "attributes": {"name": "alpha"}}]}})
        self.assertEqual([p["name"] for p in hub.projects(HUB_A).folders], ["alpha", "Beta"])


class ReadTests(unittest.TestCase):
    TIP = {"data": {"attributes": {"storageSize": 120}, "relationships": {"storage": {"data": {"id": "urn:adsk.objects:os.object:wip.dm.prod/abc.json"}}}}}

    def test_a_file_is_read_through_its_signed_address_without_the_token(self):
        hub = FakeHub({"/tip": self.TIP, "/signeds3download": {"url": "https://signed.example/abc"}, "signed.example": b'{"a": 1}'})
        self.assertEqual(hub.read_file("p", "i", 1000), b'{"a": 1}')
        self.assertEqual([authorised for url, authorised in hub.calls if "signed.example" in url], [False])
        self.assertTrue(all(authorised for url, authorised in hub.calls if "signed.example" not in url))

    def test_a_file_that_is_too_large_is_not_downloaded(self):
        hub = FakeHub({"/tip": self.TIP})
        with self.assertRaises(HubFilesError):
            hub.read_file("p", "i", 100)
        self.assertEqual(len(hub.calls), 1)   # only the size was asked

    def test_a_signed_address_that_is_not_https_is_refused(self):
        hub = FakeHub({"/tip": self.TIP, "/signeds3download": {"url": "http://signed.example/abc"}})
        with self.assertRaises(HubFilesError):
            hub.read_file("p", "i", 1000)

    def test_a_file_with_no_content_is_refused(self):
        hub = FakeHub({"/tip": {"data": {"attributes": {}, "relationships": {}}}})
        with self.assertRaises(HubFilesError):
            hub.read_file("p", "i", 1000)


if __name__ == "__main__":
    unittest.main()
