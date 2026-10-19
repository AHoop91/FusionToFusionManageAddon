"""Shared Configuration: the settings come from one shared file, with the last good copy kept for when it cannot be read."""

import json
import os
import tempfile
import unittest

from src.config.config_envelope import FORMAT_ID, FORMAT_VERSION
from src.config.config_service import (
    SHARED_CACHED, SHARED_ERROR, SHARED_OFF, SHARED_OK, CompanyModeUnavailable, ConfigService,
)
from src.config.models import MODE_COMPANY, MODE_LOCAL, AppConfig, ConnectionSettings


def write_shared(path: str, client_id: str = "shared-id", tenant: str = "acme") -> None:
    shared = AppConfig(local=ConnectionSettings(client_id=client_id, tenant=tenant))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"format": FORMAT_ID, "version": FORMAT_VERSION, "config": shared.to_dict()}, handle)


class SharedConfigTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.shared_path = os.path.join(folder.name, "shared.json")
        self.service = ConfigService(os.path.join(folder.name, "config.json"))

    def use_shared(self):
        local = ConnectionSettings(client_id="my-own-id", tenant="mine")
        self.assertEqual(self.service.update(MODE_LOCAL, local, self.service.config.workspaces, ""), [])
        self.assertEqual(self.service.update(MODE_COMPANY, local, self.service.config.workspaces, self.shared_path), [])
        self.service.effective_settings()   # reads the file now, which also keeps the copy

    def test_the_shared_file_replaces_the_local_connection(self):
        write_shared(self.shared_path)
        self.use_shared()
        self.assertEqual(self.service.effective_settings().client_id, "shared-id")
        self.assertEqual(self.service.config.local.tenant, "acme")
        self.assertEqual(self.service.shared_status.state, SHARED_OK)

    def test_a_missing_file_cannot_be_selected(self):
        problems = self.service.update(MODE_COMPANY, ConnectionSettings(), self.service.config.workspaces, self.shared_path)
        self.assertEqual(len(problems), 1)
        self.assertEqual(self.service.config.mode, MODE_LOCAL)

    def test_an_empty_path_cannot_be_selected(self):
        problems = self.service.update(MODE_COMPANY, ConnectionSettings(), self.service.config.workspaces, "  ")
        self.assertEqual(problems, ["No shared configuration file is set."])

    def test_a_file_that_is_not_ours_cannot_be_selected(self):
        with open(self.shared_path, "w", encoding="utf-8") as handle:
            json.dump({"hello": "world"}, handle)
        self.assertEqual(len(self.service.update(MODE_COMPANY, ConnectionSettings(), self.service.config.workspaces, self.shared_path)), 1)

    def test_the_last_good_copy_is_used_when_the_file_goes_away(self):
        write_shared(self.shared_path)
        self.use_shared()
        os.remove(self.shared_path)
        self.service._shared_checked = None   # as if the refresh time had passed
        self.assertEqual(self.service.effective_settings().client_id, "shared-id")
        self.assertEqual(self.service.shared_status.state, SHARED_CACHED)

    def test_without_a_copy_an_unreadable_file_is_reported(self):
        write_shared(self.shared_path)
        self.use_shared()
        os.remove(self.shared_path)
        os.remove(self.service._cache_path)
        self.service._shared_checked = None
        with self.assertRaises(CompanyModeUnavailable):
            self.service.effective_settings()
        self.assertEqual(self.service.shared_status.state, SHARED_ERROR)

    def test_a_copy_of_another_file_is_not_used(self):
        write_shared(self.shared_path)
        self.use_shared()
        other = self.shared_path + ".other.json"
        write_shared(other, client_id="other-id")
        self.assertEqual(self.service.update(MODE_COMPANY, ConnectionSettings(), self.service.config.workspaces, other), [])
        os.remove(other)   # the copy kept is of shared.json, so it does not stand in for other.json
        with self.assertRaises(CompanyModeUnavailable):
            self.service.effective_settings()

    def test_the_file_is_read_again_after_the_refresh_time(self):
        write_shared(self.shared_path)
        self.use_shared()
        write_shared(self.shared_path, client_id="changed-id")
        self.assertEqual(self.service.effective_settings().client_id, "shared-id")   # not yet: the read is reused
        self.service._shared_checked = None
        self.assertEqual(self.service.effective_settings().client_id, "changed-id")

    def test_going_back_to_local_keeps_the_users_own_settings(self):
        write_shared(self.shared_path)
        self.use_shared()
        self.assertEqual(self.service.update(MODE_LOCAL, ConnectionSettings(client_id="my-own-id", tenant="mine"),
                                             self.service.config.workspaces, self.shared_path), [])
        self.assertEqual(self.service.effective_settings().client_id, "my-own-id")
        self.assertEqual(self.service.shared_status.state, SHARED_OFF)

    def test_saving_in_shared_mode_does_not_copy_the_shared_settings_into_the_profile(self):
        write_shared(self.shared_path)
        self.use_shared()
        self.service.update(MODE_COMPANY, self.service.config.local, self.service.config.workspaces, self.shared_path)
        with open(self.service._path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(saved["local"]["client_id"], "my-own-id")
        self.assertEqual(saved["company"]["source"], self.shared_path)


if __name__ == "__main__":
    unittest.main()
