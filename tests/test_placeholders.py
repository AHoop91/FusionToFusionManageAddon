"""The markers in the request files: written, found and filled in."""

import unittest

from src.publish.placeholders import Unresolved, key_of, marker, markers, resolve


class MarkerTests(unittest.TestCase):
    def test_a_marker_is_its_kind_and_argument_and_a_kind_alone_has_no_colon(self):
        self.assertEqual(marker("item", "PN-1"), "{{item:PN-1}}")
        self.assertEqual(marker("tenant"), "{{tenant}}")
        self.assertEqual(marker("edge", "A>B@1"), "{{edge:A>B@1}}")

    def test_a_marker_that_could_not_be_read_back_is_refused(self):
        for kind, argument in (("Item", "A"), ("item2", "A"), ("", "A"), ("item", "A{B"), ("item", "A}B"), ("item", "{{item:X}}")):
            with self.subTest(kind=kind, argument=argument), self.assertRaises(ValueError):
                marker(kind, argument)

    def test_what_is_written_is_found_with_the_same_key(self):
        text = marker("item", "PN-1") + marker("version", "PN-1") + marker("edge", "A>B@1") + marker("tenant")
        self.assertEqual(markers(text), {key_of("item", "PN-1"), key_of("version", "PN-1"), ("edge", "A>B@1"), ("tenant", "")})

    def test_an_item_number_is_a_key_without_its_case_or_spaces_but_an_edge_is_exact(self):
        self.assertEqual(key_of("item", " Pn-1 "), ("item", "pn-1"))
        self.assertEqual(key_of("version", "PN-1"), ("version", "pn-1"))
        self.assertEqual(key_of("edge", "A>B@1"), ("edge", "A>B@1"))


class FindTests(unittest.TestCase):
    def test_markers_are_found_in_urls_and_nested_bodies(self):
        request = {"url": "/items/{{item:A}}/bom-items", "body": {"item": {"link": "/items/{{item:B}}"}, "list": ["{{tenant}}"]}}
        self.assertEqual(markers(request), {key_of("item", "A"), key_of("item", "B"), ("tenant", "")})

    def test_what_is_not_text_or_not_a_marker_is_not_found(self):
        self.assertEqual(markers({"n": 1, "ok": True, "none": None, "text": "{item:A} {{Item:A}} {{item:A", "list": [2, 3.5]}), set())
        self.assertEqual(markers(None), set())

    def test_a_marker_in_the_name_of_a_field_is_not_one(self):
        self.assertEqual(markers({"{{item:A}}": "x"}), set())

    def test_several_markers_in_one_text_are_all_found(self):
        self.assertEqual(markers("/a/{{item:A}}/b/{{item:B}}/{{item:a}}"), {key_of("item", "A"), key_of("item", "B")})


class ResolveTests(unittest.TestCase):
    def test_resolve_fills_every_marker_and_item_numbers_ignore_case(self):
        request = {"url": "/items/{{item:PN-1}}", "body": ["{{version:pn-1}}"]}
        values = {key_of("item", "pn-1"): "7", key_of("version", "PN-1"): "[REV:w]"}
        self.assertEqual(resolve(request, values), {"url": "/items/7", "body": ["[REV:w]"]})

    def test_resolve_names_what_is_missing(self):
        with self.assertRaises(Unresolved) as caught:
            resolve({"url": "/items/{{item:A}}/{{edge:A>B@1}}"}, {})
        self.assertEqual(caught.exception.keys, [("edge", "A>B@1"), ("item", "a")])
        self.assertEqual(str(caught.exception), "No value for {{edge:A>B@1}}, {{item:a}}")

    def test_a_request_is_not_changed_and_what_is_not_text_is_kept(self):
        request = {"url": "/items/{{item:A}}", "body": {"n": 1, "ok": True, "none": None, "list": ["{{item:A}}", 2]}}
        before = repr(request)
        resolved = resolve(request, {key_of("item", "A"): "7"})
        self.assertEqual(repr(request), before)
        self.assertEqual(resolved, {"url": "/items/7", "body": {"n": 1, "ok": True, "none": None, "list": ["7", 2]}})

    def test_a_value_is_put_in_as_it_is_and_never_read_for_markers_or_escapes(self):
        values = {key_of("item", "A"): r"\1{{item:B}}\g<0>"}
        self.assertEqual(resolve("/{{item:A}}/", values), r"/\1{{item:B}}\g<0>/")

    def test_a_request_with_no_markers_comes_back_equal(self):
        request = {"method": "DELETE", "url": "/x", "body": None}
        self.assertEqual(resolve(request, {}), request)


if __name__ == "__main__":
    unittest.main()
