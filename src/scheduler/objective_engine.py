"""多目标归一化与静态权重打分引擎。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


DEFAULT_OBJECTIVE_KEYS = (
    "task_value",
    "completion",
    "association",
    "thermal_safety",
    "power_smoothing",
    "resource_utilization",
    "smoothness",
)

DEFAULT_OBJECTIVE_RANGES: dict[str, tuple[float, float]] = {
    "task_value": (0.0, 100.0),
    "completion": (0.0, 1.0),
    "association": (0.0, 1.0),
    "thermal_safety": (0.0, 1.0),
    "power_smoothing": (0.0, 1.0),
    "resource_utilization": (0.0, 1.0),
    "smoothness": (0.0, 1.0),
}


@dataclass(slots=True)
class ObjectiveScaleConfig:
    ranges: dict[str, tuple[float, float]]
    target_min: float = 0.0
    target_max: float = 100.0


@dataclass(slots=True)
class ObjectiveScoreDetail:
    total_score: float
    normalized: dict[str, float]
    weighted: dict[str, float]


def build_scale_config(
    raw_ranges: Mapping[str, Sequence[float] | tuple[float, float]] | None,
    *,
    target_min: float = 0.0,
    target_max: float = 100.0,
) -> ObjectiveScaleConfig:
    ranges = dict(DEFAULT_OBJECTIVE_RANGES)
    if raw_ranges:
        for key in DEFAULT_OBJECTIVE_KEYS:
            value = raw_ranges.get(key)
            if value is None or len(value) != 2:
                continue
            low = float(value[0])
            high = float(value[1])
            if high <= low:
                continue
            ranges[key] = (low, high)
    return ObjectiveScaleConfig(ranges=ranges, target_min=float(target_min), target_max=float(target_max))


def normalize_0_100(raw: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    ratio = (float(raw) - float(lower)) / (float(upper) - float(lower))
    return max(0.0, min(100.0, ratio * 100.0))


def normalize_to_scale(raw: float, lower: float, upper: float, *, target_min: float, target_max: float) -> float:
    if upper <= lower:
        return float(target_min)
    ratio = (float(raw) - float(lower)) / (float(upper) - float(lower))
    ratio = max(0.0, min(1.0, ratio))
    return float(target_min) + (float(target_max) - float(target_min)) * ratio


def _sanitize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    sanitized = {k: max(0.0, float(v)) for k, v in weights.items()}
    total = sum(sanitized.values())
    if total <= 0:
        return {k: 0.0 for k in DEFAULT_OBJECTIVE_KEYS}
    return {k: sanitized.get(k, 0.0) / total for k in DEFAULT_OBJECTIVE_KEYS}


def score_candidate(
    *,
    objective_raw: Mapping[str, float],
    objective_ranges: Mapping[str, tuple[float, float]],
    weights: Mapping[str, float],
) -> ObjectiveScoreDetail:
    normalized: dict[str, float] = {}
    weighted: dict[str, float] = {}
    w = _sanitize_weights(weights)
    scale_cfg = build_scale_config(objective_ranges)

    for key in DEFAULT_OBJECTIVE_KEYS:
        raw = float(objective_raw.get(key, 0.0))
        lower, upper = scale_cfg.ranges.get(key, DEFAULT_OBJECTIVE_RANGES[key])
        norm = normalize_to_scale(
            raw=raw,
            lower=float(lower),
            upper=float(upper),
            target_min=scale_cfg.target_min,
            target_max=scale_cfg.target_max,
        )
        normalized[key] = norm
        weighted[key] = norm * w.get(key, 0.0)

    return ObjectiveScoreDetail(total_score=sum(weighted.values()), normalized=normalized, weighted=weighted)
