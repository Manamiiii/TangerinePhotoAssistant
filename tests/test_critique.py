import unittest

from tangerine_photo_assistant.critique import build_structured_critique


class StructuredCritiqueTests(unittest.TestCase):
    def test_existing_v4_result_is_normalized_without_forced_pairing(self) -> None:
        result = build_structured_critique({
            "subject_type": "人像",
            "quality_summary": "主体清楚，背景稍乱。",
            "visible_problems": [{
                "name": "背景干扰", "severity": "medium",
                "evidence": "人物轮廓与树枝重叠", "confidence": 0.72,
            }],
            "shooting_advice": [{
                "suggestion": "向侧面移动半步", "reason": "简化背景",
                "exif_basis": "135mm",
            }],
            "lightroom_suggestions": [{
                "adjustment": "主体蒙版", "direction": "+0.15 EV",
                "reason": "加强主体分离",
            }],
            "photoshop_needed": False,
            "photoshop_reason": "不需要",
            "overall_confidence": 0.72,
        }, [{
            "code": "slow_shutter_risk", "severity": "warning",
            "message": "快门偏慢", "evidence": {"exposure_seconds": 0.02},
            "inference": True,
        }])

        self.assertEqual(result["observations"][0]["phenomenon"], "背景干扰")
        self.assertEqual(result["observations"][0]["repairability"], "partial")
        self.assertEqual(result["next_time"][0]["reason"], "简化背景")
        self.assertEqual(result["editing"][0]["tool"], "Lightroom")
        self.assertTrue(result["technical_evidence"][0]["inference"])
        self.assertNotIn("reason", result["observations"][0])

    def test_technical_only_capture_keeps_model_status_explicit(self) -> None:
        result = build_structured_critique(None, [{
            "code": "highlight_clipping", "message": "亮部接近纯白",
            "severity": "high", "evidence": {"highlight_clip_pct": 8.2},
        }])
        self.assertFalse(result["has_model_result"])
        self.assertEqual(result["observations"], [])
        self.assertEqual(result["technical_evidence"][0]["source"], "technical")


if __name__ == "__main__":
    unittest.main()
