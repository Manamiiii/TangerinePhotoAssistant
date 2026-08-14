import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.editing import (
    EditRecipeError,
    edit_recipe_history,
    restore_edit_recipe,
    render_edit_preview,
    save_edit_recipe,
)


class EditRecipeTests(unittest.TestCase):
    def test_preview_renders_all_parameters_without_changing_source(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.jpg"
            image = Image.new("RGB", (32, 24))
            image.putdata([
                (x * 8, y * 10, (x + y) * 4)
                for y in range(24) for x in range(32)
            ])
            image.save(source, quality=95)
            original_bytes = source.read_bytes()
            rendered = render_edit_preview(source, {
                "exposure_ev": 0.4, "contrast": 15, "highlights": -30,
                "shadows": 20, "temperature": 18, "tint": -8,
                "saturation": 12, "sharpness": 30,
            })
            self.assertEqual(source.read_bytes(), original_bytes)
            with Image.open(source) as before, Image.open(BytesIO(rendered)) as after:
                self.assertEqual(after.size, before.size)
                self.assertIsNotNone(ImageChops.difference(before.convert("RGB"), after.convert("RGB")).getbbox())

    def test_recipe_versions_are_non_destructive_and_restorable(self) -> None:
        with TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "catalog.sqlite3")
            connection.execute(
                """INSERT INTO captures(capture_key, parent_relative, stem, pairing_status)
                   VALUES ('capture:1', 'sample', 'PHOTO_1', 'jpeg_only')"""
            )
            connection.commit()
            first = save_edit_recipe(
                connection, 1, {"exposure_ev": 0.4, "highlights": -30}
            )
            second = save_edit_recipe(
                connection, 1, {"contrast": 12}, status="accepted",
                note="  保留自然肤色  ",
            )
            self.assertEqual(second["status"], "accepted")
            self.assertEqual(second["note"], "保留自然肤色")
            self.assertEqual(second["parameters"]["contrast"], 12)
            self.assertEqual(second["parameters"]["exposure_ev"], 0)

            restored = restore_edit_recipe(connection, 1, first["id"])
            self.assertEqual(restored["status"], "draft")
            self.assertEqual(restored["parameters"]["exposure_ev"], 0.4)
            self.assertEqual(len(edit_recipe_history(connection, 1)), 3)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM edit_recipe_revisions").fetchone()[0],
                3,
            )
            connection.close()

    def test_recipe_parameter_boundaries_and_source_are_validated(self) -> None:
        with TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "catalog.sqlite3")
            connection.execute(
                """INSERT INTO captures(capture_key, parent_relative, stem, pairing_status)
                   VALUES ('capture:1', 'sample', 'PHOTO_1', 'jpeg_only')"""
            )
            connection.commit()
            with self.assertRaises(EditRecipeError):
                save_edit_recipe(connection, 1, {"exposure_ev": 3})
            with self.assertRaises(EditRecipeError):
                save_edit_recipe(connection, 1, {"unknown": 1})
            with self.assertRaises(EditRecipeError):
                save_edit_recipe(connection, 1, {}, source_analysis_id=99)
            connection.close()


if __name__ == "__main__":
    unittest.main()
