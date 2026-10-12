import unittest

from src.core.units import convert
from src.sync.property_compare import compare_properties
from src.config.workspace_models import FieldMapping


class ConvertTests(unittest.TestCase):
    def test_a_length_in_centimetres_is_millimetres_times_ten(self):
        self.assertAlmostEqual(convert(20.5, "cm", "mm"), 205)
        self.assertAlmostEqual(convert(20.5, "Centimeters", "mm"), 205)

    def test_area_and_volume_scale_by_the_power(self):
        self.assertAlmostEqual(convert(2.0, "cm²", "mm²"), 200)
        self.assertAlmostEqual(convert(1.5, "Cubic centimeters", "mm³"), 1500)

    def test_density_is_a_ratio(self):
        self.assertAlmostEqual(convert(0.0079, "kg/cm³", "kg/mm³"), 0.0079e-3)
        self.assertAlmostEqual(convert(0.0079, "Kilograms per Cubic Centimeter", "kilograms per cubic millimeter"), 0.0079e-3)

    def test_mass_and_inches(self):
        self.assertAlmostEqual(convert(2.0, "kg", "grams"), 2000)
        self.assertAlmostEqual(convert(25.4, "mm", "inches"), 1)

    def test_a_different_dimension_or_unknown_unit_is_not_converted(self):
        self.assertIsNone(convert(1.0, "cm", "kilograms"))
        self.assertIsNone(convert(1.0, "cm", "furlongs"))
        self.assertIsNone(convert(1.0, "cm", ""))


class CompareConvertsTests(unittest.TestCase):
    def test_a_mapped_physical_value_is_put_in_the_fields_unit(self):
        properties = [{"name": "Physical Length", "value": "20.5", "unit": "cm", "original": "20.5 cm"}]

        def to_field(field, text, unit):
            return ("205", "mm") if (field, unit) == ("LENGTH", "cm") else None

        rows = compare_properties(properties, {}, [FieldMapping("physical:Length", "LENGTH")], {"LENGTH": "205"}, "found", None, to_field)
        row = rows[0]
        self.assertEqual((row["value"], row["unit"], row["original"], row["status"]), ("205", "mm", "20.5 cm", "match"))


if __name__ == "__main__":
    unittest.main()
