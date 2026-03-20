"""星上重规划触发与范围控制（规则版，非强化学习）。"""

from __future__ import annotations

from typing import Any


def evaluate_replan_trigger(state: dict[str, float], cfg: dict[str, Any], predicted_gain: float) -> dict[str, Any]:
    """根据当前状态与收益阈值判断是否触发重规划。"""
    replan_cfg = cfg.get("replan", {})
    rules = replan_cfg.get("disturbance_rules", {})
    level = _classify_level(state, rules)
    if level == "NONE":
        return {"trigger": False, "level": level, "window_count": 0, "reason": "no-disturbance"}

    if level != "L3" and predicted_gain < float(replan_cfg.get("gain_threshold", 0)):
        return {"trigger": False, "level": level, "window_count": 0, "reason": "below-gain-threshold"}

    window_levels = replan_cfg.get("window_levels", {})
    return {
        "trigger": True,
        "level": level,
        "window_count": int(window_levels.get(level, 1)),
        "reason": "disturbance-detected",
    }


def _classify_level(state: dict[str, float], rules: dict[str, dict[str, float]]) -> str:
    temp = float(state.get("temp", 0))
    power = float(state.get("power", 0))
    if not rules:
        return "NONE"
    for level in ("L3", "L2", "L1"):
        r = rules.get(level, {})
        if temp >= float(r.get("temp_high", 1e9)) or power >= float(r.get("power_high", 1e9)):
            return level
    return "NONE"

