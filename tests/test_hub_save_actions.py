"""Saving the hub's Configuration File to the Fusion Hub, and making the places for it. Run: python -m unittest discover tests"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from src.config.config_transfer import CONFIG_FILE_NAME
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import hub_save_actions
    from src.ui.actions.hub_file_actions import NO_HUB
    from src.ui.actions.hub_save_actions import MAX_NAME_LENGTH, HubSaves, register_hub_save_actions
    from src.ui.message_bridge import MessageBridge

STATES = SimpleNamespace(UploadProcessing="processing", UploadFinished="finished", UploadFailed="failed")


class Setup(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(hub_id="hub-1", hub_name="Hub One")
        self.folder = mock.Mock()
        self.folder.name = "Configs"
        self.folder.uploadFile.return_value = SimpleNamespace(uploadState=STATES.UploadProcessing)
        self.data = mock.Mock()
        self.data.findFolderById.return_value = self.folder
        self.data.dataProjects.itemById.return_value = SimpleNamespace(rootFolder=self.folder)
        self.data.activeHub = SimpleNamespace(id="hub-1", dataProjects=mock.Mock())
        self.saves = HubSaves(self.config, lambda: self.data, lambda: STATES)
        patch = mock.patch.object(hub_save_actions, "config_file_bytes", return_value=b"{}")
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.saves._forget)


class StartTests(Setup):
    def test_the_file_is_written_and_uploaded_to_the_folder_and_it_is_pending(self):
        uploaded = []

        def upload(path):
            with open(path, "rb") as handle:
                uploaded.append((path, handle.read()))
            return SimpleNamespace(uploadState=STATES.UploadProcessing)

        self.folder.uploadFile.side_effect = upload
        self.assertEqual(self.saves.start({"project_id": "p1", "folder_id": "f1"}), {"pending": True})
        self.assertEqual((os.path.basename(uploaded[0][0]), uploaded[0][1]), (CONFIG_FILE_NAME, b"{}"))
        self.data.findFolderById.assert_called_once_with("f1")

    def test_with_no_folder_named_the_projects_root_folder_is_used(self):
        self.saves.start({"project_id": "p1"})
        self.data.dataProjects.itemById.assert_called_once_with("p1")
        self.folder.uploadFile.assert_called_once()

    def test_no_hub_is_refused(self):
        self.config.hub_id = ""
        with self.assertRaisesRegex(ValueError, NO_HUB):
            self.saves.start({"project_id": "p1"})

    def test_no_project_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Choose a folder in a project"):
            self.saves.start({"folder_id": "f1"})

    def test_a_folder_fusion_cannot_open_is_refused_before_anything_is_written(self):
        self.data.findFolderById.return_value = None
        with mock.patch.object(hub_save_actions.tempfile, "mkdtemp") as made:
            with self.assertRaisesRegex(ValueError, "could not open that folder"):
                self.saves.start({"project_id": "p1", "folder_id": "gone"})
        made.assert_not_called()

    def test_a_failed_upload_start_leaves_no_temporary_folder(self):
        directories = []

        def refuse(path):
            directories.append(os.path.dirname(path))
            raise RuntimeError("no")

        self.folder.uploadFile.side_effect = refuse
        with self.assertRaises(RuntimeError):
            self.saves.start({"project_id": "p1"})
        self.assertFalse(os.path.exists(directories[0]))

    def test_a_new_save_discards_the_one_never_asked_about(self):
        self.saves.start({"project_id": "p1"})
        first = self.saves._upload.directory
        self.saves.start({"project_id": "p1"})
        self.assertFalse(os.path.exists(first))
        self.assertTrue(os.path.exists(self.saves._upload.directory))


class StatusTests(Setup):
    def start_with(self, state):
        self.folder.uploadFile.return_value = SimpleNamespace(uploadState=state)
        self.saves.start({"project_id": "p1"})
        return self.saves._upload.directory

    def test_without_a_save_under_way_it_is_refused(self):
        with self.assertRaisesRegex(ValueError, "No save to the Fusion Hub is under way"):
            self.saves.status()

    def test_an_upload_still_processing_is_pending_and_kept(self):
        directory = self.start_with(STATES.UploadProcessing)
        self.assertEqual(self.saves.status(), {"pending": True})
        self.assertTrue(os.path.exists(directory))

    def test_a_finished_upload_says_where_and_clears_the_temporary_folder(self):
        directory = self.start_with(STATES.UploadFinished)
        self.assertEqual(self.saves.status(), {"pending": False, "ok": True, "folder": "Configs", "name": CONFIG_FILE_NAME})
        self.assertFalse(os.path.exists(directory))
        with self.assertRaises(ValueError):   # it is told once
            self.saves.status()

    def test_a_failed_upload_is_refused_with_where_and_clears_the_temporary_folder(self):
        directory = self.start_with(STATES.UploadFailed)
        with self.assertRaisesRegex(ValueError, "could not save the file to Configs"):
            self.saves.status()
        self.assertFalse(os.path.exists(directory))


class CreateTests(Setup):
    def test_a_project_is_made_in_the_open_hub(self):
        self.data.activeHub.dataProjects.add.return_value = object()
        self.assertEqual(self.saves.create({"kind": "project", "name": "  Configs  "}), {"name": "Configs"})
        self.data.activeHub.dataProjects.add.assert_called_once_with("Configs")

    def test_a_project_is_not_made_when_the_hub_changed(self):
        self.data.activeHub = SimpleNamespace(id="hub-2", dataProjects=mock.Mock())
        with self.assertRaisesRegex(ValueError, "The hub changed"):
            self.saves.create({"kind": "project", "name": "X"})
        self.data.activeHub.dataProjects.add.assert_not_called()

    def test_a_project_is_not_made_when_no_hub_is_active(self):
        self.data.activeHub = None
        with self.assertRaisesRegex(ValueError, "The hub changed"):
            self.saves.create({"kind": "project", "name": "X"})

    def test_a_folder_is_made_in_the_folder_named(self):
        self.folder.dataFolders.add.return_value = object()
        self.saves.create({"kind": "folder", "name": "Sub", "project_id": "p1", "folder_id": "f1"})
        self.folder.dataFolders.add.assert_called_once_with("Sub")

    def test_a_folder_in_a_project_with_none_named_is_made_in_its_root(self):
        self.folder.dataFolders.add.return_value = object()
        self.saves.create({"kind": "folder", "name": "Sub", "project_id": "p1"})
        self.data.dataProjects.itemById.assert_called_once_with("p1")

    def test_a_folder_to_add_to_that_fusion_cannot_open_is_refused(self):
        self.data.findFolderById.return_value = None
        with self.assertRaisesRegex(ValueError, "could not open the folder to add to"):
            self.saves.create({"kind": "folder", "name": "Sub", "folder_id": "gone"})

    def test_something_fusion_would_not_make_is_refused(self):
        self.folder.dataFolders.add.return_value = None
        with self.assertRaisesRegex(ValueError, "could not create Sub"):
            self.saves.create({"kind": "folder", "name": "Sub", "project_id": "p1"})

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Unknown kind"):
            self.saves.create({"kind": "file", "name": "X"})

    def test_names_fusion_would_not_take_are_refused_before_fusion_is_asked(self):
        for name in ("", "   ", "a/b", 'say "hi"', "x" * (MAX_NAME_LENGTH + 1)):
            with self.assertRaises(ValueError, msg=repr(name)):
                self.saves.create({"kind": "project", "name": name})
        self.data.activeHub.dataProjects.add.assert_not_called()

    def test_a_name_of_the_longest_length_is_taken(self):
        self.data.activeHub.dataProjects.add.return_value = object()
        self.saves.create({"kind": "project", "name": "x" * MAX_NAME_LENGTH})


class RegisterTests(unittest.TestCase):
    def test_the_actions_are_registered_and_a_status_with_no_save_is_an_error_reply(self):
        bridge = MessageBridge()
        register_hub_save_actions(bridge, SimpleNamespace(hub_id="h", hub_name="H"))
        reply = bridge.dispatch("save_to_hub_status", "")
        self.assertEqual((reply["ok"], reply["error"]), (False, "No save to the Fusion Hub is under way."))
        reply = bridge.dispatch("create_in_hub", '{"kind": "project", "name": ""}')
        self.assertEqual((reply["ok"], reply["error"]), (False, "Enter a name."))
        self.assertFalse(bridge.dispatch("save_to_hub", "{}")["ok"])


if __name__ == "__main__":
    unittest.main()
