from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def request_json(url: str, method: str = "GET") -> dict:
    request = Request(url, method=method)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--target-completed-batches", type=int, required=True)
    parser.add_argument("--api-root", default="http://127.0.0.1:8765")
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()

    args.log.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")

    log(
        f"controller started; run={args.run_id} "
        f"target={args.target_completed_batches}"
    )
    while True:
        try:
            status = request_json(f"{args.api_root}/api/migration/status")
            run = status["plan"]["run"]
            log(
                f"run={run['id']} status={run['status']} "
                f"batches={run['completed_batches']} verified={run['verified_count']} "
                f"failed={run['failed_count']} bytes={run['copied_bytes']}"
            )
            if run["id"] != args.run_id:
                log("active run changed; controller stopped")
                return 2
            if (
                run["completed_batches"] >= args.target_completed_batches
                and run["status"] == "paused"
            ) or run["status"] in {"audited", "switched"}:
                log("target reached; controller stopped normally")
                return 0
            if run["status"] in {"cancelled", "failed", "audit_failed"}:
                log("terminal safety state reached; controller stopped")
                return 2
            if (
                run["status"] == "paused"
                and run["completed_batches"] < args.target_completed_batches
            ):
                task = request_json(
                    f"{args.api_root}/api/migration/runs/{args.run_id}/resume",
                    method="POST",
                )
                log(f"resume submitted; task={task['id']}")
        except Exception as exc:
            log(f"poll error: {exc}")
        time.sleep(20)


if __name__ == "__main__":
    raise SystemExit(main())
