"""Downloading a thumbnail from its signed url."""

import io
import unittest
from contextlib import contextmanager
from unittest import mock

from src.publish import download as module
from src.publish.download import MAX_BYTES, download


def opening(body: bytes):
    """A stand-in for ``open_url`` that answers ``body`` and notes what it was asked."""
    asked = []

    @contextmanager
    def open_url(url, timeout, cancel=None):
        asked.append((url, timeout, cancel))
        yield io.BytesIO(body)

    return open_url, asked


class DownloadTests(unittest.TestCase):
    def test_an_https_address_gives_what_it_answers(self):
        opener, asked = opening(b"png")
        with mock.patch.object(module, "open_url", opener):
            self.assertEqual(download("HTTPS://x.example/t.png", 5), b"png")
        self.assertEqual(asked, [("HTTPS://x.example/t.png", 5, None)])

    def test_the_token_it_is_given_is_the_one_the_request_is_made_under(self):
        opener, asked = opening(b"png")
        token = object()
        with mock.patch.object(module, "open_url", opener):
            download("https://x.example/t.png", cancel=token)
        self.assertIs(asked[0][2], token)

    def test_an_address_that_is_not_https_is_refused_before_anything_is_opened(self):
        opener, asked = opening(b"png")
        with mock.patch.object(module, "open_url", opener):
            for url in ("http://x.example/t.png", "file:///c:/t.png", "", None):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    download(url)
        self.assertEqual(asked, [])

    def test_an_answer_of_the_most_allowed_is_given_and_a_byte_more_is_refused(self):
        with mock.patch.object(module, "open_url", opening(b"x" * MAX_BYTES)[0]):
            self.assertEqual(len(download("https://x.example/t.png")), MAX_BYTES)
        with mock.patch.object(module, "open_url", opening(b"x" * (MAX_BYTES + 1))[0]):
            with self.assertRaises(ValueError) as caught:
                download("https://x.example/t.png")
        self.assertIn("20 MB", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
