from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.diagnostics import build_diagnostic_report, write_diagnostic_bundle
from tangerine_photo_assistant.settings import Settings


def settings_for(root: Path) -> Settings:
    originals = root / "private-photos"
    originals.mkdir()
    workspace = root / "workspace"
    (workspace / "Equipment").mkdir(parents=True)
    (workspace / "Equipment" / "inventory.json").write_text(
        json.dumps({"version": 2, "ownership": {"camera": {"SECRET-SERIAL": True}, "lens": {}, "accessory": {}}}),
        encoding="utf-8",
    )
    return Settings(
        originals=originals,
        workspace=workspace,
        cache_root=root / "cache",
        cache_max_size_gb=20,
        offline_only=True,
        read_only=True,
        allow_move=False,
        allow_delete=False,
        allow_original_metadata_write=False,
        raw_extensions=(".raf", ".cr3"),
        exiftool=None,
        metadata_batch_size=8,
        burst_time_gap_seconds=3.0,
    )


class DiagnosticBundleTests(unittest.TestCase):
    def test_bundle_uses_a_whitelist_and_excludes_sensitive_values(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            connection = connect(settings.database_path)
            private_path = str(root / "private-photos" / "SECRET-FILENAME.JPG")
            connection.execute(
                "INSERT INTO scan_runs(started_at,root_path,status) VALUES ('now',?,'complete')",
                (str(settings.originals),),
            )
            run_id = int(connection.execute("SELECT id FROM scan_runs").fetchone()[0])
            connection.execute(
                "INSERT INTO scan_errors(scan_run_id,path,error_type,message) VALUES (?,?,?,?)",
                (run_id, private_path, "C:/SECRET/error", "SECRET-RAW-ERROR"),
            )
            connection.execute(
                """INSERT INTO files(
                    path,relative_path,parent_relative,file_name,stem,extension,media_kind,
                    size_bytes,modified_ns,first_seen_run_id,last_seen_run_id,exif_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (private_path, "SECRET-FILENAME.JPG", "", "SECRET-FILENAME.JPG", "SECRET-FILENAME", ".jpg", "jpeg", 10, 1, run_id, run_id,
                 '{"GPSLatitude":31.123,"SerialNumber":"SECRET-SERIAL"}'),
            )
            connection.commit()

            task = {"status": "complete", "stage": "SECRET user note / path", "current": 2, "total": 2, "failure_count": 0, "pausable": False}
            report = build_diagnostic_report(connection, settings, task)
            serialized = json.dumps(report, ensure_ascii=False)
            for secret in (str(root), "SECRET-FILENAME", "SECRET-SERIAL", "31.123", "SECRET-RAW-ERROR", "SECRET user note"):
                self.assertNotIn(secret, serialized)
            self.assertEqual(report["database"]["integrity"], "ok")
            self.assertEqual(report["database"]["table_counts"]["files"], 1)
            self.assertEqual(report["database"]["scan_error_types"], [{"value": "other", "count": 1}])
            self.assertEqual(report["task"]["stage"], "other")
            self.assertEqual(report["equipment_counts"]["ownership"]["camera"], 1)

            result = write_diagnostic_bundle(connection, settings, task)
            bundle = settings.reports_path / result["filename"]
            self.assertRegex(bundle.name, r"^tangerine-diagnostics-\d{8}-\d{6}-\d{6}\.zip$")
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(archive.namelist(), ["diagnostics.json"])
                payload = archive.read("diagnostics.json").decode("utf-8")
            self.assertNotIn("SECRET", payload)
            self.assertEqual(result["integrity"], "ok")
            connection.close()


if __name__ == "__main__":
    unittest.main()
