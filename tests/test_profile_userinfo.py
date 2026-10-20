"""The Autodesk user profile becomes the panel's profile, with only an https picture."""

import unittest

from src.fm.profile import parse_userinfo


class ParseUserinfoTests(unittest.TestCase):
    def test_maps_the_fields_the_panel_shows(self):
        profile = parse_userinfo({"sub": "ABC123", "name": "Ash Hooper", "email": "ash@example.com", "picture": "https://images.example.com/a.png"}, "acme")
        self.assertEqual(profile, {"name": "Ash Hooper", "email": "ash@example.com", "picture": "https://images.example.com/a.png",
                                   "picture_large": "https://images.example.com/a.png", "tenant": "acme", "user_id": "ABC123"})

    def test_the_name_is_built_from_its_parts_when_missing(self):
        self.assertEqual(parse_userinfo({"given_name": "Ash", "family_name": "Hooper"}, "")["name"], "Ash Hooper")

    def test_a_picture_that_is_not_https_is_dropped(self):
        self.assertEqual(parse_userinfo({"picture": "http://images.example.com/a.png"}, "")["picture"], "")


if __name__ == "__main__":
    unittest.main()
