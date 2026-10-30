"""The add-in keeps files in the user's application data and the temporary folder only: with no usable folder it keeps nothing, and it never
falls back to the home folder."""

import os
import tempfile
import unittest
from unittest import mock

from src.auth import token_store
from src.config import config_service
from src.config.config_envelope import ConfigTransferError
from src.config.shared_config import NOT_ABSOLUTE, clean_source, read_shared
from src.core import logging_setup, paths
from src.ui import item_numbers


@mock.patch.object(paths.sys, "platform", "win32")
class DataDirTests(unittest.TestCase):
    def test_local_and_roaming_come_from_their_own_variables(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\L", "APPDATA": r"C:\R"}):
            self.assertEqual(paths.data_dir(), os.path.join(r"C:\L", "MfgToFm"))
            self.assertEqual(paths.data_dir(roaming=True), os.path.join(r"C:\R", "MfgToFm"))
            self.assertEqual(paths.log_dir(), os.path.join(r"C:\L", "MfgToFm", "logs"))

    def test_a_missing_or_relative_variable_is_an_error_not_the_home_folder(self):
        for env in ({}, {"LOCALAPPDATA": "", "APPDATA": ""}, {"LOCALAPPDATA": "  ", "APPDATA": "  "},
                    {"LOCALAPPDATA": "relative", "APPDATA": "relative"}, {"LOCALAPPDATA": "~", "APPDATA": "~"}):
            with mock.patch.dict(os.environ, env, clear=True):
                for call in (paths.data_dir, lambda: paths.data_dir(roaming=True), paths.log_dir):
                    with self.assertRaises(paths.DataDirError):
                        call()

    def test_the_token_file_and_the_settings_are_not_kept_without_a_folder(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": "", "APPDATA": ""}):
            with self.assertRaises(paths.DataDirError):
                token_store._DpapiBackend()
            with self.assertRaises(paths.DataDirError):
                config_service.config_path()

    def test_remembered_item_numbers_fall_back_to_the_temporary_folder(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": ""}):
            self.assertEqual(item_numbers._remembered_path(), os.path.join(paths.temp_dir(), "item_numbers.json"))


@mock.patch.object(paths.sys, "platform", "darwin")
class MacDataDirTests(unittest.TestCase):
    def test_the_folders_are_in_the_users_library(self):
        with mock.patch.object(paths.os.path, "expanduser", side_effect=lambda p: p.replace("~", "/Users/me", 1)):
            self.assertEqual(paths.data_dir(), os.path.join("/Users/me/Library/Application Support", "MfgToFm"))
            self.assertEqual(paths.data_dir(roaming=True), paths.data_dir())
            self.assertEqual(paths.log_dir(), os.path.join("/Users/me/Library/Logs", "MfgToFm", "logs"))

    def test_an_unknown_home_folder_is_an_error_not_a_relative_path(self):
        with mock.patch.object(paths.os.path, "expanduser", side_effect=lambda p: p), \
                mock.patch.object(paths.os.path, "isabs", side_effect=lambda p: p.startswith("/")):
            for call in (paths.data_dir, paths.log_dir):
                with self.assertRaises(paths.DataDirError):
                    call()


class InsideTempTests(unittest.TestCase):
    def test_only_a_path_in_the_temporary_folder_is_inside(self):
        base = tempfile.gettempdir()
        self.assertTrue(paths.inside_temp(os.path.join(base, "x", "logs")))
        self.assertFalse(paths.inside_temp(os.path.join(base, "..", "elsewhere")))
        self.assertFalse(paths.inside_temp(os.path.dirname(base)))
        self.assertFalse(paths.inside_temp("logs"))
        self.assertFalse(paths.inside_temp(""))


class LogDirectoryTests(unittest.TestCase):
    def test_the_override_is_honoured_inside_the_temporary_folder(self):
        folder = tempfile.mkdtemp(prefix="mfgtofm-paths-")
        self.addCleanup(os.rmdir, folder)
        with mock.patch.dict(os.environ, {logging_setup.LOG_DIR_ENV: folder}):
            self.assertEqual(logging_setup.log_directory(), folder)

    def test_the_override_cannot_send_the_logs_elsewhere(self):
        elsewhere = os.path.join(os.path.dirname(tempfile.gettempdir()), "mfgtofm-not-here")
        with mock.patch.dict(os.environ, {logging_setup.LOG_DIR_ENV: elsewhere}), \
                mock.patch.object(logging_setup, "log_dir", return_value=os.path.join(tempfile.gettempdir(), "mfgtofm-user-logs")) as user, \
                mock.patch.object(logging_setup.os, "makedirs") as make:
            self.assertEqual(logging_setup.log_directory(), user.return_value)
            make.assert_called_once_with(user.return_value, exist_ok=True)

    def test_without_a_user_folder_the_logs_go_to_the_temporary_folder(self):
        with mock.patch.dict(os.environ, {logging_setup.LOG_DIR_ENV: ""}), \
                mock.patch.object(logging_setup, "log_dir", side_effect=paths.DataDirError("no")), \
                mock.patch.object(logging_setup.os, "makedirs"):
            self.assertEqual(logging_setup.log_directory(), os.path.join(paths.temp_dir(), "logs"))


class SharedSourceTests(unittest.TestCase):
    def test_nothing_in_the_path_is_expanded(self):
        with mock.patch.dict(os.environ, {"SOMEWHERE": r"C:\Elsewhere"}):
            self.assertEqual(clean_source(r' "%SOMEWHERE%\a.json" '), r"%SOMEWHERE%\a.json")
            self.assertEqual(clean_source("~/a.json"), "~/a.json")

    def test_a_path_that_is_not_full_is_refused_before_it_is_read(self):
        for source in ("a.json", r"~\a.json", r"%APPDATA%\a.json", r"..\a.json"):
            with mock.patch("src.config.shared_config.read_envelope") as read:
                with self.assertRaises(ConfigTransferError) as caught:
                    read_shared(source)
                self.assertEqual(str(caught.exception), NOT_ABSOLUTE)
                read.assert_not_called()
