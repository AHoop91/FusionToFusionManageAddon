"""A request from a panel is run by its registered handler, which is given an object; whatever else arrives is refused, never raised."""

import unittest

from src.ui.message_bridge import MessageBridge


def bridge_with_echo():
    bridge = MessageBridge()
    bridge.register("echo", lambda payload: payload)
    return bridge


class DispatchTests(unittest.TestCase):
    def test_the_handler_gets_the_object_and_its_answer_is_the_result(self):
        self.assertEqual(bridge_with_echo().dispatch("echo", '{"a": 1}'), {"ok": True, "result": {"a": 1}, "error": None})

    def test_no_data_is_an_empty_object(self):
        self.assertEqual(bridge_with_echo().dispatch("echo", "")["result"], {})

    def test_data_that_is_not_an_object_is_refused(self):
        for raw in ("[]", "[1, 2]", '"x"', "1", "null", "true"):
            with self.subTest(raw=raw):
                answer = bridge_with_echo().dispatch("echo", raw)
                self.assertEqual((answer["ok"], answer["result"]), (False, None))
                self.assertIn("JSON object", answer["error"])

    def test_data_that_is_not_json_is_refused(self):
        answer = bridge_with_echo().dispatch("echo", "{")
        self.assertFalse(answer["ok"])

    def test_a_handler_that_fails_is_reported_not_raised(self):
        bridge = MessageBridge()
        bridge.register("boom", lambda payload: 1 / 0)
        answer = bridge.dispatch("boom", "{}")
        self.assertEqual((answer["ok"], answer["result"]), (False, None))

    def test_an_unknown_action_is_refused(self):
        answer = MessageBridge().dispatch("nothing", "{}")
        self.assertEqual((answer["ok"], answer["error"]), (False, "Unknown action: nothing"))

    def test_an_action_cannot_be_registered_twice(self):
        with self.assertRaises(ValueError):
            bridge_with_echo().register("echo", lambda payload: payload)


if __name__ == "__main__":
    unittest.main()
