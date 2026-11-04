"""The languages a hub shares: chosen by a Hub Admin, carried in the Configuration File, kept by each member. Run: python -m unittest discover -s tests -t ."""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from src.config.config_transfer import config_file_bytes, languages_from_hub_file
from src.config.hub_languages import MAX_SHARED, HubLanguages, clean
from src.core import i18n
from tests.without_fusion import fusion_modules_stubbed

with fusion_modules_stubbed():
    from src.ui.actions import hub_file_actions, hub_save_actions
    from src.ui.actions.hub_file_actions import HubConfigFile
    from src.ui.actions.hub_save_actions import HubSaves
    from src.ui.actions.language_actions import language_payload


def language(name, **strings):
    return {"language": name, "strings": strings or {"a": "Hallo"}}


def write(folder, code, data):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, code + ".json"), "w", encoding="utf-8") as handle:
        json.dump(data, handle)


class CleanTests(unittest.TestCase):
    def test_a_usable_language_is_kept_with_its_name_and_text(self):
        self.assertEqual(clean({"de": language("Deutsch")}), {"de": language("Deutsch")})

    def test_what_cannot_be_used_is_left_out(self):
        bad = {"en": language("English"), "../x": language("Path"), "d": language("Short"), "fr": "text", "es": {"language": "Español"},
               "it": {"language": "Italiano", "strings": {"a": 5}}, "pt": {"strings": {"a": "Olá"}}, 7: language("Number")}
        self.assertEqual(clean(bad), {"pt": language("pt", a="Olá")})

    def test_a_file_that_has_no_languages_has_none(self):
        for nothing in (None, [], "x", {}):
            self.assertEqual(clean(nothing), {})

    def test_no_more_than_the_most_are_kept(self):
        many = {chr(97 + i // 26) + chr(97 + i % 26): language("L") for i in range(MAX_SHARED + 5)}
        self.assertEqual(len(clean(many)), MAX_SHARED)


class Folders(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.base, self.shipped = os.path.join(root.name, "settings"), os.path.join(root.name, "shipped")
        self.user = os.path.join(root.name, "user")
        write(self.shipped, "en", {"language": "English", "strings": {"a": "Hello"}})
        self.activated = []
        self.hubs = HubLanguages(self.base, lambda: self.activated.append(True))
        self.addCleanup(i18n.set_hub_dir, None)
        self.addCleanup(i18n.set_language, "en", user="", hub="")


class CollectTests(Folders):
    def test_every_language_of_the_users_own_goes_in_the_file_and_the_shipped_ones_do_not(self):
        write(self.user, "de", language("Deutsch"))
        write(self.user, "fr", language("Français"))
        write(self.shipped, "ja", language("日本語"))   # shipped: the add-in has it already
        self.assertEqual(self.hubs.collect(self.shipped, self.user), {"de": language("Deutsch"), "fr": language("Français")})

    def test_a_file_that_cannot_be_used_is_left_out_and_the_rest_go_in(self):
        write(self.user, "de", language("Deutsch"))
        os.makedirs(self.user, exist_ok=True)
        with open(os.path.join(self.user, "fr.json"), "w") as handle:
            handle.write("{ broken")
        write(self.user, "es", {"language": "Español", "strings": {"a": 5}})
        self.assertEqual(list(self.hubs.collect(self.shipped, self.user)), ["de"])

    def test_a_user_with_no_languages_of_their_own_shares_none(self):
        self.assertEqual(self.hubs.collect(self.shipped, self.user), {})


class ReceiveTests(Folders):
    def test_the_languages_are_kept_in_the_hubs_folder_and_found_there(self):
        self.assertEqual(self.hubs.receive("hub-1", {"de": language("Deutsch")}), ["de"])
        folder = self.hubs.folder("hub-1")
        self.assertTrue(os.path.isfile(os.path.join(folder, "de.json")))
        self.assertEqual(self.activated, [True])
        found = {l.code: l.source for l in i18n.available(self.shipped, "", folder)}
        self.assertEqual(found, {"en": "shipped", "de": "hub"})

    def test_the_active_hubs_languages_are_found_without_being_asked_for(self):
        self.hubs.receive("hub-1", {"de": language("Deutsch")})
        self.assertEqual(i18n.find("de", self.shipped, "").source, "hub")

    def test_a_language_the_hub_took_out_goes_and_an_empty_file_clears_them_all(self):
        self.hubs.receive("hub-1", {"de": language("Deutsch"), "fr": language("Français")})
        self.hubs.receive("hub-1", {"fr": language("Français")})
        self.assertEqual(sorted(os.listdir(self.hubs.folder("hub-1"))), ["fr.json"])
        self.hubs.receive("hub-1", {})
        self.assertFalse(os.path.exists(self.hubs.folder("hub-1")))

    def test_each_hub_keeps_its_own(self):
        self.hubs.receive("hub-1", {"de": language("Deutsch")})
        self.hubs.receive("hub-2", {"fr": language("Français")})
        self.assertEqual(os.listdir(self.hubs.folder("hub-1")), ["de.json"])
        self.assertEqual(os.listdir(self.hubs.folder("hub-2")), ["fr.json"])

    def test_a_hub_id_is_never_a_path(self):
        folder = self.hubs.folder("../../evil")
        self.assertEqual(os.path.dirname(folder), os.path.join(self.base, "hub-languages"))

    def test_nothing_unsafe_is_written(self):
        self.hubs.receive("hub-1", {"../escape": language("Evil"), "en": language("English"), "de": language("Deutsch")})
        self.assertEqual(os.listdir(self.hubs.folder("hub-1")), ["de.json"])
        self.assertFalse(os.path.exists(os.path.join(self.base, "escape.json")))


class PrecedenceTests(Folders):
    def test_the_users_file_wins_over_the_hubs_and_the_hubs_over_the_shipped(self):
        hub = os.path.join(self.base, "hub")
        write(self.shipped, "de", language("Deutsch (shipped)"))
        write(hub, "de", language("Deutsch (hub)"))
        self.assertEqual(i18n.find("de", self.shipped, "", hub).name, "Deutsch (hub)")
        write(self.user, "de", language("Deutsch (mine)"))
        self.assertEqual(i18n.find("de", self.shipped, self.user, hub).name, "Deutsch (mine)")

    def test_the_fall_back_to_english_is_always_the_shipped_one(self):
        hub = os.path.join(self.base, "hub")
        write(hub, "xx", {"language": "Hub", "strings": {"a": "Hub text"}})
        self.assertEqual(i18n.load("xx", self.shipped, "", hub)["a"], "Hub text")


class FileTests(unittest.TestCase):
    config = SimpleNamespace(hub_id="hub-1", hub_name="Hub One", config=SimpleNamespace(to_dict=lambda: {"mode": "local"}))

    def test_the_languages_are_a_section_of_the_file_beside_the_settings(self):
        raw = config_file_bytes(self.config, {"de": language("Deutsch")})
        self.assertEqual(json.loads(raw)["config"], {"mode": "local"})
        self.assertEqual(languages_from_hub_file(raw), {"de": language("Deutsch")})

    def test_a_file_without_them_shares_none_and_has_no_empty_section(self):
        raw = config_file_bytes(self.config)
        self.assertNotIn("languages", json.loads(raw))
        self.assertEqual(languages_from_hub_file(raw), {})
        self.assertNotIn("languages", json.loads(config_file_bytes(self.config, {})))


class SaveAndReadTests(unittest.TestCase):
    def test_once_the_file_is_in_the_hub_the_hub_is_noted_to_hold_what_was_saved(self):
        hubs = mock.Mock()
        hubs.collect.return_value = {"de": language("Deutsch")}
        folder = mock.Mock()
        folder.name = "Configs"
        uploads = SimpleNamespace(uploadState="processing")
        folder.uploadFile.return_value = uploads
        data = mock.Mock()
        data.findFolderById.return_value = folder
        data.dataProjects.itemById.return_value = SimpleNamespace(rootFolder=folder)
        states = SimpleNamespace(UploadProcessing="processing", UploadFinished="finished", UploadFailed="failed")
        saves = HubSaves(SimpleNamespace(hub_id="hub-1", hub_name="Hub One"), lambda: data, lambda: states, hubs)
        self.addCleanup(saves._forget)
        with mock.patch.object(hub_save_actions, "config_file_bytes", return_value=b"{}"):
            saves.start({"project_id": "p1"})
        saves.status()
        hubs.receive.assert_not_called()   # still saving
        uploads.uploadState = "finished"
        saves.status()
        hubs.receive.assert_called_once_with("hub-1", {"de": language("Deutsch")})

    def test_saving_puts_the_hub_admins_languages_in_the_file(self):
        hubs = mock.Mock()
        hubs.collect.return_value = {"de": language("Deutsch")}
        folder = mock.Mock()
        folder.name = "Configs"
        folder.uploadFile.return_value = SimpleNamespace(uploadState="processing")
        data = mock.Mock()
        data.findFolderById.return_value = folder
        data.dataProjects.itemById.return_value = SimpleNamespace(rootFolder=folder)
        config = SimpleNamespace(hub_id="hub-1", hub_name="Hub One")
        saves = HubSaves(config, lambda: data, lambda: SimpleNamespace(UploadProcessing="processing"), hubs)
        self.addCleanup(saves._forget)
        with mock.patch.object(hub_save_actions, "config_file_bytes", return_value=b"{}") as written:
            saves.start({"project_id": "p1"})
        written.assert_called_once_with(config, {"de": language("Deutsch")})
        hubs.collect.assert_called_once_with()

    def apply(self, hubs, raw):
        config = mock.Mock()
        config.hub_id, config.hub_name = "hub-1", "Hub One"
        config.apply_hub_file.return_value = []
        hub = mock.Mock()
        hub.file_info.return_value = {}
        hub.read_file.return_value = raw
        file = HubConfigFile(config, lambda: hub, hubs)
        with mock.patch.object(hub_file_actions, "config_from_hub_file", return_value="imported"), \
                mock.patch.object(hub_file_actions, "settings_payload", return_value={"shown": True}):
            return file.apply("hub-1", "Hub One", "p1", "i1", "hub.json")

    def test_reading_the_file_keeps_the_languages_it_shares(self):
        hubs = mock.Mock()
        raw = config_file_bytes(FileTests.config, {"de": language("Deutsch")})
        self.apply(hubs, raw)
        hubs.receive.assert_called_once_with("hub-1", {"de": language("Deutsch")})

    def test_a_file_with_no_languages_clears_the_ones_kept_before(self):
        hubs = mock.Mock()
        self.apply(hubs, config_file_bytes(FileTests.config))
        hubs.receive.assert_called_once_with("hub-1", {})

    def test_languages_that_cannot_be_kept_do_not_fail_the_settings(self):
        hubs = mock.Mock()
        hubs.receive.side_effect = OSError("disk full")
        self.assertEqual(self.apply(hubs, config_file_bytes(FileTests.config, {"de": language("Deutsch")})), {"settings": {"shown": True}})


class WhereItIsTests(Folders):
    """Each language of the user's own says whether the hub has it: Local, or Shared in hub."""

    def where(self, code="de"):
        payload = language_payload(self.shipped, self.user)
        return {l["code"]: l.get("sharing", {}).get("hub") for l in payload["languages"]}[code]

    def test_a_language_the_hub_does_not_have_is_local(self):
        write(self.user, "de", language("Deutsch"))
        self.assertEqual(self.where(), "none")

    def test_a_language_the_hub_has_with_the_same_content_is_shared_in_hub(self):
        write(self.user, "de", language("Deutsch"))
        self.hubs.receive("hub-1", {"de": language("Deutsch")})
        self.assertEqual(self.where(), "same")

    def test_a_language_changed_since_it_was_shared_says_the_hub_has_an_older_one(self):
        write(self.user, "de", language("Deutsch", a="Hallo"))
        self.hubs.receive("hub-1", {"de": language("Deutsch", a="Hallo alt")})
        self.assertEqual(self.where(), "different")

    def test_a_file_with_entries_that_are_not_text_still_matches_what_was_shared(self):
        write(self.user, "de", {"language": "Deutsch", "strings": {"a": "Hallo", "b": 5}})
        self.hubs.receive("hub-1", {"de": {"language": "Deutsch", "strings": {"a": "Hallo"}}})
        self.assertEqual(self.where(), "same")


class SharingStatusTests(Folders):
    def sharing(self):
        payload = language_payload(self.shipped, self.user)
        return {l["code"]: l.get("sharing") for l in payload["languages"]}

    def test_the_users_own_languages_say_they_are_shared_and_the_shipped_ones_say_nothing(self):
        write(self.user, "de", language("Deutsch"))
        write(self.shipped, "ja", language("日本語"))
        found = self.sharing()
        self.assertEqual(found["de"], {"included": True, "reason": "", "hub": "none"})
        self.assertIsNone(found["ja"])
        self.assertIsNone(found["en"])

    def test_a_language_whose_file_cannot_be_used_says_why_it_is_not_shared(self):
        write(self.user, "de", {"language": "Deutsch", "strings": {"zzz": "nothing English has"}})
        found = self.sharing()["de"]
        self.assertFalse(found["included"])
        self.assertTrue(found["reason"])


if __name__ == "__main__":
    unittest.main()
