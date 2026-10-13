import unittest

from src.config.export_models import COMPONENT, ITEM, ExportSettings
from src.config.models import AppConfig


class ExportSettingsTests(unittest.TestCase):
    def test_every_format_goes_to_the_item_until_set(self):
        settings = ExportSettings()
        self.assertEqual({k: settings.destination_of(k) for k in ("step", "pdf", "dwg", "dxf")}, {k: ITEM for k in ("step", "pdf", "dwg", "dxf")})

    def test_a_saved_choice_is_kept_and_a_bad_one_falls_back(self):
        settings = ExportSettings.from_dict({"destinations": {"pdf": COMPONENT, "dxf": "nowhere", "zip": COMPONENT}})
        self.assertEqual(settings.destination_of("pdf"), COMPONENT)
        self.assertEqual(settings.destination_of("dxf"), ITEM)
        self.assertNotIn("zip", settings.to_dict()["destinations"])
        self.assertEqual(settings.validate(), [])

    def test_an_old_config_without_exports_loads(self):
        self.assertEqual(AppConfig.from_dict({}).exports.destination_of("pdf"), ITEM)

    def test_the_choices_survive_a_round_trip(self):
        config = AppConfig()
        config.exports.destinations["dwg"] = COMPONENT
        self.assertEqual(AppConfig.from_dict(config.to_dict()).exports.destination_of("dwg"), COMPONENT)


if __name__ == "__main__":
    unittest.main()
