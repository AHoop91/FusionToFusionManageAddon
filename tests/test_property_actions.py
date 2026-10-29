"""Listing the hub's custom properties for field mapping. Run: python -m unittest discover tests"""

import unittest
from unittest import mock

from src.config.config_service import CompanyModeUnavailable
from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import property_actions
    from src.ui.actions.property_actions import register_property_actions
    from src.ui.message_bridge import MessageBridge

PROPERTIES = [{"name": "Supplier"}, {"name": "Colour"}]


class PropertyActionsTests(unittest.TestCase):
    def setUp(self):
        self.bridge = MessageBridge()
        self.pushed = []
        self.bridge.set_pusher(lambda action, text: self.pushed.append((action, text)))
        self.queued = []   # the reads, run by the test when it wants them to finish
        self.hub_name = mock.Mock(return_value="Hub One")
        self.service = mock.Mock()
        self.service.return_value.list_properties.return_value = PROPERTIES
        for patch in (mock.patch.object(property_actions, "FusionGraphQlClient"),
                      mock.patch.object(property_actions, "PropertyService", self.service)):
            patch.start()
            self.addCleanup(patch.stop)
        register_property_actions(self.bridge, self.hub_name, self.queued.append)

    def call(self, action):
        return self.bridge.dispatch(action, "")

    def finish_reads(self):
        while self.queued:
            self.queued.pop(0)()

    def test_a_request_is_pending_and_the_properties_are_pushed_when_read(self):
        reply = self.call("list_custom_properties")
        self.assertEqual((reply["ok"], reply["result"]["pending"], reply["result"]["properties"]), (True, True, []))
        self.finish_reads()
        self.assertEqual([action for action, _ in self.pushed], ["list_custom_properties_status"])
        self.assertIn('"properties": [{"name": "Supplier"}, {"name": "Colour"}]', self.pushed[0][1])
        self.service.return_value.list_properties.assert_called_once_with("Hub One")

    def test_the_status_gives_the_outcome_for_a_panel_that_missed_the_push(self):
        self.call("list_custom_properties")
        self.finish_reads()
        status = self.call("list_custom_properties_status")["result"]
        self.assertEqual((status["pending"], status["ok"], status["properties"]), (False, True, PROPERTIES))

    def test_asking_again_while_it_is_read_starts_no_second_read(self):
        self.call("list_custom_properties")
        self.call("list_custom_properties")
        self.assertEqual(len(self.queued), 1)

    def test_a_failed_read_is_told_with_why(self):
        self.service.return_value.list_properties.side_effect = RuntimeError("hub down")
        self.call("list_custom_properties")
        self.finish_reads()
        status = self.call("list_custom_properties_status")["result"]
        self.assertEqual((status["ok"], status["message"], status["properties"]), (False, "hub down", []))

    def test_company_mode_being_unavailable_is_told_in_the_reply(self):
        property_actions.FusionGraphQlClient.side_effect = CompanyModeUnavailable("no company mode")
        result = self.call("list_custom_properties")["result"]
        self.assertEqual((result["ok"], result["message"]), (False, "no company mode"))
        self.assertEqual(self.queued, [])

    def test_no_open_hub_is_told_in_the_reply_and_starts_nothing(self):
        self.hub_name.side_effect = RuntimeError("no hub")
        result = self.call("list_custom_properties")["result"]
        self.assertEqual((result["ok"], result["message"]), (False, "No active hub: no hub"))
        self.assertEqual(self.queued, [])
        self.assertFalse(self.call("list_custom_properties_status")["result"]["pending"])


if __name__ == "__main__":
    unittest.main()
