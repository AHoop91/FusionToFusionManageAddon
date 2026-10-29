"""``as_dict``: an object stays as it is, anything else reads as an empty object."""

import unittest

from src.core.shapes import as_dict, as_list, dict_rows, dig, rows_in, whole


class AsDictTests(unittest.TestCase):
    def test_an_object_is_given_as_it_is(self):
        value = {"a": 1}
        self.assertIs(as_dict(value), value)

    def test_anything_else_is_an_empty_object(self):
        for value in (None, "x", 1, [], [{"a": 1}], True):
            with self.subTest(value=value):
                self.assertEqual(as_dict(value), {})


class ListTests(unittest.TestCase):
    def test_a_list_is_given_as_it_is(self):
        value = [1, "x"]
        self.assertIs(as_list(value), value)

    def test_anything_else_is_an_empty_list(self):
        for value in (None, "x", 1, {}, {"a": 1}, (1, 2)):
            with self.subTest(value=value):
                self.assertEqual(as_list(value), [])

    def test_only_the_objects_of_a_list_are_rows(self):
        self.assertEqual(dict_rows([{"a": 1}, None, "x", [], {"b": 2}]), [{"a": 1}, {"b": 2}])
        for value in (None, "x", {"a": 1}):
            with self.subTest(value=value):
                self.assertEqual(dict_rows(value), [])


class RowsInTests(unittest.TestCase):
    def test_a_list_or_an_object_holding_it(self):
        rows = [{"a": 1}, "x", {"b": 2}]
        self.assertEqual(rows_in(rows, "fields"), [{"a": 1}, {"b": 2}])
        self.assertEqual(rows_in({"fields": rows}, "fields"), [{"a": 1}, {"b": 2}])

    def test_anything_else_is_empty(self):
        for value in (None, "x", {}, {"fields": "x"}, {"other": [{"a": 1}]}):
            with self.subTest(value=value):
                self.assertEqual(rows_in(value, "fields"), [])


class DigTests(unittest.TestCase):
    def test_a_path_is_followed(self):
        self.assertEqual(dig({"a": {"b": {"c": 1}}}, "a", "b", "c"), 1)
        self.assertEqual(dig({"a": {"b": [1]}}, "a", "b"), [1])

    def test_no_path_is_the_value_itself(self):
        self.assertEqual(dig({"a": 1}), {"a": 1})

    def test_a_missing_or_wrongly_shaped_step_gives_none(self):
        for value in ({}, None, "x", [], {"a": None}, {"a": "x"}, {"a": [{"b": 1}]}, {"a": {"b": None}}):
            with self.subTest(value=value):
                self.assertIsNone(dig(value, "a", "b"))


class WholeTests(unittest.TestCase):
    def test_a_number_or_numeric_text_is_a_whole_number(self):
        self.assertEqual((whole(3), whole("12"), whole(4.9)), (3, 12, 4))

    def test_anything_else_is_zero(self):
        for value in (None, "", "abc", [], {}, "1.5"):
            with self.subTest(value=value):
                self.assertEqual(whole(value), 0)
