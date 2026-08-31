import math
import sqlite3
import unittest

from tangerine_photo_assistant.insights import _conditions, review_condition_sql
from tangerine_photo_assistant.parameter_buckets import PARAMETER_BUCKETS


class ParameterBucketTests(unittest.TestCase):
    def test_every_boundary_matches_python_sql_and_drilldown_without_gaps(self):
        with sqlite3.connect(":memory:") as connection:
            for dimension, buckets in PARAMETER_BUCKETS.items():
                values = [None, -1, 0, 0.00001, 99999]
                for upper, _ in buckets.ranges:
                    if upper is not None:
                        values.extend([math.nextafter(upper, 0), upper,
                                       math.nextafter(upper, math.inf)])
                for value in values:
                    with self.subTest(dimension=dimension, value=value):
                        expected = buckets.label(value)
                        actual = connection.execute(
                            f"SELECT {buckets.case_sql('f.')} FROM (SELECT ? AS {buckets.column}) f",
                            (value,),
                        ).fetchone()[0]
                        self.assertEqual(actual, expected)
                        hits = []
                        for label in ["未知", *(label for _, label in buckets.ranges)]:
                            expression, parameters = review_condition_sql(f"{dimension}_v2|{label}")
                            hit = connection.execute(
                                f"SELECT 1 FROM (SELECT ? AS {buckets.column}) f WHERE {expression}",
                                [value, *parameters],
                            ).fetchone()
                            if hit:
                                hits.append(label)
                        self.assertEqual(hits, [expected])

    def test_familiar_stops_and_focal_lengths_keep_raw_values(self):
        self.assertEqual(PARAMETER_BUCKETS["aperture"].label(2.9), "f/2.8–<4")
        self.assertEqual(PARAMETER_BUCKETS["aperture"].label(4), "f/4–<5.6")
        self.assertEqual(PARAMETER_BUCKETS["focal"].label(55), "50–<85mm")
        row = {"focal_length_35mm": None, "focal_length_mm": 55, "f_number": 2.9,
               "exposure_time": None, "iso": None, "camera_model": None, "lens_model": None}
        conditions = _conditions(row, [])
        self.assertFalse(any(dimension == "focal" for dimension, _, _ in conditions))
        self.assertEqual(row["f_number"], 2.9)

    def test_old_saved_conditions_keep_original_boundaries(self):
        expression, _ = review_condition_sql("aperture|f/2.9–4")
        self.assertIn(">=2.9", expression)
        self.assertIn("<4.5", expression)
        expression, _ = review_condition_sql("focal|55–99mm")
        self.assertIn(">=55", expression)
        self.assertIn("<100", expression)
        with self.assertRaises(ValueError):
            review_condition_sql("aperture_v2|anything' OR 1=1")


if __name__ == "__main__":
    unittest.main()
