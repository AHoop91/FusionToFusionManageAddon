import unittest
from types import SimpleNamespace

from src.fusion_mfg.fusion_hub_files import _file_details


class FileDetailsTests(unittest.TestCase):
    def test_gives_the_details_fusion_knows(self) -> None:
        data_file = SimpleNamespace(parentProject=SimpleNamespace(name="P"), dateModified=None,
                                    lastUpdatedBy=SimpleNamespace(displayName="Ada"), latestVersionNumber=3)
        info = _file_details(data_file)
        self.assertEqual(info["project_name"], "P")
        self.assertEqual(info["modified_by"], "Ada")
        self.assertEqual(info["version"], "3")

    def test_leaves_out_a_detail_fusion_does_not_give(self) -> None:
        data_file = SimpleNamespace(latestVersionNumber="")   # no project, no updater: those reads raise; an empty version is dropped
        self.assertEqual(_file_details(data_file), {})


if __name__ == "__main__":
    unittest.main()
