import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.editing import (
    EditRecipeError,
    edit_recipe_history,
    restore_edit_recipe,
    save_edit_recipe,
)


class EditRecipeTests(unittest.TestCase):
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
