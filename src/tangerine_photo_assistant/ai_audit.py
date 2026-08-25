from __future__ import annotations

import json
import sqlite3
from typing import Any

from .ai_analysis import (
    AUDIT_LOW_CONFIDENCE,
    AUDIT_OVERCONFIDENT,
    AUDIT_PARSE_ERROR,
    AUDIT_RISK_MASK,
    AUDIT_SCHEMA_ERROR,
    AUDIT_UNSAFE_ACTION,
    AUDIT_VISIBLE_PROBLEMS,
)
from .inventory import utc_now


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 0.5:
        return "low"
    if value < 0.8:
        return "medium"
    if value < 0.99:
        return "high"
    return "overconfident"


def _problem_labels(bits: int | None) -> list[str]:
    value = int(bits or 0)
    labels = []
    for bit, label in (
        (AUDIT_PARSE_ERROR, "parse"),
        (AUDIT_SCHEMA_ERROR, "schema"),
        (AUDIT_UNSAFE_ACTION, "unsafe"),
        (AUDIT_OVERCONFIDENT, "overconfident"),
        (AUDIT_LOW_CONFIDENCE, "low_confidence"),
        (AUDIT_VISIBLE_PROBLEMS, "visible"),
    ):
        if value & bit:
            labels.append(label)
    return labels or ["none"]


