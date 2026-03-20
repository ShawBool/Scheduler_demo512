"""配置加载与校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL_KEYS = (
    "runtime",
    "simulation",
    "constraints",
    "objective_weights",
    "logging",
)


def _ensure_positive(value: Any, key: str) -> None:
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{key} must be positive")


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.setdefault("runtime", {})
    cfg["runtime"].setdefault("solver_timeout_sec", 10)
    cfg["runtime"].setdefault("time_step", 1)
    cfg.setdefault("objective_weights", {})
    cfg["objective_weights"].setdefault("task_value", 1)
    cfg["objective_weights"].setdefault("lateness_penalty", 0)
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"missing required keys: {missing}")

    sim = cfg["simulation"]
    _ensure_positive(sim.get("dag_group_min"), "dag_group_min")
    _ensure_positive(sim.get("dag_group_max"), "dag_group_max")
    if sim["task_count_min"] > sim["task_count_max"]:
        raise ValueError("task_count_min must be <= task_count_max")
    if sim["dag_group_min"] > sim["dag_group_max"]:
        raise ValueError("dag_group_min must be <= dag_group_max")

    constraints = cfg["constraints"]
    numeric_positive_keys = (
        "cpu_capacity",
        "gpu_capacity",
        "memory_capacity",
        "storage_capacity",
        "bus_capacity",
        "max_concurrency_cores",
        "power_capacity",
        "thermal_capacity",
        "attitude_time_per_degree",
    )
    for key in numeric_positive_keys:
        _ensure_positive(constraints.get(key), key)
