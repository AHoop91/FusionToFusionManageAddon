"""The picture of a product, read from the link its item gave for it."""

import unittest
from unittest import mock

from src.fm import tableaus
from src.fm.client import FmApiError
from src.fm.tableaus import TableauService

GOOD = "/api/v2/workspaces/77/items/9/field-values/IMAGE/image/12"


class PictureTests(unittest.TestCase):
    def test_the_picture_at_a_link_of_the_workspace_is_read(self):
        with mock.patch.object(tableaus, "load_image", return_value="data:image/png;base64,AA") as load:
            self.assertEqual(TableauService(mock.Mock()).picture("77", GOOD), {"image": "data:image/png;base64,AA"})
        self.assertEqual(load.call_args[0][1], GOOD)

    def test_any_other_link_is_refused_unread(self):
        for link in ("", "https://example.com/x.png", "/api/v2/workspaces/78/items/9/field-values/IMAGE/image/12",
                     "/api/v3/workspaces/77/items/9/attachments", GOOD + "/../x", "/api/v2/workspaces/77/items/9/field-values/image/image/1"):
            with self.subTest(link=link), mock.patch.object(tableaus, "load_image") as load:
                with self.assertRaises(FmApiError):
                    TableauService(mock.Mock()).picture("77", link)
                load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
