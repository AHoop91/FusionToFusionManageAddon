import logging
import unittest

from src.core.logging_setup import MASK, RedactingFormatter, redact


class RedactTests(unittest.TestCase):
    def test_signed_link_loses_its_token_and_signature_but_keeps_the_rest(self):
        text = '"url" : "https://s3.example.com/a/b?X-Amz-Security-Token=Fwo%2Fabc&X-Amz-Signature=dead&other=1"'
        out = redact(text)
        self.assertNotIn("Fwo", out)
        self.assertNotIn("dead", out)
        self.assertIn(f"X-Amz-Signature={MASK}", out)
        self.assertIn("https://s3.example.com/a/b", out)

    def test_a_link_cut_short_by_a_clip_is_masked_to_its_end(self):
        self.assertEqual(redact("https://s3/x?X-Amz-Security-Token=FwoGZXIvYXdzEOD%2F%2F"), f"https://s3/x?X-Amz-Security-Token={MASK}")

    def test_bearer_header_and_json_tokens(self):
        self.assertEqual(redact("Authorization: Bearer abc.DEF-1_x"), f"Authorization: Bearer {MASK}")
        out = redact('{"access_token": "eyJabc", "refresh_token":"r1", "expires_in": 3600}')
        self.assertNotIn("eyJabc", out)
        self.assertNotIn('"r1"', out)
        self.assertIn('"expires_in": 3600', out)

    def test_basic_auth_cookies_and_bare_jwts(self):
        self.assertEqual(redact("Authorization: Basic dXNlcjpwYXNz"), f"Authorization: Basic {MASK}")
        self.assertEqual(redact("Set-Cookie: sid=abc123; Path=/"), f"Set-Cookie: {MASK}")
        out = redact("user said eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl ok")
        self.assertEqual(out, f"user said {MASK} ok")
        self.assertEqual(redact("https://x/y?X-Goog-Signature=abcd&AWSAccessKeyId=AKIA123"), f"https://x/y?X-Goog-Signature={MASK}&AWSAccessKeyId={MASK}")

    def test_sign_in_code_only_in_a_query(self):
        self.assertEqual(redact("GET /callback?code=abc123&state=xyz"), f"GET /callback?code={MASK}&state=xyz")
        self.assertEqual(redact("status code=404"), "status code=404")

    def test_form_secret(self):
        self.assertEqual(redact("client_secret=s3cr3t&grant_type=x"), f"client_secret={MASK}&grant_type=x")

    def test_ordinary_lines_are_untouched(self):
        for line in ("GET /api/v3/items -> 200 (token 0.12s, first byte 0.3s)", "Part number PN-000701 is item number PN-000701"):
            self.assertEqual(redact(line), line)

    def test_formatter_masks_the_message_and_the_traceback(self):
        try:
            raise ValueError("failed https://s3/x?X-Amz-Signature=sigvalue")
        except ValueError:
            import sys
            record = logging.LogRecord("t", logging.ERROR, __file__, 1, "sent %s", ("Bearer tokenvalue",), sys.exc_info())
        out = RedactingFormatter("%(message)s").format(record)
        self.assertNotIn("tokenvalue", out)
        self.assertNotIn("sigvalue", out)


if __name__ == "__main__":
    unittest.main()
