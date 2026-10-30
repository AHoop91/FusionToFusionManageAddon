"""A sign-out ends the sign-ins and token refreshes that were under way: none of them may save tokens or change the state afterwards."""

import unittest
from unittest import mock

from src.auth import auth_service
from src.auth.auth_service import STATE_SIGNED_IN, STATE_SIGNED_OUT, STATE_SIGNING_IN, AuthService
from src.auth.errors import AuthError
from src.config.models import ConnectionSettings

SETTINGS = ConnectionSettings(client_id="c")


class Store:
    def __init__(self, tokens=None):
        self.tokens = tokens
        self.saved = []

    def load(self, _client_id):
        return self.tokens

    def save(self, _client_id, tokens):
        self.tokens = tokens
        self.saved.append(tokens)

    def clear(self, _client_id):
        self.tokens = None


def expired():
    return {"access_token": "old", "refresh_token": "r", "expires_at": 0}


class RefreshTests(unittest.TestCase):
    def test_a_refresh_under_way_when_the_user_signs_out_does_not_bring_the_session_back(self):
        store = Store(expired())
        service = AuthService(store)

        def refresh(*_args):
            service.sign_out(SETTINGS)   # the user signs out while the request to the token endpoint is out
            return {"access_token": "new", "refresh_token": "r2", "expires_at": 9e12}

        with mock.patch.object(auth_service, "refresh_tokens", side_effect=refresh):
            with self.assertRaises(AuthError):
                service.get_access_token(SETTINGS)
        self.assertEqual(store.saved, [])
        self.assertIsNone(store.load("c"))
        self.assertEqual(service.status(SETTINGS)["state"], STATE_SIGNED_OUT)

    def test_a_refresh_nothing_interrupted_is_saved(self):
        store = Store(expired())
        with mock.patch.object(auth_service, "refresh_tokens", return_value={"access_token": "new", "expires_at": 9e12}):
            self.assertEqual(AuthService(store).get_access_token(SETTINGS), "new")
        self.assertEqual(store.tokens["refresh_token"], "r")

    def test_a_refused_refresh_of_an_older_session_does_not_sign_out_the_new_one(self):
        store = Store(expired())
        service = AuthService(store)

        def refuse(*_args):
            service.sign_out(SETTINGS)
            store.tokens = {"access_token": "fresh", "refresh_token": "r9", "expires_at": 9e12}   # a new sign-in finished
            raise AuthError("dead", rejected=True)

        with mock.patch.object(auth_service, "refresh_tokens", side_effect=refuse):
            with self.assertRaises(AuthError):
                service.get_access_token(SETTINGS)
        self.assertEqual(store.tokens["access_token"], "fresh")

    def test_a_sign_out_of_another_client_leaves_the_refresh_alone(self):
        store = Store(expired())
        service = AuthService(store)

        def refresh(*_args):
            service.sign_out(ConnectionSettings(client_id="other"))
            return {"access_token": "new", "refresh_token": "r2", "expires_at": 9e12}

        with mock.patch.object(auth_service, "refresh_tokens", side_effect=refresh):
            self.assertEqual(service.get_access_token(SETTINGS), "new")
        self.assertEqual(len(store.saved), 1)


class LoginTests(unittest.TestCase):
    def login(self, service, outcome):
        """Run a sign-in whose browser wait is ``outcome`` (a function that may sign out first), then return."""
        server = mock.Mock()
        server.wait.side_effect = outcome
        with service._lock:
            service._state, service._client_id = STATE_SIGNING_IN, "c"
            generation = service._generations.get("c", 0)
        with mock.patch.object(auth_service, "exchange_code", return_value={"access_token": "a", "expires_at": 9e12}):
            service._run_login(SETTINGS, "v", server, generation)

    def test_a_sign_in_that_finishes_after_a_sign_out_keeps_no_tokens(self):
        store = Store()
        service = AuthService(store)

        def wait(*_args):
            service.sign_out(SETTINGS)
            return {"code": "x", "error": ""}

        self.login(service, wait)
        self.assertEqual(store.saved, [])
        self.assertEqual(service.status(SETTINGS)["state"], STATE_SIGNED_OUT)

    def test_a_sign_in_cut_short_by_a_sign_out_is_not_reported_as_failed(self):
        service = AuthService(Store())

        def wait(*_args):
            service.sign_out(SETTINGS)
            return {"code": "", "error": "Sign-in was cancelled."}

        self.login(service, wait)
        self.assertEqual(service.status(SETTINGS), {"state": STATE_SIGNED_OUT, "error": ""})

    def test_a_sign_out_during_a_sign_in_ends_the_wait(self):
        service = AuthService(Store())
        service._state, service._client_id = STATE_SIGNING_IN, "c"
        service._cancel.clear()
        service.sign_out(SETTINGS)
        self.assertTrue(service._cancel.is_set())

    def test_a_sign_in_nothing_interrupted_is_kept(self):
        store = Store()
        service = AuthService(store)
        self.login(service, lambda *_args: {"code": "x", "error": ""})
        self.assertEqual(len(store.saved), 1)
        self.assertEqual(service.status(SETTINGS)["state"], STATE_SIGNED_IN)

    def test_a_refresh_begun_before_a_new_sign_in_does_not_save_over_it(self):
        store = Store(expired())
        service = AuthService(store)

        def refresh(*_args):
            self.login(service, lambda *_a: {"code": "x", "error": ""})   # the user signs in again meanwhile
            return {"access_token": "stale", "refresh_token": "r2", "expires_at": 9e12}

        with mock.patch.object(auth_service, "refresh_tokens", side_effect=refresh):
            with self.assertRaises(AuthError):
                service.get_access_token(SETTINGS)
        self.assertEqual([t["access_token"] for t in store.saved], ["a"])


if __name__ == "__main__":
    unittest.main()