def _benchmark_candidates(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT aa.id AS analysis_id, aa.capture_id,
                  GROUP_CONCAT(DISTINCT CASE WHEN e.id IS NOT NULL
                      THEN e.id || ':' || e.proposed_name END) AS albums,
                  COALESCE(substr(c.captured_at, 1, 7), '未知月份') AS capture_month,
                  aa.audit_confidence, aa.audit_bits,
                  GROUP_CONCAT(DISTINCT CASE
                      WHEN td.dimension='subject' AND ct.source='analysis'
                      THEN td.name END) AS subjects
           FROM ai_analyses aa
           JOIN captures c ON c.id=aa.capture_id
           LEFT JOIN event_captures ec ON ec.capture_id=c.id
           LEFT JOIN events e ON e.id=ec.event_id AND e.status!='archived'
           LEFT JOIN capture_tags ct ON ct.capture_id=c.id
           LEFT JOIN tag_definitions td ON td.id=ct.tag_id
           WHERE aa.status='complete' AND aa.result_json IS NOT NULL
             AND aa.id=(SELECT MAX(latest.id) FROM ai_analyses latest
                        WHERE latest.capture_id=aa.capture_id
                          AND latest.status='complete'
                          AND latest.result_json IS NOT NULL)
           GROUP BY aa.capture_id ORDER BY aa.capture_id"""
    ).fetchall()
    candidates = []
    for row in rows:
        subjects = sorted(filter(None, str(row["subjects"] or "").split(",")))
        albums = sorted(filter(None, str(row["albums"] or "").split(",")))
        strata = {
            "album": albums or ["0:未归入相册"],
            "subject": subjects or ["未分类"],
            "month": [str(row["capture_month"])],
            "confidence": [_confidence_bucket(row["audit_confidence"])],
            "problem": _problem_labels(row["audit_bits"]),
        }
        candidates.append({
            "capture_id": int(row["capture_id"]),
            "analysis_id": int(row["analysis_id"]),
            "strata": strata,
        })
    return candidates


def create_fixed_benchmark(
    connection: sqlite3.Connection, target_size: int = 100
) -> dict[str, Any]:
    if not 10 <= target_size <= 500:
        raise ValueError("固定基准集目标数量必须在 10 到 500 之间")
    existing_rows = connection.execute(
        "SELECT capture_id, strata_json FROM ai_audit_benchmark ORDER BY capture_id"
    ).fetchall()
    existing_ids = {int(row["capture_id"]) for row in existing_rows}
    coverage: dict[str, int] = {}
    for row in existing_rows:
        try:
            strata = json.loads(row["strata_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        for dimension, values in strata.items():
            for value in values:
                key = f"{dimension}:{value}"
                coverage[key] = coverage.get(key, 0) + 1
    remaining = [
        candidate for candidate in _benchmark_candidates(connection)
        if candidate["capture_id"] not in existing_ids
    ]
    selected: list[dict[str, Any]] = []
    while remaining and len(existing_ids) + len(selected) < target_size:
        def score(candidate: dict[str, Any]) -> tuple[float, int]:
            balance = sum(
                1.0 / (1 + coverage.get(f"{dimension}:{value}", 0))
                for dimension, values in candidate["strata"].items()
                for value in values
            )
            return balance, -candidate["capture_id"]

        best = max(remaining, key=score)
        remaining.remove(best)
        selected.append(best)
        for dimension, values in best["strata"].items():
            for value in values:
                key = f"{dimension}:{value}"
                coverage[key] = coverage.get(key, 0) + 1
    now = utc_now()
    connection.executemany(
        """INSERT OR IGNORE INTO ai_audit_benchmark(
               capture_id, source_analysis_id, added_at, strata_json
           ) VALUES (?, ?, ?, ?)""",
        [
            (
                item["capture_id"], item["analysis_id"], now,
                json.dumps(item["strata"], ensure_ascii=False, sort_keys=True),
            )
            for item in selected
        ],
    )
    if selected:
        connection.execute(
            """UPDATE ai_version_reviews SET status='draft', reviewed_at=?
               WHERE status='approved'""",
            (now,),
        )
    connection.commit()
    result = fixed_benchmark_summary(connection)
    result["added_count"] = len(selected)
    result["requested_size"] = target_size
    return result


def fixed_benchmark_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    rows = connection.execute(
        "SELECT strata_json FROM ai_audit_benchmark ORDER BY capture_id"
    ).fetchall()
    coverage: dict[str, set[str]] = {
        "album": set(), "subject": set(), "month": set(),
        "confidence": set(), "problem": set(),
    }
    for row in rows:
        try:
            strata = json.loads(row["strata_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        for dimension, values in coverage.items():
            values.update(strata.get(dimension, []))
    versions = ai_version_gates(connection)
    available_capture_count = int(connection.execute(
        """SELECT COUNT(DISTINCT capture_id) FROM ai_analyses
           WHERE status='complete' AND result_json IS NOT NULL"""
    ).fetchone()[0])
    return {
        "capture_count": len(rows),
        "available_capture_count": available_capture_count,
        "coverage": {key: len(values) for key, values in coverage.items()},
        "versions": versions,
    }


def ai_version_gates(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    benchmark_count = int(connection.execute(
        "SELECT COUNT(*) FROM ai_audit_benchmark"
    ).fetchone()[0])
    rows = connection.execute(
        f"""WITH latest_results AS (
                  SELECT capture_id, prompt_version, MAX(id) AS analysis_id
                  FROM ai_analyses
                  WHERE status='complete' AND result_json IS NOT NULL
                  GROUP BY capture_id, prompt_version
              )
           SELECT aa.prompt_version, MAX(aa.id) AS latest_id,
                  COUNT(DISTINCT aa.capture_id) AS analyzed,
                  SUM(CASE WHEN aa.user_verdict IS NOT NULL THEN 1 ELSE 0 END)
                      AS reviewed,
                  SUM(CASE WHEN aa.user_verdict='inaccurate' THEN 1 ELSE 0 END)
                      AS inaccurate,
                  SUM(CASE WHEN (aa.audit_bits IS NULL
                                     OR (aa.audit_bits & {AUDIT_RISK_MASK}) != 0)
                                AND aa.user_verdict IS NULL THEN 1 ELSE 0 END)
                      AS unresolved_risk,
                  avr.status AS review_status, avr.note, avr.reviewed_at
           FROM latest_results latest
           JOIN ai_analyses aa ON aa.id=latest.analysis_id
           JOIN ai_audit_benchmark benchmark ON benchmark.capture_id=aa.capture_id
           LEFT JOIN ai_version_reviews avr ON avr.prompt_version=aa.prompt_version
           GROUP BY aa.prompt_version ORDER BY latest_id DESC"""
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        analyzed = int(item["analyzed"] or 0)
        reviewed = int(item["reviewed"] or 0)
        inaccurate = int(item["inaccurate"] or 0)
        item["benchmark_count"] = benchmark_count
        item["analysis_coverage"] = round(
            analyzed * 100 / benchmark_count, 1
        ) if benchmark_count else 0.0
        item["review_coverage"] = round(
            reviewed * 100 / analyzed, 1
        ) if analyzed else 0.0
        item["inaccurate_rate"] = round(
            inaccurate * 100 / reviewed, 1
        ) if reviewed else None
        blockers = []
        if benchmark_count < 10:
            blockers.append("固定基准少于 10 张")
        if item["analysis_coverage"] < 80:
            blockers.append("基准分析覆盖率低于 80%")
        if reviewed < min(10, benchmark_count):
            blockers.append("人工复核少于 10 张")
        if item["review_coverage"] < 80:
            blockers.append("人工复核覆盖率低于 80%")
        if item["inaccurate_rate"] is None or item["inaccurate_rate"] > 10:
            blockers.append("不准确率尚未确认低于 10%")
        if int(item["unresolved_risk"] or 0) > 0:
            blockers.append("仍有未复核高风险结果")
        item["gate_blockers"] = blockers
        item["eligible_for_expansion"] = not blockers
        item["review_status"] = item["review_status"] or "draft"
        result.append(item)
    return result


def save_ai_version_review(
    connection: sqlite3.Connection,
    prompt_version: str,
    status: str,
    note: str | None = None,
) -> dict[str, Any]:
    clean_version = prompt_version.strip()
    if not clean_version or len(clean_version) > 100:
        raise ValueError("提示词版本无效")
    if status not in {"draft", "approved", "rejected"}:
        raise ValueError("版本结论无效")
    gate = next(
        (item for item in ai_version_gates(connection)
         if item["prompt_version"] == clean_version),
        None,
    )
    if gate is None:
        raise ValueError("固定基准集中没有该版本结果")
    if status == "approved" and not gate["eligible_for_expansion"]:
        raise ValueError("该版本尚未通过扩大批次质量门禁")
    clean_note = note.strip()[:1000] if note and note.strip() else None
    reviewed_at = utc_now()
    connection.execute(
        """INSERT INTO ai_version_reviews(prompt_version,status,note,reviewed_at)
           VALUES (?,?,?,?) ON CONFLICT(prompt_version) DO UPDATE SET
             status=excluded.status, note=excluded.note,
             reviewed_at=excluded.reviewed_at""",
        (clean_version, status, clean_note, reviewed_at),
    )
    connection.commit()
    return {
        "prompt_version": clean_version, "status": status,
        "note": clean_note, "reviewed_at": reviewed_at,
    }


def ai_audit_facets(connection: sqlite3.Connection) -> dict[str, Any]:
    complete = "aa.status='complete' AND aa.result_json IS NOT NULL"
    albums = [dict(row) for row in connection.execute(
        f"""SELECT e.id, e.proposed_name AS name, COUNT(DISTINCT aa.id) AS count
            FROM ai_analyses aa JOIN event_captures ec ON ec.capture_id=aa.capture_id
            JOIN events e ON e.id=ec.event_id
            WHERE {complete} AND e.status!='archived'
            GROUP BY e.id ORDER BY count DESC, e.proposed_name LIMIT 200"""
    )]
    subjects = [dict(row) for row in connection.execute(
        f"""SELECT td.name, COUNT(DISTINCT aa.id) AS count
            FROM ai_analyses aa JOIN capture_tags ct ON ct.capture_id=aa.capture_id
            JOIN tag_definitions td ON td.id=ct.tag_id AND td.dimension='subject'
            WHERE {complete} AND ct.source='analysis'
            GROUP BY td.name ORDER BY count DESC, td.name LIMIT 200"""
    )]
    months = [dict(row) for row in connection.execute(
        f"""SELECT substr(c.captured_at,1,7) AS name, COUNT(*) AS count
            FROM ai_analyses aa JOIN captures c ON c.id=aa.capture_id
            WHERE {complete} AND c.captured_at IS NOT NULL
            GROUP BY substr(c.captured_at,1,7) ORDER BY name DESC"""
    )]
    return {"albums": albums, "subjects": subjects, "months": months}
