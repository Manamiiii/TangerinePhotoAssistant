from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from typing import Any

MIN_CONDITION_SAMPLE = 3
MIN_PROBLEM_SAMPLE = 2


def _bucket(value: float | None, boundaries: list[tuple[float, str]], fallback: str) -> str:
    if value is None:
        return fallback
    numeric = float(value)
    for upper, label in boundaries:
        if numeric < upper:
            return label
    return boundaries[-1][1]


def _conditions(row: sqlite3.Row, subjects: list[str]) -> set[tuple[str, str, str]]:
    conditions: set[tuple[str, str, str]] = {
        ("subject", subject, "题材") for subject in subjects if subject
    }
    focal = row["focal_length_35mm"] or row["focal_length_mm"]
    if focal is not None:
        conditions.add(("focal", _bucket(float(focal), [
            (20, "<20mm"), (35, "20–34mm"), (55, "35–54mm"),
            (100, "55–99mm"), (200, "100–199mm"), (float("inf"), "≥200mm"),
        ], ""), "等效焦段"))
    if row["exposure_time"] is not None:
        conditions.add(("shutter", _bucket(float(row["exposure_time"]), [
            (0.001001, "≥1/1000s"), (0.004001, "1/999–1/250s"),
            (0.008001, "1/249–1/125s"), (1 / 60 + 1e-9, "1/124–1/60s"),
            (1 / 15 + 1e-9, "1/59–1/15s"), (float("inf"), "慢于1/15s"),
        ], ""), "快门"))
    if row["iso"] is not None:
        conditions.add(("iso", _bucket(int(row["iso"]), [
            (201, "≤200"), (801, "201–800"), (1601, "801–1600"),
            (3201, "1601–3200"), (6401, "3201–6400"), (float("inf"), ">6400"),
        ], ""), "ISO"))
    if row["f_number"] is not None:
        conditions.add(("aperture", _bucket(float(row["f_number"]), [
            (2, "<f/2"), (2.9, "f/2–2.8"), (4.5, "f/2.9–4"),
            (8.5, "f/4.1–8"), (float("inf"), ">f/8"),
        ], ""), "光圈"))
    if row["camera_model"]:
        conditions.add(("camera", str(row["camera_model"]), "相机"))
    if row["lens_model"]:
        conditions.add(("lens", str(row["lens_model"]), "镜头"))
    return conditions


