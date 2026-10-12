import os
import tempfile
import unittest

from src.config.config_service import ConfigError, ConfigService
from src.publish.sender import SEND_LOG, FolderError, _load_log


class ConfigFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "config.json")

    def test_no_file_is_a_first_run(self):
        self.assertEqual(ConfigService(self.path).config.mode, "local")

    def test_a_damaged_file_is_an_error_and_is_left_alone(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(ConfigError) as caught:
            ConfigService(self.path)
        self.assertIn(self.path, str(caught.exception))
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{not json")


class SendLogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def write(self, text):
        with open(os.path.join(self.folder.name, SEND_LOG), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_a_folder_never_sent_has_no_log(self):
        self.assertEqual(_load_log(self.folder.name), {})

    def test_a_log_is_read(self):
        self.write('{"A": {"id": "1"}}')
        self.assertEqual(_load_log(self.folder.name), {"A": {"id": "1"}})

    def test_a_damaged_log_stops_the_send(self):
        self.write("{not json")
        with self.assertRaises(FolderError):
            _load_log(self.folder.name)

    def test_a_log_that_is_not_an_object_stops_the_send(self):
        self.write("[]")
        with self.assertRaises(FolderError):
            _load_log(self.folder.name)


if __name__ == "__main__":
    unittest.main()
