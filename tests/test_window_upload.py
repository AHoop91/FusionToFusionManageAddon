"""How an upload is started, kept, ended and told: what the Export window reads, what a failure leaves behind, and what the files of an item make of a preview."""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from src.config.hub_context import capture_context
from src.config.models import ConnectionSettings
from src.config.workspace_models import ITEMS_KIND
from tests.hub_fixtures import config_of, items_workspace


CONTEXT = capture_context(config_of())


class _Stub(types.ModuleType):
    """A stand-in for Fusion's ``adsk`` modules: any name in it is an empty class."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(name, (), {"__init__": lambda self, *a, **k: None})
        setattr(self, name, value)
        return value


_NAMES = ("adsk", "adsk.core", "adsk.fusion", "adsk.drawing")
_saved = {}
AttachmentUpload = UploadJob = None


def setUpModule():
    global AttachmentUpload, UploadJob
    for name in _NAMES:
        _saved[name] = sys.modules.get(name)
        sys.modules[name] = _Stub(name)
    for sub in ("core", "fusion", "drawing"):
        setattr(sys.modules["adsk"], sub, sys.modules["adsk." + sub])
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]   # imported again below, against the stand-ins
    from src.ui import attachment_upload
    AttachmentUpload, UploadJob = attachment_upload.AttachmentUpload, attachment_upload.UploadJob


def tearDownModule():
    for name in [m for m in sys.modules if m.startswith("src.ui")]:
        del sys.modules[name]   # so no other test meets a module built on the stand-ins
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class _Ui:
    def __init__(self):
        self.messages = []

    def messageBox(self, text, *_args):
        self.messages.append(text)


class _Tasks:
    def post(self, task):
        task()


class _Host:
    visible = False

    def send(self, *_args):
        pass


class UploadEndTests(unittest.TestCase):
    def setUp(self):
        self.ui = _Ui()
        self.reloads = []
        self.upload = AttachmentUpload(self.ui, _Tasks(), _Host(), _Host(), config_of(), None, lambda: self.reloads.append(1))
        self.job = UploadJob("Uploading STEP File", "STEP file", ".step", ("Find item", "Create STEP", "Upload"), lambda *a: None, lambda *a: True)

    def test_one_upload_at_a_time(self):
        self.assertIsNotNone(self.upload.begin_in_window(self.job))
        self.assertIsNone(self.upload.begin_in_window(self.job))
        self.assertTrue(self.upload.status()["active"])

    def test_a_failure_the_window_follows_is_kept_for_it_and_shows_no_message_box(self):
        self.upload.begin_in_window(self.job)
        self.upload._fail("Could not create PN-1.step")
        self.assertEqual(self.upload.status(), {"active": False, "result": {"ok": False, "message": "Could not create PN-1.step"}})
        self.assertEqual(self.ui.messages, [])

    def test_a_success_the_window_follows_says_where_the_file_went(self):
        self.upload.begin_in_window(self.job)
        self.upload._done("PN-1.step", "new", "component")
        result = self.upload.status()["result"]
        self.assertTrue(result["ok"])
        self.assertIn("PN-1.step was attached to the component", result["message"])
        self.assertEqual((self.ui.messages, self.reloads), ([], [1]))

    def test_the_next_upload_does_not_show_the_last_result(self):
        self.upload.begin_in_window(self.job)
        self.upload._fail("no")
        self.assertIsNotNone(self.upload.begin_in_window(self.job))
        self.assertNotIn("result", self.upload.status())

    def test_an_upload_started_elsewhere_still_ends_in_a_message_box(self):
        self.assertTrue(self.upload._begin(self.job, 0))
        self.upload._fail("no")
        self.assertEqual(self.upload.status(), {"active": False})
        self.assertEqual(self.ui.messages, ["no"])


class UploadAnnounceTests(unittest.TestCase):
    def setUp(self):
        self.told = []
        self.upload = AttachmentUpload(_Ui(), _Tasks(), _Host(), _Host(), config_of(), None, lambda: None, self.told.append)
        self.job = UploadJob("Uploading STEP File", "STEP file", ".step", ("Find item", "Create STEP", "Upload"), lambda *a: None, lambda *a: True)

    def test_each_change_is_pushed_and_a_repeat_is_not(self):
        self.upload.begin_in_window(self.job)
        self.upload._stage(self.job, 2, 10)
        self.upload._stage(self.job, 2, 10)
        self.upload._stage(self.job, 2, 40)
        self.assertEqual([(t["step"], t["percent"]) for t in self.told], [(0, None), (2, 10), (2, 40)])

    def test_the_end_is_pushed_with_its_result(self):
        self.upload.begin_in_window(self.job)
        self.upload._fail("no")
        self.assertEqual(self.told[-1], {"active": False, "result": {"ok": False, "message": "no"}})

    def test_an_end_with_no_result_is_pushed_too(self):
        self.upload._begin(self.job, 0)
        self.upload._end()
        self.assertEqual(self.told[-1], {"active": False})


class _Window:
    def __init__(self, error=None):
        self.error, self.shown, self.disposed = error, 0, 0

    def show(self):
        self.shown += 1
        if self.error:
            raise self.error

    def dispose(self):
        self.disposed += 1


def _job(make=lambda *a: None):
    return UploadJob("Uploading STEP File", "STEP file", ".step", ("Find item", "Create STEP", "Upload"), make, lambda *a: True)


class MakeTests(unittest.TestCase):
    """``_make`` writes the file on Fusion's thread and hands it to the upload; anything that goes wrong ends the upload with a message."""

    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        from src.ui import attachment_upload
        for target, value in (("temp_root", lambda: self.root.name), ("catch_up", lambda: None)):
            patcher = mock.patch.object(attachment_upload, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(AttachmentUpload, "_let_page_draw")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ui = _Ui()
        self.upload = AttachmentUpload(self.ui, _Tasks(), _Host(), _Window(), config_of(), None, lambda: None)
        self.subject = types.SimpleNamespace(item_number="PN/1")

    def test_the_file_is_read_then_its_folder_is_removed_and_the_upload_goes_on_at_the_send_stage(self):
        seen = []

        def make(path, _subject, progress):
            with open(path, "wb") as handle:
                handle.write(b"step data")
            seen.append(os.path.basename(path))
            progress(50)

        self.upload._begin(_job(), 1)
        with mock.patch("threading.Thread") as thread:
            self.upload._make(_job(make), CONTEXT, "7", "9", self.subject)
        self.assertEqual(seen, ["PN_1.step"])   # the number is made safe to be a file name
        sent = thread.call_args.kwargs["args"]
        self.assertEqual((sent[1], sent[2:4], sent[4], sent[5]), (CONTEXT, ("7", "9"), "PN_1.step", b"step data"))
        self.assertEqual(os.listdir(self.root.name), [])
        self.assertEqual((self.upload.status()["step"], self.upload.status()["percent"]), (2, 0))

    def test_a_file_that_cannot_be_made_ends_the_upload_with_a_message_and_leaves_no_folder(self):
        def make(path, *_rest):
            raise RuntimeError("no geometry")

        self.upload._begin(_job(), 1)
        self.upload._make(_job(make), CONTEXT, "7", "9", self.subject)
        self.assertEqual(self.upload.status(), {"active": False})
        self.assertEqual(self.ui.messages, ["Could not create PN_1.step:\nno geometry"])
        self.assertEqual(os.listdir(self.root.name), [])

    def test_a_file_that_comes_out_empty_is_not_uploaded(self):
        def make(path, *_rest):
            open(path, "wb").close()

        self.upload._begin(_job(), 1)
        with mock.patch("threading.Thread") as thread:
            self.upload._make(_job(make), CONTEXT, "7", "9", self.subject)
        thread.assert_not_called()
        self.assertEqual(self.upload.status(), {"active": False})
        self.assertEqual(self.ui.messages, ["Could not create PN_1.step:\nThe STEP file came out empty."])

    def test_a_folder_that_cannot_be_made_ends_the_upload_too(self):
        self.upload._begin(_job(), 1)
        with mock.patch("os.makedirs", side_effect=PermissionError("denied")):
            self.upload._make(_job(), CONTEXT, "7", "9", self.subject)
        self.assertEqual(self.upload.status(), {"active": False})   # not left under way, which would refuse every later upload
        self.assertEqual(len(self.ui.messages), 1)
        self.assertIn("denied", self.ui.messages[0])

    def test_the_window_that_cannot_be_shown_does_not_leave_the_upload_under_way(self):
        window = _Window(RuntimeError("no window"))
        upload = AttachmentUpload(self.ui, _Tasks(), _Host(), window, config_of(), None, lambda: None)
        with mock.patch("threading.Thread") as thread:
            upload.from_number(_job(), self.subject)
        self.assertEqual(upload.status(), {"active": False})
        self.assertEqual(window.disposed, 1)
        self.assertIn("no window", self.ui.messages[0])
        thread.assert_not_called()
        self.assertTrue(upload._begin(_job(), 0))

    def test_a_second_upload_from_the_menu_says_one_is_under_way(self):
        self.upload._begin(_job(), 0)
        window = self.upload._window
        self.upload.from_number(_job(), self.subject)
        self.assertEqual(self.ui.messages, ["A file is already being uploaded."])
        self.assertEqual(window.shown, 0)

    def test_a_late_report_of_an_upload_that_ended_is_dropped(self):
        told = []
        upload = AttachmentUpload(self.ui, _Tasks(), _Host(), _Window(), config_of(), None, lambda: None, told.append)
        upload._begin(_job(), 1)
        upload._end()
        upload._stage(_job(), 2, 80)
        self.assertEqual(upload.status(), {"active": False})
        self.assertEqual(told[-1], {"active": False})


class FindItemTests(unittest.TestCase):
    def setUp(self):
        from src.ui import attachment_upload
        self.module = attachment_upload
        self.upload = AttachmentUpload(_Ui(), _Tasks(), _Host(), _Window(), config_of(), None, lambda: None)
        self.addCleanup(mock.patch.stopall)

    def _search(self, hits):
        service = mock.patch.object(self.module, "ItemService").start()
        service.return_value.search.return_value = hits
        mock.patch.object(self.module, "FmClient").start()
        return service

    def test_an_items_workspace_that_is_not_set_up_says_so(self):
        with self.assertRaisesRegex(ValueError, "not set.*Complete it in Preferences"):
            self.upload._find_item("PN-1", capture_context(config_of(workspace="")))

    def test_no_item_for_the_number_is_said(self):
        self._search([])
        with self.assertRaisesRegex(LookupError, "No item exists for PN-1"):
            self.upload._find_item("PN-1", CONTEXT)

    def test_one_hit_is_the_item(self):
        service = self._search([{"id": "9", "descriptor": "PN-1 - Bolt"}])
        self.assertEqual(self.upload._find_item("PN-1", CONTEXT), ("242", "9"))
        self.assertEqual(service.call_args.args[1], self.module.WORKING)   # a released version cannot have files attached

    def test_the_item_is_looked_for_under_the_context_not_the_settings_now_active(self):
        client = mock.patch.object(self.module, "FmClient").start()
        mock.patch.object(self.module, "ItemService").start().return_value.search.return_value = [{"id": "9", "descriptor": "PN-1 - Bolt"}]
        self.upload._config = config_of(tenant="other", workspace="999", hub="hub2")   # another hub is active when the worker gets to it
        self.assertEqual(self.upload._find_item("PN-1", CONTEXT), ("242", "9"))
        self.assertEqual(client.call_args.args[0].tenant, "acme")

    def test_several_that_match_are_not_guessed_between(self):
        self._search([{"id": "9", "descriptor": "PN-1 - Bolt"}, {"id": "10", "descriptor": "PN-1 - Nut"}])
        with self.assertRaisesRegex(LookupError, "2 Fusion Manage items match PN-1"):
            self.upload._find_item("PN-1", CONTEXT)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        from src.ui import attachment_upload
        self.module = attachment_upload
        self.upload = AttachmentUpload(_Ui(), _Tasks(), _Host(), _Window(), config_of(), None, lambda: None)
        for name in ("FmClient", "AttachmentService"):
            mock.patch.object(attachment_upload, name).start()
        self.addCleanup(mock.patch.stopall)
        self.files = attachment_upload.AttachmentService.return_value.files

    def _preview(self, destination="item"):
        with mock.patch.object(self.upload, "_find_item", return_value=("242", "9")), \
                mock.patch.object(self.upload, "_find_component", return_value=("176", "5")) as component:
            self.component = component
            return self.upload.preview(destination, "PN-1", "PN-1.step", {"saved": 1}, CONTEXT)

    def test_a_file_not_there_yet_would_be_attached_as_new(self):
        self.files.return_value = [{"name": "other.pdf", "version": 1, "updated": "u", "user": "x", "size": 3}]
        self.assertEqual(self._preview(), {"state": "ok", "name": "PN-1.step", "existing": None})

    def test_a_file_there_would_get_a_new_version_and_says_how_recent_it_is(self):
        self.files.return_value = [{"name": "PN-1.step", "version": 2, "updated": "u", "user": "x", "size": 3}]
        with mock.patch.object(self.module, "compare", return_value={"state": "older"}):
            answer = self._preview()
        self.assertEqual(answer["existing"], {"version": 2, "updated": "u", "user": "x", "size": 3, "freshness": {"state": "older"}})

    def test_a_component_is_found_in_the_components_workspace(self):
        self.files.return_value = []
        self._preview("component")
        self.component.assert_called_once()

    def test_what_cannot_be_read_is_unavailable_with_the_reason(self):
        self.files.side_effect = RuntimeError("504")
        self.assertEqual(self._preview(), {"state": "unavailable", "message": "504"})

    def test_a_cancelled_look_is_not_answered(self):
        from src.core.cancel import Cancelled
        self.files.side_effect = Cancelled()
        with self.assertRaises(Cancelled):
            self._preview()


class _Queue:
    """Tasks that wait until ``run`` is called, as on Fusion's thread."""

    def __init__(self):
        self.tasks = []

    def post(self, task):
        self.tasks.append(task)

    def run(self):
        tasks, self.tasks = self.tasks, []
        for task in tasks:
            task()


class ContextTests(unittest.TestCase):
    """An upload is made under the hub, tenant and workspace active when it was asked for."""

    def setUp(self):
        self.ui, self.tasks = _Ui(), _Queue()
        self.config = config_of()
        self.upload = AttachmentUpload(self.ui, self.tasks, _Host(), _Window(), self.config, None, lambda: None)
        self.subject = types.SimpleNamespace(item_number="PN-1")

    def _change_hub(self):
        self.config.hub_id = "hub2"
        self.config.effective_settings.return_value = ConnectionSettings(client_id="c", tenant="other")
        self.config.config.workspaces = {ITEMS_KIND: items_workspace("999")}

    def test_a_number_upload_finds_and_makes_under_the_context_taken_when_it_was_asked_for(self):
        with mock.patch("threading.Thread") as thread:
            self.upload.from_number(_job(), self.subject)
        self._change_hub()   # before the worker thread has started
        context = thread.call_args.kwargs["args"][1]
        self.assertEqual((context.hub_id, context.tenant, context.cfg.workspace_id), ("hub1", "acme", "242"))

    def test_a_panel_upload_makes_under_the_context_taken_when_it_was_asked_for(self):
        job = _job()
        with mock.patch.object(self.upload, "_make") as make:
            self.upload.from_panel(job, "7", "9", self.subject)
            self._change_hub()   # before the UI thread gets to the file
            self.tasks.run()
        context = make.call_args.args[1]
        self.assertEqual((context.hub_id, context.tenant, context.cfg.workspace_id), ("hub1", "acme", "242"))

    def test_the_export_window_is_given_the_context_to_go_on_with(self):
        context = self.upload.begin_in_window(_job())
        self._change_hub()
        with mock.patch("threading.Thread") as thread:
            self.upload.continue_in_window(_job(), context, self.subject, "item")
        self.assertEqual(thread.call_args.kwargs["args"][1].tenant, "acme")

    def test_settings_that_cannot_be_read_are_told_to_the_user_and_nothing_starts(self):
        self.config.effective_settings.side_effect = RuntimeError("unreadable")
        with mock.patch("threading.Thread") as thread:
            self.upload.from_number(_job(), self.subject)
        self.assertIn("unreadable", self.ui.messages[0])
        self.assertEqual(self.upload.status(), {"active": False})
        thread.assert_not_called()
        with self.assertRaises(RuntimeError):
            self.upload.begin_in_window(_job())
        self.assertEqual(self.upload.status(), {"active": False})   # not left under way, which would refuse every later upload


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.ui, self.tasks, self.window = _Ui(), _Queue(), _Window()
        self.upload = AttachmentUpload(self.ui, self.tasks, _Host(), self.window, config_of(), None, lambda: None)
        self.subject = types.SimpleNamespace(item_number="PN-1")

    def _from_number(self):
        with mock.patch("threading.Thread"):
            self.upload.from_number(_job(), self.subject)

    def test_the_window_closes_when_the_upload_ends(self):
        self._from_number()
        self.assertEqual(self.window.shown, 1)
        self.upload._fail("no")
        self.tasks.run()
        self.assertEqual(self.window.disposed, 1)

    def test_a_window_the_next_upload_is_showing_is_not_closed_by_the_end_of_the_last(self):
        self._from_number()
        self.upload._fail("no")   # the close waits in the queue
        self._from_number()       # the user starts another before the queue is reached
        self.tasks.run()
        self.assertEqual(self.window.disposed, 0)
        self.upload._fail("no again")
        self.tasks.run()
        self.assertEqual(self.window.disposed, 1)   # closed once, by the end of the one that showed it last

    def test_an_upload_that_never_had_a_window_disposes_none(self):
        self.upload._begin(_job(), 0)
        self.upload._end()
        self.tasks.run()
        self.assertEqual(self.window.disposed, 0)


class FindThenMakeTests(unittest.TestCase):
    def setUp(self):
        self.ui, self.tasks = _Ui(), _Queue()
        self.upload = AttachmentUpload(self.ui, self.tasks, _Host(), _Window(), config_of(), None, lambda: None)
        self.subject = types.SimpleNamespace(item_number="PN-1")
        self.job = _job()
        self.upload._begin(self.job, 0)

    def test_the_item_found_is_made_into_a_file_on_the_ui_thread(self):
        with mock.patch.object(self.upload, "_find_item", return_value=("242", "9")), mock.patch.object(self.upload, "_make") as make:
            self.upload._find_then_make(self.job, CONTEXT, self.subject, "item")
            make.assert_not_called()   # posted, not run on the worker
            self.tasks.run()
        make.assert_called_once_with(self.job, CONTEXT, "242", "9", self.subject, "item")

    def test_a_component_is_looked_for_in_the_components_workspace(self):
        with mock.patch.object(self.upload, "_find_item") as item, mock.patch.object(self.upload, "_find_component", return_value=("176", "5")) as component:
            self.upload._find_then_make(self.job, CONTEXT, self.subject, "component")
        component.assert_called_once_with("PN-1", CONTEXT)
        item.assert_not_called()

    def test_an_item_that_is_not_found_ends_the_upload_with_the_reason(self):
        with mock.patch.object(self.upload, "_find_item", side_effect=LookupError("No item exists for PN-1.")):
            self.upload._find_then_make(self.job, CONTEXT, self.subject, "item")
        self.assertEqual(self.upload.status(), {"active": False})
        self.tasks.run()
        self.assertEqual(self.ui.messages, ["Could not attach a STEP file:\nNo item exists for PN-1."])

    def test_the_add_in_stopping_ends_it_without_a_message(self):
        from src.core.cancel import Cancelled
        with mock.patch.object(self.upload, "_find_item", side_effect=Cancelled()):
            self.upload._find_then_make(self.job, CONTEXT, self.subject, "item")
        self.assertEqual(self.upload.status(), {"active": False})
        self.tasks.run()
        self.assertEqual(self.ui.messages, [])


class SendAndDoneTests(unittest.TestCase):
    def setUp(self):
        from src.ui import attachment_upload
        self.module = attachment_upload
        self.ui, self.tasks, self.host = _Ui(), _Queue(), _Host()
        self.sent, self.reloads = [], []
        self.host.send = lambda *args: self.sent.append(args)
        self.window = _Window()
        self.upload = AttachmentUpload(self.ui, self.tasks, self.host, self.window, config_of(), None, lambda: self.reloads.append(1))
        self.job = _job()
        self.upload._begin(self.job, 2)
        patcher = mock.patch.object(attachment_upload, "FmClient")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _upload(self, **service):
        with mock.patch.object(self.module, "AttachmentService") as attachments:
            attachments.return_value.upload.configure_mock(**service)
            self.upload._upload(self.job, CONTEXT, "242", "9", "PN-1.step", b"data", "item")
            return attachments.return_value.upload

    def test_the_progress_of_the_send_is_reported_as_a_percent(self):
        def send(workspace_id, item_id, name, content, progress):
            progress(0.256)
            return "new"

        self._upload(side_effect=send)
        self.assertEqual(self.upload.status()["percent"], 25)

    def test_the_file_is_sent_to_the_tenant_of_the_context_not_the_one_active_now(self):
        self.upload._config = config_of(tenant="other", hub="hub2")
        self._upload(return_value="new")
        self.assertEqual(self.module.FmClient.call_args.args[0].tenant, "acme")

    def test_a_file_sent_is_told_to_the_user_after_the_item_is_read_again(self):
        self._upload(return_value="new")
        self.assertEqual(self.reloads, [])   # waits for the UI thread
        self.tasks.run()
        self.assertEqual(self.ui.messages, ["PN-1.step was attached to the item in Fusion Manage."])
        self.assertEqual(self.reloads, [1])
        self.assertEqual(self.upload.status(), {"active": False})

    def test_a_new_version_says_so(self):
        self._upload(return_value=self.module.NEW_VERSION)
        self.tasks.run()
        self.assertEqual(self.ui.messages, ["A new version of PN-1.step was uploaded to the item in Fusion Manage."])

    def test_an_open_panel_gets_a_toast_not_a_message_box(self):
        self.host.visible = True
        self._upload(return_value="new")
        self.tasks.run()
        self.assertEqual(self.ui.messages, [])
        self.assertEqual(self.sent[0][0], "toast")
        self.assertIn('"tone": "success"', self.sent[0][1])

    def test_the_progress_window_is_gone_before_the_message_is_shown(self):
        order = []
        self.window.dispose = lambda: order.append("window")
        self.ui.messageBox = lambda *args: order.append("message")
        self.upload._window_open = True
        self._upload(return_value="new")
        self.tasks.run()
        self.assertEqual(order, ["window", "message"])

    def test_a_failed_send_ends_the_upload_with_a_message_and_reads_nothing_again(self):
        self._upload(side_effect=RuntimeError("503"))
        self.tasks.run()
        self.assertEqual(self.ui.messages, ["Could not attach PN-1.step:\n503"])
        self.assertEqual((self.reloads, self.upload.status()), ([], {"active": False}))

    def test_the_add_in_stopping_during_the_send_says_nothing(self):
        from src.core.cancel import Cancelled
        self._upload(side_effect=Cancelled())
        self.tasks.run()
        self.assertEqual((self.ui.messages, self.reloads), ([], []))
        self.assertEqual(self.upload.status(), {"active": False})


class WarmComponentTests(unittest.TestCase):
    def setUp(self):
        self.upload = AttachmentUpload(_Ui(), _Queue(), _Host(), _Window(), config_of(), None, lambda: None)

    def test_a_failure_is_left_for_the_export_to_report(self):
        with mock.patch.object(self.upload, "_find_component", side_effect=LookupError("none")):
            self.upload.warm_component("PN-1", CONTEXT)   # does not raise

    def test_the_add_in_stopping_is_not_an_error(self):
        from src.core.cancel import Cancelled
        with mock.patch.object(self.upload, "_find_component", side_effect=Cancelled()):
            self.upload.warm_component("PN-1", CONTEXT)


class FindComponentTests(unittest.TestCase):
    def setUp(self):
        from src.ui import attachment_upload
        self.module = attachment_upload
        self.upload = AttachmentUpload(_Ui(), _Queue(), _Host(), _Window(), config_of(), None, lambda: None)
        mock.patch.object(attachment_upload, "FmClient").start()
        self.service = mock.patch.object(attachment_upload, "ComponentService").start()
        self.addCleanup(mock.patch.stopall)

    def test_the_component_is_found_once_and_then_kept(self):
        self.service.return_value.find_working.return_value = ("/api/v3/workspaces/176/items/5", "")
        self.assertEqual(self.upload._find_component("PN-1", CONTEXT), ("176", "5"))
        self.assertEqual(self.upload._find_component("PN-1", CONTEXT), ("176", "5"))
        self.service.return_value.find_working.assert_called_once()

    def test_what_was_found_under_one_tenant_is_not_reused_under_another(self):
        self.service.return_value.find_working.side_effect = [("/api/v3/workspaces/176/items/5", ""), ("/api/v3/workspaces/176/items/8", "")]
        self.assertEqual(self.upload._find_component("PN-1", CONTEXT), ("176", "5"))
        self.assertEqual(self.upload._find_component("PN-1", capture_context(config_of(tenant="other"))), ("176", "8"))
        self.assertEqual(self.upload._find_component("PN-1", CONTEXT), ("176", "5"))   # each tenant keeps its own

    def test_a_component_that_is_not_there_says_why_and_is_not_kept(self):
        self.service.return_value.find_working.return_value = ("", "It is released.")
        with self.assertRaisesRegex(LookupError, "It is released."):
            self.upload._find_component("PN-1", CONTEXT)
        with self.assertRaises(LookupError):
            self.upload._find_component("PN-1", CONTEXT)
        self.assertEqual(self.service.return_value.find_working.call_count, 2)


if __name__ == "__main__":
    unittest.main()