def build_conditional_review_insights(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT c.id, aa.result_json, f.camera_model, f.lens_model,
                  f.exposure_time, f.f_number, f.iso,
                  f.focal_length_mm, f.focal_length_35mm
           FROM captures c
           JOIN ai_analyses aa ON aa.capture_id=c.id AND aa.status='complete'
             AND COALESCE(aa.user_verdict, '')!='inaccurate'
             AND aa.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                        WHERE newest.capture_id=c.id AND newest.status='complete')
           JOIN capture_files cf ON cf.capture_id=c.id AND cf.role='jpeg'
             AND cf.file_id=(SELECT MIN(cf2.file_id) FROM capture_files cf2
                             JOIN files f2 ON f2.id=cf2.file_id
                             WHERE cf2.capture_id=c.id AND cf2.role='jpeg'
                               AND f2.present=1)
           JOIN files f ON f.id=cf.file_id
           WHERE aa.result_json IS NOT NULL"""
    ).fetchall()
    subject_rows = connection.execute(
        """SELECT ct.capture_id, td.name FROM capture_tags ct
           JOIN tag_definitions td ON td.id=ct.tag_id
           WHERE td.dimension='subject' AND td.active=1"""
    ).fetchall()
    subjects: dict[int, list[str]] = defaultdict(list)
    for row in subject_rows:
        subjects[int(row["capture_id"])].append(str(row["name"]))

    condition_totals: Counter[tuple[str, str, str]] = Counter()
    problem_totals: Counter[str] = Counter()
    joint_totals: Counter[tuple[tuple[str, str, str], str]] = Counter()
    valid_captures = 0
    for row in rows:
        try:
            result = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict):
            continue
        problems = {
            " ".join(str(problem.get("name") or "").split())
            for problem in (result.get("visible_problems") or [])
            if isinstance(problem, dict) and problem.get("name")
        }
        conditions = _conditions(row, subjects.get(int(row["id"]), []))
        valid_captures += 1
        condition_totals.update(conditions)
        problem_totals.update(problems)
        joint_totals.update((condition, problem) for condition in conditions for problem in problems)

    if valid_captures < MIN_CONDITION_SAMPLE:
        return []
    insights: list[dict[str, Any]] = []
    for (dimension, value, dimension_label), sample_count in condition_totals.items():
        if sample_count < MIN_CONDITION_SAMPLE or sample_count >= valid_captures:
            continue
        for problem, total_problem_count in problem_totals.items():
            problem_count = joint_totals[((dimension, value, dimension_label), problem)]
            if problem_count < MIN_PROBLEM_SAMPLE:
                continue
            rate = problem_count / sample_count
            baseline = total_problem_count / valid_captures
            lift = rate / baseline if baseline else 0
            if rate < 0.3 or lift < 1.15:
                continue
            insights.append({
                "condition_key": f"{dimension}|{value}",
                "dimension": dimension,
                "dimension_label": dimension_label,
                "condition": value,
                "problem": problem,
                "sample_count": sample_count,
                "problem_count": problem_count,
                "problem_rate": round(rate * 100, 1),
                "baseline_rate": round(baseline * 100, 1),
                "lift": round(lift, 2),
            })
    insights.sort(
        key=lambda item: (item["lift"], item["problem_count"], item["sample_count"]),
        reverse=True,
    )
    return insights[:12]


def review_condition_sql(raw: str) -> tuple[str, list[Any]]:
    dimension, separator, value = raw.partition("|")
    if not separator or not value:
        raise ValueError("复盘条件格式无效")
    if dimension == "subject":
        return (
            """EXISTS (SELECT 1 FROM capture_tags insight_ct
                        JOIN tag_definitions insight_td ON insight_td.id=insight_ct.tag_id
                        WHERE insight_ct.capture_id=c.id
                          AND insight_td.dimension='subject' AND insight_td.name=?)""",
            [value],
        )
    if dimension == "camera":
        return "f.camera_model=?", [value]
    if dimension == "lens":
        return "f.lens_model=?", [value]
    buckets: dict[str, dict[str, str]] = {
        "focal": {
            "<20mm": "COALESCE(f.focal_length_35mm, f.focal_length_mm)<20",
            "20–34mm": "COALESCE(f.focal_length_35mm, f.focal_length_mm)>=20 AND COALESCE(f.focal_length_35mm, f.focal_length_mm)<35",
            "35–54mm": "COALESCE(f.focal_length_35mm, f.focal_length_mm)>=35 AND COALESCE(f.focal_length_35mm, f.focal_length_mm)<55",
            "55–99mm": "COALESCE(f.focal_length_35mm, f.focal_length_mm)>=55 AND COALESCE(f.focal_length_35mm, f.focal_length_mm)<100",
            "100–199mm": "COALESCE(f.focal_length_35mm, f.focal_length_mm)>=100 AND COALESCE(f.focal_length_35mm, f.focal_length_mm)<200",
            "≥200mm": "COALESCE(f.focal_length_35mm, f.focal_length_mm)>=200",
        },
        "shutter": {
            "≥1/1000s": "f.exposure_time<=0.001",
            "1/999–1/250s": "f.exposure_time>0.001 AND f.exposure_time<=0.004",
            "1/249–1/125s": "f.exposure_time>0.004 AND f.exposure_time<=0.008",
            "1/124–1/60s": "f.exposure_time>0.008 AND f.exposure_time<=1.0/60",
            "1/59–1/15s": "f.exposure_time>1.0/60 AND f.exposure_time<=1.0/15",
            "慢于1/15s": "f.exposure_time>1.0/15",
        },
        "iso": {
            "≤200": "f.iso<=200", "201–800": "f.iso>200 AND f.iso<=800",
            "801–1600": "f.iso>800 AND f.iso<=1600",
            "1601–3200": "f.iso>1600 AND f.iso<=3200",
            "3201–6400": "f.iso>3200 AND f.iso<=6400", ">6400": "f.iso>6400",
        },
        "aperture": {
            "<f/2": "f.f_number<2", "f/2–2.8": "f.f_number>=2 AND f.f_number<2.9",
            "f/2.9–4": "f.f_number>=2.9 AND f.f_number<4.5",
            "f/4.1–8": "f.f_number>=4.5 AND f.f_number<8.5",
            ">f/8": "f.f_number>=8.5",
        },
    }
    expression = buckets.get(dimension, {}).get(value)
    if not expression:
        raise ValueError("复盘条件不受支持")
    return f"({expression})", []
