from __future__ import annotations

from typing import Any


LIMITED_REPAIR_TERMS = ("闭眼", "失焦", "运动模糊", "抖动", "遮挡", "表情", "姿势")
PARTIAL_REPAIR_TERMS = (
    "曝光", "高光", "阴影", "暗部", "噪点", "白平衡", "色偏",
    "地平线", "构图", "背景", "裁切",
)


def _text(value: object) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    return text or None


def _confidence(value: object) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(1.0, confidence)), 2)


def classify_repairability(name: str) -> tuple[str, str]:
    if any(term in name for term in LIMITED_REPAIR_TERMS):
        return "limited", "后期难以真正恢复"
    if any(term in name for term in PARTIAL_REPAIR_TERMS):
        return "partial", "后期可部分改善"
    return "unknown", "需要结合画面人工判断"


def build_structured_critique(
    result: dict[str, Any] | None,
    technical_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize existing model output for review UI without inventing pairings."""
    result = result if isinstance(result, dict) else {}
    observations: list[dict[str, Any]] = []
    for raw in result.get("visible_problems") or []:
        if not isinstance(raw, dict) or not _text(raw.get("name")):
            continue
        name = _text(raw.get("name")) or "画面问题"
        repairability, repairability_label = classify_repairability(name)
        observations.append({
            "phenomenon": name,
            "evidence": _text(raw.get("evidence")),
            "severity": _text(raw.get("severity")),
            "confidence": _confidence(raw.get("confidence")),
            "repairability": repairability,
            "repairability_label": repairability_label,
            "source": "model",
        })

    next_time: list[dict[str, Any]] = []
    for raw in result.get("shooting_advice") or []:
        if not isinstance(raw, dict) or not _text(raw.get("suggestion")):
            continue
        next_time.append({
            "suggestion": _text(raw.get("suggestion")),
            "reason": _text(raw.get("reason")),
            "exif_basis": _text(raw.get("exif_basis")),
            "source": "model",
        })

    editing: list[dict[str, Any]] = []
    for raw in result.get("lightroom_suggestions") or []:
        if not isinstance(raw, dict) or not _text(raw.get("adjustment")):
            continue
        editing.append({
            "adjustment": _text(raw.get("adjustment")),
            "direction": _text(raw.get("direction")),
            "reason": _text(raw.get("reason")),
            "tool": "Lightroom",
        })

    evidence = [{
        "code": _text(issue.get("code")) or "technical_issue",
        "message": _text(issue.get("message")) or "技术检测提示",
        "severity": _text(issue.get("severity")),
        "evidence": issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {},
        "inference": bool(issue.get("inference", False)),
        "source": "technical",
    } for issue in technical_issues if isinstance(issue, dict)]

    return {
        "summary": _text(result.get("quality_summary")),
        "subject_type": _text(result.get("subject_type")),
        "overall_confidence": _confidence(result.get("overall_confidence")),
        "observations": observations,
        "next_time": next_time,
        "editing": editing,
        "photoshop": {
            "needed": result.get("photoshop_needed") is True,
            "reason": _text(result.get("photoshop_reason")),
        } if result else None,
        "technical_evidence": evidence,
        "has_model_result": bool(result),
    }
