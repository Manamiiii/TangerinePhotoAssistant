from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from PIL import Image, ImageOps

from .ai_analysis import (
    ai_run_status,
    build_prompt,
    parse_model_json,
    validate_model_result,
)
from .database import connect
from .inventory import utc_now
from .settings import Settings


def _load_equipment(project_root: Path) -> str:
    path = project_root / "docs" / "EQUIPMENT_PROFILE.md"
    if not path.is_file():
        return "器材资料未提供。"
    text = path.read_text(encoding="utf-8")
    return text[:8000]


def _load_runtime(settings: Settings) -> tuple[Any, Any, Any]:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import torch
    from transformers import (
        AutoProcessor,
        BitsAndBytesConfig,
        Qwen3VLForConditionalGeneration,
    )

    if settings.ai_model_path is None:
        raise RuntimeError("AI model path is not configured")
    processor = AutoProcessor.from_pretrained(
        settings.ai_model_path, local_files_only=True, trust_remote_code=False
    )
    model_options: dict[str, Any] = {
        "dtype": torch.bfloat16,
        "local_files_only": True,
        "trust_remote_code": False,
        "attn_implementation": "sdpa",
    }
    if settings.ai_quantization == "int8":
        model_options.update({
            "quantization_config": BitsAndBytesConfig(load_in_8bit=True),
            "device_map": "auto",
            "max_memory": {
                0: f"{settings.ai_gpu_memory_limit_gb}GiB",
                "cpu": "18GiB",
            },
            "low_cpu_mem_usage": True,
        })
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            settings.ai_model_path, **model_options
        )
    else:
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            settings.ai_model_path, **model_options
        ).to("cuda")
    model.eval()
    return torch, processor, model


