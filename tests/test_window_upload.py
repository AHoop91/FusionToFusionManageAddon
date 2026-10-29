"""How an upload is started, kept, ended and told: what the Export window reads, what a failure leaves behind, and what the files of an item make of a preview."""

import os
import sys
import tempfile
import types
import unittest
from unittest import mock


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
        self.upload = AttachmentUpload(self.ui, _Tasks(), _Host(), _Host(), None, None, lambda: self.reloads.append(1))
        self.job = UploadJob("Uploading STEP File", "STEP file", ".step", ("Find item", "Create STEP", "Upload"), lambda *a: None, lambda *a: True)

    def test_one_upload_at_a_time(self):
        self.assertTrue(self.upload.begin_in_window(self.job))
        self.assertFalse(self.upload.begin_in_window(self.job))
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
        self.assertTrue(self.upload.begin_in_window(self.job))
        self.assertNotIn("result", self.upload.status())

    def test_an_upload_started_elsewhere_still_ends_in_a_message_box(self):
        self.assertTrue(self.upload._begin(self.job, 0))
        self.upload._fail("no")
        self.assertEqual(self.upload.status(), {"active": False})
        self.assertEqual(self.ui.messages, ["no"])


class UploadAnnounceTests(unittest.TestCase):
    def setUp(self):
        self.told = []
        self.upload = AttachmentUpload(_Ui(), _Tasks(), _Host(), _Host(), None, None, lambda: None, self.told.append)
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
        self.upload = AttachmentUpload(self.ui, _Tasks(), _Host(), _Window(), None, None, lambda: None)
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
            self.upload._make(_job(make), "7", "9", self.subject)
        self.assertEqual(seen, ["PN_1.step"])   # the number is made safe to be a file name
        sent = thread.call_args.kwargs["args"]
        self.assertEqual((sent[1:3], sent[3], sent[4]), (("7", "9"), "PN_1.step", b"step data"))
        self.assertEqual(os.listdir(self.root.name), [])
        self.assertEqual((self.upload.status()["step"], self.upload.status()["percent"]), (2, 0))

    def test_a_file_that_cannot_be_made_ends_the_upload_with_a_message_and_leaves_no_folder(self):
        def make(path, *_rest):
            raise RuntimeError("no geometry")

        self.upload._begin(_job(), 1)
        self.upload._make(_job(make), "7", "9", self.subject)
        self.assertEqual(self.upload.status(), {"active": False})
        self.assertEqual(self.ui.messages, ["Could not create PN_1.step:\nno geometry"])
        self.assertEqual(os.listdir(self.root.name), [])

    def test_a_file_that_comes_out_empty_is_not_uploaded(self):
        def make(path, *_rest):
            open(path, "wb").close()

        self.upload._begin(_job(), 1)
        with mock.patch("threading.Thread") as thread:
            self.upload._make(_job(make), "7", "9", self.subject)
        thread.assert_not_called()
        self.assertEqual(self.upload.status(), {"active": False})
        self.assertEqual(self.ui.messages, ["Could not create PN_1.step:\nThe STEP file came out empty."])

    def test_a_folder_that_cannot_be_made_ends_the_upload_too(self):
        self.upload._begin(_job(), 1)
        with mock.patch("os.makedirs", side_effect=PermissionError("denied")):
            self.upload._make(_job(), "7", "9", self.subject)
        self.assertEqual(self.upload.status(), {"active": False})   # not left under way, which would refuse every later upload
        self.assertEqual(len(self.ui.messages), 1)
        self.assertIn("denied", self.ui.messages[0])

    def test_the_window_that_cannot_be_shown_does_not_leave_the_upload_under_way(self):
        window = _Window(RuntimeError("no window"))
        upload = AttachmentUpload(self.ui, _Tasks(), _Host(), window, None, None, lambda: None)
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
        upload = AttachmentUpload(self.ui, _Tasks(), _Host(), _Window(), None, None, lambda: None, told.append)
        upload._begin(_job(), 1)
        upload._end()
        upload._stage(_job(), 2, 80)
        self.assertEqual(upload.status(), {"active": False})
        self.assertEqual(told[-1], {"active": False})


class FindItemTests(unittest.TestCase):
    def setUp(self):
        from src.ui import attachment_upload
        self.module = attachment_upload
        self.config = mock.MagicMock()
        self.config.items_setup_problem.return_value = ""
        self.config.config.workspaces.get.return_value.workspace_id = "242"
        self.upload = AttachmentUpload(_Ui(), _Tasks(), _Host(), _Window(), self.config, None, lambda: None)
        self.addCleanup(mock.patch.stopall)

    def _search(self, hits):
        service = mock.patch.object(self.module, "ItemService").start()
        service.return_value.search.return_value = hits
        mock.patch.object(self.module, "FmClient").start()
        return service

    def test_an_items_workspace_that_is_not_set_up_says_so(self):
        self.config.items_setup_problem.return_value = "The Items workspace is not set."
        with self.assertRaisesRegex(ValueError, "not set.*Complete it in Preferences"):
            self.upload._find_item("PN-1")

    def test_no_item_for_the_number_is_said(self):
        self._search([])
        with self.assertRaisesRegex(LookupError, "No item exists for PN-1"):
            self.upload._find_item("PN-1")

    def test_one_hit_is_the_item(self):
        service = self._search([{"id": "9", "descriptor": "PN-1 - Bolt"}])
        self.assertEqual(self.upload._find_item("PN-1"), ("242", "9"))
        self.assertEqual(service.call_args.args[1], self.module.WORKING)   # a released version cannot have files attached

    def test_several_that_match_are_not_guessed_between(self):
        self._search([{"id": "9", "descriptor": "PN-1 - Bolt"}, {"id": "10", "descriptor": "PN-1 - Nut"}])
        with self.assertRaisesRegex(LookupError, "2 Fusion Manage items match PN-1"):
            self.upload._find_item("PN-1")


