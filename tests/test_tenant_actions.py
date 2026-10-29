"""Finding the Fusion Manage tenant from the open design's linked item. Run: python -m unittest discover tests"""

import unittest
from unittest import mock

from tests.without_fusion import fusion_modules_stubbed

# The actions package imports Fusion's modules (for its dialogs), which only Fusion has.
with fusion_modules_stubbed():
    from src.ui.actions import tenant_actions
    from src.ui.actions.tenant_actions import NO_DESIGN, NOT_LINKED, register_tenant_actions
    from src.ui.message_bridge import MessageBridge


class TenantActionsTests(unittest.TestCase):
    def setUp(self):
        self.bridge = MessageBridge()
        self.pushed = []
        self.bridge.set_pusher(lambda action, text: self.pushed.append((action, text)))
        self.queued = []   # the reads, run by the test when it wants them to finish
        self.ref = mock.Mock(return_value=("m1", "t1"))
        self.read_section = mock.Mock(return_value={"component_id": "c1"})
        self.read_item = mock.Mock(return_value={"urn": "", "url": "https://acme.autodeskplm360.net/plm/item/1"})
        for patch in (mock.patch.object(tenant_actions, "FusionGraphQlClient"),
                      mock.patch.object(tenant_actions, "read_section", self.read_section),
                      mock.patch.object(tenant_actions, "read_manage_item", self.read_item)):
            patch.start()
            self.addCleanup(patch.stop)
        register_tenant_actions(self.bridge, self.ref, self.queued.append)

    def call(self, action):
        return self.bridge.dispatch(action, "")

    def finish_reads(self):
        while self.queued:
            self.queued.pop(0)()

    def test_a_request_is_pending_and_the_tenant_is_pushed_when_found(self):
        result = self.call("detect_tenant")["result"]
        self.assertEqual((result["pending"], result["tenant"]), (True, ""))
        self.finish_reads()
        self.assertEqual([action for action, _ in self.pushed], ["detect_tenant_status"])
        status = self.call("detect_tenant_status")["result"]
        self.assertEqual((status["pending"], status["ok"], status["tenant"], status["message"]), (False, True, "acme", ""))

    def test_the_item_is_looked_for_in_the_saved_version_of_the_open_design(self):
        self.call("detect_tenant")
        self.finish_reads()
        self.assertEqual(self.read_section.call_args[0][1:], ("summary", "m1", "t1"))
        self.assertEqual(self.read_item.call_args[0][1:], ({"component_id": "c1"}, "c1", "t1"))

    def test_the_tenant_may_come_from_the_urn_when_the_address_has_none(self):
        self.read_item.return_value = {"urn": "urn:adsk.plm:tenant.workspace.item:ACME.57.9", "url": ""}
        self.call("detect_tenant")
        self.finish_reads()
        self.assertEqual(self.call("detect_tenant_status")["result"]["tenant"], "acme")

    def test_a_design_with_no_linked_item_is_not_ok_and_says_so(self):
        self.read_item.return_value = {"urn": "", "url": ""}
        self.call("detect_tenant")
        self.finish_reads()
        status = self.call("detect_tenant_status")["result"]
        self.assertEqual((status["ok"], status["tenant"], status["message"]), (False, "", NOT_LINKED))

    def test_no_saved_design_is_told_in_the_reply_and_starts_nothing(self):
        self.ref.return_value = ("", "")
        result = self.call("detect_tenant")["result"]
        self.assertEqual((result["pending"], result["ok"], result["message"]), (False, False, NO_DESIGN))
        self.assertEqual(self.queued, [])
        self.assertEqual(self.call("detect_tenant_status")["result"]["message"], "")   # and it is not kept as the outcome

    def test_a_failed_read_is_told_with_why(self):
        self.read_section.side_effect = RuntimeError("Data Model down")
        self.call("detect_tenant")
        self.finish_reads()
        status = self.call("detect_tenant_status")["result"]
        self.assertEqual((status["ok"], status["tenant"], status["message"]), (False, "", "Data Model down"))

    def test_asking_again_while_it_is_read_starts_no_second_read(self):
        self.call("detect_tenant")
        self.call("detect_tenant")
        self.assertEqual(len(self.queued), 1)

    def test_before_any_request_the_status_is_blank(self):
        self.assertEqual(self.call("detect_tenant_status")["result"],
                         {"pending": False, "ok": False, "message": "", "tenant": ""})


if __name__ == "__main__":
    unittest.main()
