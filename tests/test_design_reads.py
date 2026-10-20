import unittest
from unittest import mock

from src.fusion_mfg import design_reads
from src.fusion_mfg.design_reads import DesignReads


class DesignReadsTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(design_reads, "read_section", side_effect=lambda client, section, *rest: {"section": section, "rest": rest})
        self.read = patch.start()
        self.addCleanup(patch.stop)

    def test_a_version_is_read_once(self):
        reads = DesignReads()
        first = reads.summary("client", "m1", "t1")
        self.assertIs(reads.summary("client", "m1", "t1"), first)
        self.assertEqual(self.read.call_count, 1)

    def test_each_kind_of_read_is_kept_on_its_own(self):
        reads = DesignReads()
        summary = reads.summary("client", "m1", "t1")
        reads.structure("client", "m1", "t1", summary)
        reads.structure("client", "m1", "t1", summary)
        reads.properties("client", "m1", "t1", summary, False)
        reads.properties("client", "m1", "t1", summary, True)   # with the physical properties is another read
        reads.properties("client", "m1", "t1", summary, True)
        self.assertEqual([call.args[1] for call in self.read.call_args_list], ["summary", "structure", "properties", "properties"])

    def test_another_version_is_read_again(self):
        reads = DesignReads()
        reads.summary("client", "m1", "t1")
        reads.summary("client", "m1", "t2")
        reads.summary("client", "m1", "t2")
        self.assertEqual(self.read.call_count, 2)

    def test_a_read_that_fails_is_not_kept(self):
        reads = DesignReads()
        self.read.side_effect = [OSError("down"), {"ok": 1}]
        with self.assertRaises(OSError):
            reads.summary("client", "m1", "t1")
        self.assertEqual(reads.summary("client", "m1", "t1"), {"ok": 1})


if __name__ == "__main__":
    unittest.main()
