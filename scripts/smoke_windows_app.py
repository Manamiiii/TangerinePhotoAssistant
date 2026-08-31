"""Exercise a built Windows backend in a new, empty, retained test workspace."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

from tangerine_photo_assistant.desktop import ServiceClient
from tangerine_photo_assistant.service_runtime import CONTROL_HEADER
from tangerine_photo_assistant.settings import Settings, write_safe_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--port", type=int, default=18876)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix="tangerine-desktop-smoke-"))
    # Child and controller share an isolated local runtime, not the user's one.
    os.environ["LOCALAPPDATA"] = str(root / "LocalAppData")
    photos = root / "photos"
    photos.mkdir()
    config = root / "config.toml"
    write_safe_config(config, photos, root / "workspace", root / "cache")
    client = ServiceClient(config, args.port)
    if client.port_open():
        raise RuntimeError("Test port occupied; no service was started or changed")
    client.backend_command = lambda: [str(executable), "--backend", "--config", str(config),
                                      "--port", str(args.port)]
    started = False
    try:
        health = client.ensure_running(lambda _: None, timeout=45)
        started = True
        assert health["desktop_control"] and health["schema_version"] == 32
        assert client.request("/api/tasks/current")["status"] == "idle"
        with client.opener.open(client.url, timeout=3) as response:
            assert b"<html" in response.read()
        assert isinstance(client.request("/api/equipment"), dict)
        instance = health["instance_id"]
        client.restart(lambda _: None)
        assert client.health()["instance_id"] != instance
        assert client.request("/api/tasks/current")["status"] == "idle"
        database = Settings.load(config).database_path
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("SELECT count(*) FROM captures").fetchone()[0] == 0
        assert not list(photos.iterdir())
        print(json.dumps({"status": "ok", "package_start": True, "graceful_restart": True,
                          "integrity": "ok", "captures": 0, "test_workspace": str(root)}))
    finally:
        # Only the instance created in this private workspace can be controlled.
        # Never kill a PID, delete an active workspace or touch the formal service.
        if started:
            current = client.health()
            if current:
                record = json.loads((client.runtime / "service.json").read_text(encoding="utf-8"))
                assert record["instance_id"] == current["instance_id"]
                session = client.request("/api/session")
                client.request("/api/system/desktop/shutdown", post=True,
                               headers={session["header"]: session["token"], CONTROL_HEADER: record["token"]})
                deadline = time.monotonic() + 15
                while client.port_open() and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert not client.port_open(), "Test service has not exited; test workspace was retained"


if __name__ == "__main__":
    main()
