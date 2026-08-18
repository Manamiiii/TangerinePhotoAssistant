from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json; charset=utf-8"} if data else {},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def comfyui_processes() -> list[str]:
    command = (
        "$self=$PID; Get-CimInstance Win32_Process | "
        "Where-Object { $_.ProcessId -ne $self -and "
        "($_.CommandLine -like '*Documents\\ComfyUI*' -or "
        "$_.ExecutablePath -like '*Documents\\ComfyUI*') } | "
        "ForEach-Object { \"$($_.ProcessId) $($_.Name) $($_.CommandLine)\" }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-root", default="http://127.0.0.1:8765")
    parser.add_argument("--deadline", required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    deadline = datetime.fromisoformat(args.deadline)
    args.log.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")

    log(f"controller started; deadline={deadline.isoformat(timespec='minutes')}")
    benchmark_started = False
    while datetime.now() < deadline:
        try:
            task = request_json(f"{args.api_root}/api/tasks/current")
            log(
                f"task={task['status']} stage={task['stage']} "
                f"progress={task['current']}/{task['total']}"
            )
            if task["status"] == "running":
                time.sleep(30)
                continue
            if task["status"] in {"failed", "cancelled"}:
                log(f"task ended unsafely: status={task['status']} stage={task.get('stage')}")
                return 2
            if benchmark_started:
                if task["status"] == "complete":
                    log("100-photo benchmark completed; controller stopped")
                    return 0
                time.sleep(30)
                continue

            overview = request_json(f"{args.api_root}/api/analysis/overview")
            quality = overview["quality"]
            runtime = overview["runtime"]
            if quality["analyzed"] < 13_806:
                log(
                    f"quality task stopped before expected total: "
                    f"{quality['analyzed']}/13806"
                )
                return 2
            if quality["errors"] > max(50, quality["analyzed"] // 100):
                log(f"quality error gate failed: {quality['errors']} errors")
                return 2
            if not runtime["ready"]:
                log("model runtime unavailable")
                return 2
            comfy = comfyui_processes()
            if comfy:
                log(f"ComfyUI process gate blocked benchmark: processes={len(comfy)}")
                return 2
            task = request_json(
                f"{args.api_root}/api/ai/analyze",
                method="POST",
                payload={"mode": "benchmark", "limit": 100},
            )
            benchmark_started = True
            log(f"100-photo benchmark submitted; task={task['id']}")
        except Exception as exc:
            log(f"controller error: {type(exc).__name__}")
        time.sleep(30)

    try:
        task = request_json(f"{args.api_root}/api/tasks/current")
        if task["status"] == "running":
            request_json(f"{args.api_root}/api/tasks/current/cancel", method="POST")
            log("deadline reached; running task cancellation requested")
    except Exception as exc:
        log(f"deadline cancellation check failed: {type(exc).__name__}")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
