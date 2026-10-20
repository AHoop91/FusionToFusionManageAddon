import io
import unittest
import urllib.error
from unittest import mock

from src.auth import auth_service, oauth_pkce
from src.auth.auth_service import AuthService
from src.auth.errors import AuthError
from src.config.models import ConnectionSettings
from src.core import http


class Store:
    def __init__(self):
        self.tokens = {"access_token": "a", "refresh_token": "r", "expires_at": 0}
        self.cleared = False

    def load(self, _client_id):
        return None if self.cleared else self.tokens

    def save(self, _client_id, tokens):
        self.tokens = tokens

    def clear(self, _client_id):
        self.cleared = True


class RefreshFailureTests(unittest.TestCase):
    def refresh(self, error):
        store = Store()
        service = AuthService(store)
        with mock.patch.object(auth_service, "refresh_tokens", side_effect=error):
            with self.assertRaises(AuthError):
                service.get_access_token(ConnectionSettings(client_id="c"))
        return store

    def test_a_refused_refresh_signs_out(self):
        self.assertTrue(self.refresh(AuthError("no", rejected=True)).cleared)

    def test_a_failure_that_may_pass_keeps_the_session(self):
        self.assertFalse(self.refresh(AuthError("offline")).cleared)

    def test_token_endpoint_answers_are_told_apart(self):
        def post(code):
            error = urllib.error.HTTPError("https://x", code, "m", {}, io.BytesIO(b"{}"))
            with mock.patch.object(http.OPENER, "open", side_effect=error):
                with self.assertRaises(AuthError) as caught:
                    oauth_pkce.refresh_tokens("c", "r", [])
            error.close()
            return caught.exception.rejected
        self.assertTrue(post(400))
        self.assertTrue(post(401))
        self.assertFalse(post(503))
        self.assertFalse(post(429))
        with mock.patch.object(http.OPENER, "open", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(AuthError) as caught:
                oauth_pkce.refresh_tokens("c", "r", [])
        self.assertFalse(caught.exception.rejected)


if __name__ == "__main__":
    unittest.main()