def _generate(
    torch: Any, processor: Any, model: Any, image_path: Path, prompt: str,
    max_tokens: int, image_max_edge: int,
) -> str:
    with Image.open(image_path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((image_max_edge, image_max_edge), Image.Resampling.LANCZOS)
        messages = [{
            "role": "user",
            "content": [{"type": "image"}, {"type": "text", "text": prompt}],
        }]
        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = processor(text=[text], images=[image], padding=True, return_tensors="pt")
    inputs = {key: value.to(model.device) for key, value in inputs.items()}
    with torch.inference_mode():
        generated = model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
    input_length = inputs["input_ids"].shape[1]
    return processor.batch_decode(
        generated[:, input_length:], skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]


def _apply_control_request(connection: sqlite3.Connection, run_id: int) -> str | None:
    row = connection.execute("SELECT status FROM ai_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"AI run {run_id} no longer exists")
    if row["status"] == "pause_requested":
        connection.execute(
            """UPDATE ai_runs SET status='paused', finished_at=NULL, worker_pid=NULL,
               heartbeat_at=? WHERE id=?""",
            (utc_now(), run_id),
        )
        connection.commit()
        return "paused"
    if row["status"] == "cancel_requested":
        connection.execute(
            """
            UPDATE ai_analyses SET status='cancelled', finished_at=?
            WHERE run_id=? AND status IN ('queued', 'running')
            """,
            (utc_now(), run_id),
        )
        connection.execute(
            """UPDATE ai_runs SET status='cancelled', finished_at=?, worker_pid=NULL,
               heartbeat_at=? WHERE id=?""",
            (utc_now(), utc_now(), run_id),
        )
        connection.commit()
        return "cancelled"
    return None


def run_worker(config_path: Path, run_id: int) -> int:
    settings = Settings.load(config_path)
    ready, message = settings.ai_runtime_status()
    if not ready:
        raise RuntimeError(message)
    connection = connect(settings.database_path)
    project_root = Path(__file__).resolve().parents[2]
    try:
        run = ai_run_status(connection, run_id)
        if run["status"] not in {"queued", "running"}:
            raise RuntimeError(f"AI run {run_id} is already {run['status']}")
        connection.execute(
            """UPDATE ai_runs SET status='running', error=NULL, worker_pid=?, heartbeat_at=?
               WHERE id=?""",
            (os.getpid(), utc_now(), run_id),
        )
        connection.commit()
        torch, processor, model = _load_runtime(settings)
        equipment = _load_equipment(project_root)
        jobs = connection.execute(
            """
            SELECT aa.id AS analysis_id, aa.capture_id, f.path,
                   c.captured_at, f.camera_model, f.lens_model, f.exposure_time,
                   f.f_number, f.iso, f.focal_length_mm, f.focal_length_35mm,
                   f.exposure_compensation, qm.technical_score, qm.exposure_score,
                   qm.sharpness_score, qm.highlight_clip_pct, qm.shadow_clip_pct,
                   qm.issue_json
            FROM ai_analyses aa
            JOIN captures c ON c.id = aa.capture_id
            JOIN quality_metrics qm ON qm.capture_id = c.id
            JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
              AND cf.file_id = (SELECT MIN(cf2.file_id) FROM capture_files cf2
                                JOIN files f2 ON f2.id = cf2.file_id
                                WHERE cf2.capture_id = c.id AND cf2.role = 'jpeg'
                                  AND f2.present = 1)
            JOIN files f ON f.id = cf.file_id
            WHERE aa.run_id = ? AND aa.status = 'queued'
            ORDER BY aa.priority DESC, aa.id
            """,
            (run_id,),
        ).fetchall()
        for index, row in enumerate(jobs, 1):
            if _apply_control_request(connection, run_id):
                return 0
            connection.execute(
                "UPDATE ai_analyses SET status='running', started_at=? WHERE id=?",
                (utc_now(), row["analysis_id"]),
            )
            connection.commit()
            raw_responses: list[str] = []
            try:
                issues = json.loads(row["issue_json"])
                prompt = build_prompt(row, issues, equipment)
                result: dict[str, Any] | None = None
                last_parse_error: Exception | None = None
                for attempt in range(1, settings.ai_json_retry_count + 2):
                    connection.execute(
                        "UPDATE ai_analyses SET attempt_count=? WHERE id=?",
                        (attempt, row["analysis_id"]),
                    )
                    connection.commit()
                    attempt_prompt = prompt if attempt == 1 else (
                        prompt + "\n上次输出未通过结构校验。请重新生成完整且严格合法的 JSON，"
                        "不要解释，不要使用 Markdown。"
                    )
                    response = _generate(
                        torch, processor, model, Path(row["path"]), attempt_prompt,
                        settings.ai_max_new_tokens, settings.ai_image_max_edge,
                    )
                    raw_responses.append(response)
                    try:
                        result = validate_model_result(parse_model_json(response))
                        break
                    except (ValueError, json.JSONDecodeError) as exc:
                        last_parse_error = exc
                if result is None:
                    raise ValueError(
                        f"Model JSON remained invalid after {len(raw_responses)} attempts: "
                        f"{last_parse_error}"
                    )
                connection.execute(
                    """
                    UPDATE ai_analyses SET status='complete', result_json=?,
                        raw_response=?, error=NULL, finished_at=? WHERE id=?
                    """,
                    (
                        json.dumps(result, ensure_ascii=False),
                        "\n\n--- retry ---\n\n".join(raw_responses),
                        utc_now(), row["analysis_id"],
                    ),
                )
            except Exception as exc:
                connection.execute(
                    """
                    UPDATE ai_analyses SET status='failed', error=?, raw_response=?,
                        finished_at=? WHERE id=?
                    """,
                    (
                        str(exc),
                        "\n\n--- retry ---\n\n".join(raw_responses) or None,
                        utc_now(), row["analysis_id"],
                    ),
                )
            counts = connection.execute(
                """SELECT SUM(status='complete'), SUM(status='failed')
                   FROM ai_analyses WHERE run_id=?""", (run_id,)
            ).fetchone()
            connection.execute(
                """UPDATE ai_runs SET completed_count=?, failed_count=?, heartbeat_at=?
                   WHERE id=?""",
                (counts[0] or 0, counts[1] or 0, utc_now(), run_id),
            )
            connection.commit()
            print(f"AI analysis: {index:,} / {len(jobs):,}", flush=True)
            if _apply_control_request(connection, run_id):
                return 0
        final = connection.execute(
            "SELECT failed_count FROM ai_runs WHERE id=?", (run_id,)
        ).fetchone()
        connection.execute(
            """UPDATE ai_runs SET status='complete', finished_at=?, worker_pid=NULL,
               heartbeat_at=? WHERE id=?""",
            (utc_now(), utc_now(), run_id),
        )
        connection.commit()
        return 0 if not final["failed_count"] else 2
    except Exception as exc:
        connection.execute(
            """UPDATE ai_runs SET status='failed', error=?, finished_at=?,
               worker_pid=NULL, heartbeat_at=? WHERE id=?""",
            (str(exc), utc_now(), utc_now(), run_id),
        )
        connection.commit()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    try:
        return run_worker(args.config.resolve(), args.run_id)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
