import base64
import os
import sys
import tempfile
import unittest
from unittest import mock

from src.auth import token_store
from src.auth.token_store import TokenStore, _KeychainBackend, _quote


@unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows only")
class DpapiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patch = mock.patch.dict(os.environ, {"LOCALAPPDATA": folder.name})
        patch.start()
        self.addCleanup(patch.stop)
        self.backend = token_store._DpapiBackend()
        self.store = TokenStore(self.backend)

    def test_round_trip_leaves_no_temp_file(self):
        self.store.save("client", {"access_token": "a", "refresh_token": "r"})
        self.assertEqual(self.store.load("client"), {"access_token": "a", "refresh_token": "r"})
        self.assertEqual([n for n in os.listdir(self.backend._dir) if n.endswith(".tmp")], [])

    def test_the_file_needs_the_entropy(self):
        self.store.save("client", {"access_token": "a"})
        with open(self.backend._file("client"), "rb") as handle:
            blob = handle.read()
        with self.assertRaises(OSError):
            token_store._dpapi(blob, False, None)

    def test_a_file_from_the_earlier_version_is_read_and_kept_the_new_way(self):
        path = self.backend._file("client")
        with open(path, "wb") as handle:
            handle.write(token_store._dpapi(b'{"access_token": "old"}', True, None))
        self.assertEqual(self.store.load("client"), {"access_token": "old"})
        with open(path, "rb") as handle:
            token_store._dpapi(handle.read(), False)   # now needs the entropy, and has it

    def test_clear_forgets(self):
        self.store.save("client", {"access_token": "a"})
        self.store.clear("client")
        self.assertIsNone(self.store.load("client"))


class KeychainTests(unittest.TestCase):
    def test_tokens_go_in_on_stdin_not_the_command_line(self):
        with mock.patch.object(token_store.subprocess, "run") as run:
            _KeychainBackend().save('cl"ient', b"secret-token")
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["security", "-i"])
        self.assertNotIn(base64.b64encode(b"secret-token").decode(), " ".join(args[0]))
        self.assertIn(base64.b64encode(b"secret-token").decode(), kwargs["input"])
        self.assertIn('-a "cl\\"ient"', kwargs["input"])
        self.assertEqual(kwargs["input"].count("\n"), 1)

    def test_a_client_id_cannot_add_a_second_command(self):
        with mock.patch.object(token_store.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                _KeychainBackend().save("a\ndelete-generic-password", b"x")
        run.assert_not_called()

    def test_quote(self):
        self.assertEqual(_quote('a\\b"c'), '"a\\\\b\\"c"')


if __name__ == "__main__":
    unittest.main()
