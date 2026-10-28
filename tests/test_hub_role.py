"""The user's role in a hub: only a clear ADMIN is an admin, a refusal is a plain "not an admin", and a failure says nothing."""

import unittest

from src.fusion_mfg.fusion_graphql_client import MfgApiError
from src.fusion_mfg.hub_role import ACCESS_DENIED, NOT_ADMIN, UNKNOWN, parse_hub_role, read_hub_role


def members(*rows):
    return {"hub": {"members": {"results": [{"user": {"id": "u", "email": email}, "role": role, "status": "ACTIVE"} for email, role in rows]}}}


class FakeClient:
    def __init__(self, data=None, error=None):
        self.data, self.error = data, error

    def query(self, text, variables=None, label=""):
        if self.error:
            raise self.error
        return self.data


class ParseTests(unittest.TestCase):
    def test_admin(self):
        role = parse_hub_role(members(("me@x.com", "ADMIN")), "me@x.com")
        self.assertEqual((role.admin, role.known, role.role), (True, True, "ADMIN"))

    def test_another_role_is_not_admin(self):
        role = parse_hub_role(members(("me@x.com", "MEMBER")), "me@x.com")
        self.assertEqual((role.admin, role.known, role.role), (False, True, "MEMBER"))

    def test_only_the_row_of_exactly_this_email_counts(self):
        data = members(("someone.else@x.com", "ADMIN"), ("ME@x.com", "MEMBER"))
        role = parse_hub_role(data, "me@x.com")
        self.assertEqual((role.admin, role.role), (False, "MEMBER"))

    def test_no_matching_row_says_nothing(self):
        self.assertEqual(parse_hub_role(members(("someone.else@x.com", "ADMIN")), "me@x.com"), UNKNOWN)
        self.assertEqual(parse_hub_role({"hub": None}, "me@x.com"), UNKNOWN)

    def test_two_matching_rows_say_nothing(self):
        self.assertEqual(parse_hub_role(members(("me@x.com", "ADMIN"), ("me@x.com", "ADMIN")), "me@x.com"), UNKNOWN)


class ReadTests(unittest.TestCase):
    def test_a_refusal_is_an_answer(self):
        client = FakeClient(error=MfgApiError("Access Denied.", code=ACCESS_DENIED))
        self.assertEqual(read_hub_role(client, "hub", "me@x.com"), NOT_ADMIN)

    def test_other_failures_say_nothing(self):
        self.assertEqual(read_hub_role(FakeClient(error=MfgApiError("busy", transient=True)), "hub", "me@x.com"), UNKNOWN)

    def test_nothing_is_asked_without_a_hub_or_an_email(self):
        client = FakeClient(error=AssertionError("must not be asked"))
        self.assertEqual(read_hub_role(client, "", "me@x.com"), UNKNOWN)
        self.assertEqual(read_hub_role(client, "hub", "  "), UNKNOWN)

    def test_an_admin_is_read_through(self):
        self.assertTrue(read_hub_role(FakeClient(members(("me@x.com", "ADMIN"))), "hub", "me@x.com").admin)


if __name__ == "__main__":
    unittest.main()
