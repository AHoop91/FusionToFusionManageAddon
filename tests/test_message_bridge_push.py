"""Background work tells the panels its outcome through ``MessageBridge.push``, in the envelope of a reply, and never raises."""

import json
import unittest

from src.ui.message_bridge import MessageBridge


class PushTests(unittest.TestCase):
    def test_sends_the_reply_envelope_on_the_action_name(self):
        sent = []
        bridge = MessageBridge()
        bridge.set_pusher(lambda action, data: sent.append((action, json.loads(data))))
        bridge.push("get_hub_role", {"state": "admin"})
        self.assertEqual(sent, [("get_hub_role", {"ok": True, "result": {"state": "admin"}, "error": None})])

    def test_a_failure_can_be_pushed(self):
        sent = []
        bridge = MessageBridge()
        bridge.set_pusher(lambda action, data: sent.append(json.loads(data)))
        bridge.push("x", None, ok=False, error="boom")
        self.assertEqual(sent, [{"ok": False, "result": None, "error": "boom"}])

    def test_without_a_pusher_nothing_happens(self):
        MessageBridge().push("x", {})

    def test_a_pusher_that_fails_does_not_raise(self):
        def broken(_action, _data):
            raise RuntimeError("no panel")
        bridge = MessageBridge()
        bridge.set_pusher(broken)
        bridge.push("x", {})

    def test_the_pusher_can_be_taken_away(self):
        sent = []
        bridge = MessageBridge()
        bridge.set_pusher(lambda action, data: sent.append(action))
        bridge.set_pusher(None)
        bridge.push("x", {})
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
