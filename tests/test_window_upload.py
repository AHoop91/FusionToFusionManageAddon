"""The end of an upload the Export window follows is kept for the window to read; an upload started elsewhere still ends in a message."""

import sys
import types
import unittest


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


if __name__ == "__main__":
    unittest.main()
