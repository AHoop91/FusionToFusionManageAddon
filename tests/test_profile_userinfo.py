"""The Autodesk user profile becomes the panel's profile, with only an https picture."""

import unittest
from unittest import mock

from src.auth.errors import AuthError
from src.fm.profile import ProfileService, parse_userinfo


class ParseUserinfoTests(unittest.TestCase):
    def test_maps_the_fields_the_panel_shows(self):
        profile = parse_userinfo({"sub": "ABC123", "name": "Ash Hooper", "email": "ash@example.com", "picture": "https://images.example.com/a.png"}, "acme")
        self.assertEqual(profile, {"name": "Ash Hooper", "email": "ash@example.com", "picture": "https://images.example.com/a.png",
                                   "picture_large": "https://images.example.com/a.png", "tenant": "acme", "user_id": "ABC123"})

    def test_the_name_is_built_from_its_parts_when_missing(self):
        self.assertEqual(parse_userinfo({"given_name": "Ash", "family_name": "Hooper"}, "")["name"], "Ash Hooper")

    def test_a_picture_that_is_not_https_is_dropped(self):
        self.assertEqual(parse_userinfo({"picture": "http://images.example.com/a.png"}, "")["picture"], "")

    def test_values_of_an_odd_shape_read_as_empty_rather_than_failing(self):
        profile = parse_userinfo({"given_name": 5, "family_name": ["x"], "email": None, "sub": 0, "picture": 3}, "acme")
        self.assertEqual((profile["name"], profile["email"], profile["user_id"], profile["picture"]), ("5 ['x']", "", "", ""))
        self.assertEqual(parse_userinfo("x", "acme")["name"], "")


class ProfileServiceTests(unittest.TestCase):
    def test_a_failure_gives_the_empty_profile_the_panel_shows_a_generic_avatar_for(self):
        service = ProfileService(mock.Mock(tenant="acme"))
        outcomes = ({"side_effect": AuthError("signed out")}, {"side_effect": OSError("403")}, {"side_effect": ValueError("not json")},
                    {"return_value": ["not", "an", "object"]})
        for outcome in outcomes:
            with self.subTest(outcome=outcome), mock.patch.object(service, "_fetch", **outcome):
                self.assertEqual(service.current(), service.empty())
        self.assertEqual(service.empty(), {"name": "", "email": "", "picture": "", "picture_large": "", "tenant": "acme", "user_id": ""})


if __name__ == "__main__":
    unittest.main()
