"""Reading a workspace's sections: which section holds each field, and what is read to know it."""

import itertools
import unittest

from src.fm.client import FmApiError
from src.fm.sections import SectionService, parse_sections

FIELD = "/api/v3/workspaces/1/views/1/fields/"
_workspace = itertools.count(1)   # the service caches by tenant and workspace: each test uses its own


def ref(fid):
    return {"link": FIELD + fid}


class Client:
    tenant = "acme"

    def __init__(self):
        self.answers, self.paths = {}, []

    def get_json(self, path, accept="application/json"):
        self.paths.append(path)
        return self.answers[path]


def service():
    client = Client()
    return SectionService(client), client, str(next(_workspace) + 1000)


class ParseTests(unittest.TestCase):
    def test_fields_and_the_fields_in_matrices_belong_to_their_section(self):
        data = [{"__self__": "/s/10", "fields": [ref("A")], "matrices": [{"fields": [[ref("B"), None], [ref("C")]]}]}]
        self.assertEqual(parse_sections(data), {"A": "/s/10", "B": "/s/10", "C": "/s/10"})

    def test_a_field_two_sections_name_belongs_to_the_first(self):
        data = [{"link": "/s/1", "fields": [ref("A")]}, {"link": "/s/2", "fields": [ref("A"), ref("B")]}]
        self.assertEqual(parse_sections(data), {"A": "/s/1", "B": "/s/2"})

    def test_a_section_with_no_link_and_anything_odd_is_left_out(self):
        data = [{"fields": [ref("A")]}, "x", {"link": "/s/3", "fields": "x", "matrices": ["x", {"fields": "x"}]}, {"link": "/s/4", "fields": [5, ref("D")]}]
        self.assertEqual(parse_sections(data), {"D": "/s/4"})
        for data in (None, {}, "x"):
            self.assertEqual(parse_sections(data), {})


class ServiceTests(unittest.TestCase):
    def test_a_list_of_links_is_followed_and_each_section_read(self):
        svc, client, ws = service()
        client.answers = {f"/api/v3/workspaces/{ws}/sections": {"sections": [{"link": "/s/1"}, {"link": "/s/2"}]},
                          "/s/1": {"link": "/s/1", "fields": [ref("A")]}, "/s/2": {"link": "/s/2", "fields": [ref("B")]}}
        self.assertEqual(svc.field_sections(ws), {"A": "/s/1", "B": "/s/2"})
        self.assertEqual(sorted(svc.layouts(ws)), ["1", "2"])

    def test_a_section_that_carries_its_fields_is_not_read_again(self):
        svc, client, ws = service()
        client.answers = {f"/api/v3/workspaces/{ws}/sections": [{"link": "/s/1", "fields": [ref("A")]}]}
        svc.field_sections(ws)
        self.assertEqual(client.paths, [f"/api/v3/workspaces/{ws}/sections"])

    def test_a_workspace_is_read_once_and_then_kept(self):
        svc, client, ws = service()
        client.answers = {f"/api/v3/workspaces/{ws}/sections": [{"link": "/s/1", "fields": [ref("A")]}]}
        svc.field_sections(ws)
        svc.field_sections(ws)
        svc.layouts(ws)
        self.assertEqual(len(client.paths), 1)

    def test_a_section_that_answers_with_junk_is_left_out_instead_of_breaking_the_rest(self):
        svc, client, ws = service()
        client.answers = {f"/api/v3/workspaces/{ws}/sections": [{"link": "/s/1"}, {"link": "/s/2"}], "/s/1": "oops", "/s/2": {"link": "/s/2", "fields": [ref("B")]}}
        self.assertEqual(svc.field_sections(ws), {"B": "/s/2"})

    def test_no_fields_at_all_is_an_error_that_says_so(self):
        svc, client, ws = service()
        client.answers = {f"/api/v3/workspaces/{ws}/sections": [{"link": "/s/1", "fields": []}]}
        with self.assertRaises(FmApiError) as raised:
            svc.field_sections(ws)
        self.assertIn("1 section(s) came back", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