class PreviewTests(unittest.TestCase):
    def setUp(self):
        from src.ui import attachment_upload
        self.module = attachment_upload
        self.upload = AttachmentUpload(_Ui(), _Tasks(), _Host(), _Window(), mock.MagicMock(), None, lambda: None)
        for name in ("FmClient", "AttachmentService"):
            mock.patch.object(attachment_upload, name).start()
        self.addCleanup(mock.patch.stopall)
        self.files = attachment_upload.AttachmentService.return_value.files

    def _preview(self, destination="item"):
        with mock.patch.object(self.upload, "_find_item", return_value=("242", "9")), \
                mock.patch.object(self.upload, "_find_component", return_value=("176", "5")) as component:
            self.component = component
            return self.upload.preview(destination, "PN-1", "PN-1.step", {"saved": 1})

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


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.ui, self.tasks, self.window = _Ui(), _Queue(), _Window()
        self.upload = AttachmentUpload(self.ui, self.tasks, _Host(), self.window, None, None, lambda: None)
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
        self.upload = AttachmentUpload(self.ui, self.tasks, _Host(), _Window(), None, None, lambda: None)
        self.subject = types.SimpleNamespace(item_number="PN-1")
        self.job = _job()
        self.upload._begin(self.job, 0)

    def test_the_item_found_is_made_into_a_file_on_the_ui_thread(self):
        with mock.patch.object(self.upload, "_find_item", return_value=("242", "9")), mock.patch.object(self.upload, "_make") as make:
            self.upload._find_then_make(self.job, self.subject, "item")
            make.assert_not_called()   # posted, not run on the worker
            self.tasks.run()
        make.assert_called_once_with(self.job, "242", "9", self.subject, "item")

    def test_a_component_is_looked_for_in_the_components_workspace(self):
        with mock.patch.object(self.upload, "_find_item") as item, mock.patch.object(self.upload, "_find_component", return_value=("176", "5")) as component:
            self.upload._find_then_make(self.job, self.subject, "component")
        component.assert_called_once_with("PN-1")
        item.assert_not_called()

    def test_an_item_that_is_not_found_ends_the_upload_with_the_reason(self):
        with mock.patch.object(self.upload, "_find_item", side_effect=LookupError("No item exists for PN-1.")):
            self.upload._find_then_make(self.job, self.subject, "item")
        self.assertEqual(self.upload.status(), {"active": False})
        self.tasks.run()
        self.assertEqual(self.ui.messages, ["Could not attach a STEP file:\nNo item exists for PN-1."])

    def test_the_add_in_stopping_ends_it_without_a_message(self):
        from src.core.cancel import Cancelled
        with mock.patch.object(self.upload, "_find_item", side_effect=Cancelled()):
            self.upload._find_then_make(self.job, self.subject, "item")
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
        self.upload = AttachmentUpload(self.ui, self.tasks, self.host, self.window, mock.MagicMock(), None, lambda: self.reloads.append(1))
        self.job = _job()
        self.upload._begin(self.job, 2)
        patcher = mock.patch.object(attachment_upload, "FmClient")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _upload(self, **service):
        with mock.patch.object(self.module, "AttachmentService") as attachments:
            attachments.return_value.upload.configure_mock(**service)
            self.upload._upload(self.job, "242", "9", "PN-1.step", b"data", "item")
            return attachments.return_value.upload

    def test_the_progress_of_the_send_is_reported_as_a_percent(self):
        def send(workspace_id, item_id, name, content, progress):
            progress(0.256)
            return "new"

        self._upload(side_effect=send)
        self.assertEqual(self.upload.status()["percent"], 25)

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
        self.upload = AttachmentUpload(_Ui(), _Queue(), _Host(), _Window(), mock.MagicMock(), None, lambda: None)

    def test_a_failure_is_left_for_the_export_to_report(self):
        with mock.patch.object(self.upload, "_find_component", side_effect=LookupError("none")):
            self.upload.warm_component("PN-1")   # does not raise

    def test_the_add_in_stopping_is_not_an_error(self):
        from src.core.cancel import Cancelled
        with mock.patch.object(self.upload, "_find_component", side_effect=Cancelled()):
            self.upload.warm_component("PN-1")


class FindComponentTests(unittest.TestCase):
    def setUp(self):
        from src.ui import attachment_upload
        self.module = attachment_upload
        self.upload = AttachmentUpload(_Ui(), _Queue(), _Host(), _Window(), mock.MagicMock(), None, lambda: None)
        mock.patch.object(attachment_upload, "FmClient").start()
        self.service = mock.patch.object(attachment_upload, "ComponentService").start()
        self.addCleanup(mock.patch.stopall)

    def test_the_component_is_found_once_and_then_kept(self):
        self.service.return_value.find_working.return_value = ("/api/v3/workspaces/176/items/5", "")
        self.assertEqual(self.upload._find_component("PN-1"), ("176", "5"))
        self.assertEqual(self.upload._find_component("PN-1"), ("176", "5"))
        self.service.return_value.find_working.assert_called_once()

    def test_a_component_that_is_not_there_says_why_and_is_not_kept(self):
        self.service.return_value.find_working.return_value = ("", "It is released.")
        with self.assertRaisesRegex(LookupError, "It is released."):
            self.upload._find_component("PN-1")
        with self.assertRaises(LookupError):
            self.upload._find_component("PN-1")
        self.assertEqual(self.service.return_value.find_working.call_count, 2)


if __name__ == "__main__":
    unittest.main()
