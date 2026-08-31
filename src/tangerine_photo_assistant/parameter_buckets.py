"""One set of half-open EXIF ranges for charts, insights and exact drill-down.

These are presentation ranges, never EXIF corrections. Missing 35mm-equivalent
focal lengths stay unknown instead of mixing physical and equivalent lengths.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ParameterBuckets:
    column: str
    dimension_label: str
    # Exclusive upper bounds; None is the unbounded last range.
    ranges: tuple[tuple[float | None, str], ...]

    def label(self, value: float | None) -> str:
        if value is None or not isfinite(float(value)) or value <= 0:
            return "未知"
        return next(label for upper, label in self.ranges if upper is None or value < upper)

    def case_sql(self, prefix: str = "") -> str:
        column = prefix + self.column
        parts = [f"CASE WHEN {column} IS NULL OR {column}<=0 THEN '未知'"]
        for upper, label in self.ranges:
            if upper is None:
                parts.append(f"ELSE '{label}' END")
            else:
                parts.append(f"WHEN {column}<{upper!r} THEN '{label}'")
        return " ".join(parts)

    def filter_sql(self, label: str, prefix: str = "f.") -> str:
        column = prefix + self.column
        if label == "未知":
            return f"({column} IS NULL OR {column}<=0)"
        lower = 0.0
        for upper, current in self.ranges:
            if current == label:
                lower_test = f"{column}>0" if lower == 0 else f"{column}>={lower!r}"
                return lower_test if upper is None else f"{lower_test} AND {column}<{upper!r}"
            if upper is not None:
                lower = upper
        raise ValueError("复盘条件不受支持")

    def distribution_sql(self) -> str:
        return f"""SELECT {self.case_sql()} AS bucket,
                          COUNT(*) AS count, ROUND(AVG(technical_score), 1) AS average_score
                   FROM capture_exif GROUP BY bucket
                   ORDER BY bucket='未知', MIN({self.column})"""


PARAMETER_BUCKETS = {
    "focal": ParameterBuckets("focal_length_35mm", "等效焦段", (
        (24, "<24mm"), (35, "24–<35mm"), (50, "35–<50mm"),
        (85, "50–<85mm"), (135, "85–<135mm"), (200, "135–<200mm"), (None, "≥200mm"),
    )),
    "aperture": ParameterBuckets("f_number", "光圈", (
        (2, "<f/2"), (2.8, "f/2–<2.8"), (4, "f/2.8–<4"),
        (5.6, "f/4–<5.6"), (8, "f/5.6–<8"), (11, "f/8–<11"),
        (16, "f/11–<16"), (None, "≥f/16"),
    )),
    "iso": ParameterBuckets("iso", "ISO", (
        (200, "<200"), (400, "200–<400"), (800, "400–<800"),
        (1600, "800–<1600"), (3200, "1600–<3200"), (6400, "3200–<6400"),
        (None, "≥6400"),
    )),
    "shutter": ParameterBuckets("exposure_time", "快门", (
        (1 / 1000, "<1/1000s"), (1 / 250, "1/1000–<1/250s"),
        (1 / 125, "1/250–<1/125s"), (1 / 60, "1/125–<1/60s"),
        (1 / 15, "1/60–<1/15s"), (1, "1/15–<1s"), (None, "≥1s"),
    )),
}
