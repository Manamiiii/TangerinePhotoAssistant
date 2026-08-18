from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


def request_json(url: str, method: str = "GET") -> dict:
    request = Request(url, method=method)
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pause any local AI task at a fixed safety deadline."
    )
    parser.add_argument("--api-root", default="http://127.0.0.1:8765")
    parser.add_argument("--deadline", required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    deadline = datetime.fromisoformat(args.deadline)
    args.log.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")

    log(f"deadline guard started; deadline={deadline.isoformat()}")
    while datetime.now().astimezone() < deadline:
        time.sleep(min(30, max(1, (deadline - datetime.now().astimezone()).total_seconds())))

    try:
        task = request_json(f"{args.api_root}/api/tasks/current")
        log(
            f"deadline state={task.get('status')} stage={task.get('stage')} "
            f"progress={task.get('current')}/{task.get('total')}"
        )
        if task.get("status") == "running" and task.get("stage") == "ai-analysis":
            paused = request_json(
                f"{args.api_root}/api/ai/runs/current/pause", method="POST"
            )
            log(f"safe pause requested; status={paused.get('status', 'submitted')}")
        else:
            log("no running AI task required a pause")
    except Exception as exc:
        log(f"deadline guard error: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
