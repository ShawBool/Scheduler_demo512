"""配置加载与校验。"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL_KEYS = (
    "runtime",
    "simulation",
    "constraints",
    "objective_weights",
    "logging",
)


ALLOWED_INPUT_MODES = {"static", "simulation"}


LEGACY_SIM_KEYS = (
    "sequence_count_min",
    "sequence_count_max",
    "sequence_task_min",
    "sequence_task_max",
    "dag_chains_per_sequence_min",
    "dag_chains_per_sequence_max",
    "window_share_task_min",
    "window_share_task_max",
    "predecessor_probability",
)


STRUCTURED_TASK_RATIO_DEFAULT = 0.82
STRUCTURED_TASK_RATIO_MIN = 0.6


def _ensure_positive(value: Any, key: str) -> None:
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{key} must be positive")


def _as_float(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _avg_from_keys(sim: dict[str, Any], key_min: str, key_max: str, default: float) -> float:
    return (_as_float(sim.get(key_min), default) + _as_float(sim.get(key_max), default)) / 2.0


def _normalize_structured_task_ratio(
    sim: dict[str, Any], *, emit_warnings: bool, reject_below_min: bool
) -> None:
    ratio = _as_float(sim.get("structured_task_ratio"), STRUCTURED_TASK_RATIO_DEFAULT)
    if ratio < STRUCTURED_TASK_RATIO_MIN:
        if reject_below_min:
            raise ValueError(f"structured_task_ratio must be >= {STRUCTURED_TASK_RATIO_MIN:.1f}")
        if emit_warnings:
            warnings.warn(
                f"structured_task_ratio={ratio:.3f} is below minimum {STRUCTURED_TASK_RATIO_MIN:.1f}; clamped to {STRUCTURED_TASK_RATIO_MIN:.1f}",
                UserWarning,
                stacklevel=2,
            )
        ratio = STRUCTURED_TASK_RATIO_MIN
    sim["structured_task_ratio"] = ratio


def _apply_simulation_compatibility(
    sim: dict[str, Any], *, emit_warnings: bool, reject_below_min: bool = False
) -> None:
    migrated_from_legacy: list[str] = []

    if "structured_task_ratio" not in sim:
        if any(k in sim for k in ("sequence_count_min", "sequence_count_max", "sequence_task_min", "sequence_task_max")):
            avg_seq_count = _avg_from_keys(sim, "sequence_count_min", "sequence_count_max", 2.5)
            avg_seq_size = _avg_from_keys(sim, "sequence_task_min", "sequence_task_max", 15.0)
            avg_task_count = _avg_from_keys(sim, "task_count_min", "task_count_max", 80.0)
            if avg_task_count <= 0:
                sim["structured_task_ratio"] = 0.65
            else:
                sim["structured_task_ratio"] = _clamp01((avg_seq_count * avg_seq_size) / avg_task_count)
            migrated_from_legacy.append("sequence*")
        elif "free_task_ratio" in sim:
            sim["structured_task_ratio"] = _clamp01(1.0 - _as_float(sim.get("free_task_ratio"), 0.35))
            migrated_from_legacy.append("free_task_ratio")
        else:
            sim["structured_task_ratio"] = STRUCTURED_TASK_RATIO_DEFAULT

    if "dependency_density" not in sim:
        if "predecessor_probability" in sim:
            sim["dependency_density"] = _clamp01(_as_float(sim.get("predecessor_probability"), 0.6))
            migrated_from_legacy.append("predecessor_probability")
        elif any(k in sim for k in ("dag_chains_per_sequence_min", "dag_chains_per_sequence_max")):
            avg_chains = _avg_from_keys(sim, "dag_chains_per_sequence_min", "dag_chains_per_sequence_max", 3.0)
            # 旧的 chains 越多，跨链附加依赖密度通常越低，按经验线性映射到 [0.2, 0.8]。
            sim["dependency_density"] = _clamp01(max(0.2, min(0.8, 0.9 - 0.1 * avg_chains)))
            migrated_from_legacy.append("dag_chains*")
        else:
            sim["dependency_density"] = 0.6

    if "window_reuse_target" not in sim:
        if "window_share_task_min" in sim or "window_share_task_max" in sim:
            min_share = _as_float(sim.get("window_share_task_min"), 2.0)
            max_share = _as_float(sim.get("window_share_task_max"), max(min_share, 2.0))
            sim["window_reuse_target"] = max(1.0, (min_share + max(max_share, min_share)) / 2.0)
            migrated_from_legacy.append("window_share_task*")
        else:
            sim["window_reuse_target"] = 3.0

    if "key_task_probability" not in sim:
        sim["key_task_probability"] = 0.01

    if "max_hard_key_tasks" not in sim:
        sim["max_hard_key_tasks"] = 1

    _normalize_structured_task_ratio(
        sim,
        emit_warnings=emit_warnings,
        reject_below_min=reject_below_min,
    )

    # structured_task_ratio 作为主控面，始终回写 free_task_ratio 供兼容读路径使用。
    sim["free_task_ratio"] = 1.0 - _clamp01(_as_float(sim.get("structured_task_ratio"), STRUCTURED_TASK_RATIO_DEFAULT))

    if emit_warnings and migrated_from_legacy:
        unique_from = sorted(set(migrated_from_legacy))
        warnings.warn(
            "legacy simulation keys detected and migrated to new controls "
            f"(structured_task_ratio/dependency_density/window_reuse_target): {', '.join(unique_from)}",
            UserWarning,
            stacklevel=2,
        )


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if config_path.is_dir():
        file_map = {
            "runtime": "runtime.json",
            "simulation": "simulation.json",
            "constraints": "constraints.json",
            "objective_weights": "objective_weights.json",
            "replan": "replan.json",
            "logging": "logging.json",
        }
        cfg: dict[str, Any] = {}
        for section, name in file_map.items():
            with (config_path / name).open("r", encoding="utf-8") as f:
                cfg[section] = json.load(f)
    else:
        with config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)

    cfg.setdefault("runtime", {})
    cfg["runtime"].setdefault("solver_timeout_sec", 10)
    cfg["runtime"].setdefault("time_step", 1)
    cfg["runtime"].setdefault("input_mode", "static")
    cfg["runtime"].setdefault("data_dir", "data")
    cfg["runtime"].setdefault("tasks_file", "latest_small_tasks_pool.json")
    cfg["runtime"].setdefault("windows_file", "latest_windows.json")
    data_dir = Path(str(cfg["runtime"].get("data_dir", "data")))
    cfg["runtime"].setdefault("static_tasks_file", str(data_dir / str(cfg["runtime"].get("tasks_file", "latest_small_tasks_pool.json"))))
    cfg["runtime"].setdefault("static_windows_file", str(data_dir / str(cfg["runtime"].get("windows_file", "latest_windows.json"))))
    cfg.setdefault("objective_weights", {})
    cfg["objective_weights"].setdefault("task_value", 1)
    cfg["objective_weights"].setdefault("lateness_penalty", 0)
    cfg.setdefault("replan", {})
    cfg.setdefault("simulation", {})
    _apply_simulation_compatibility(cfg["simulation"], emit_warnings=True)
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"missing required keys: {missing}")

    runtime = cfg.get("runtime", {})
    input_mode = str(runtime.get("input_mode", "static")).strip().lower()
    if input_mode not in ALLOWED_INPUT_MODES:
        raise ValueError("input_mode must be one of: static, simulation")

    # 校验阶段避免修改输入对象，且不再重复发兼容 warning。
    sim = dict(cfg["simulation"])
    _apply_simulation_compatibility(sim, emit_warnings=False, reject_below_min=True)
    if sim["task_count_min"] > sim["task_count_max"]:
        raise ValueError("task_count_min must be <= task_count_max")
    dag_group_min = sim.get("dag_group_min")
    dag_group_max = sim.get("dag_group_max")
    if (
        isinstance(dag_group_min, (int, float))
        and isinstance(dag_group_max, (int, float))
        and dag_group_min > 0
        and dag_group_max > 0
        and dag_group_min > dag_group_max
    ):
        raise ValueError("dag_group_min must be <= dag_group_max")

    _ensure_positive(sim.get("visibility_window_count_min", 1), "visibility_window_count_min")
    _ensure_positive(sim.get("visibility_window_count_max", 1), "visibility_window_count_max")
    _ensure_positive(sim.get("visibility_window_duration_min", 1), "visibility_window_duration_min")
    _ensure_positive(sim.get("visibility_window_duration_max", 1), "visibility_window_duration_max")
    _ensure_positive(sim.get("window_reuse_target", 1), "window_reuse_target")
    if sim.get("visibility_window_count_min", 1) > sim.get("visibility_window_count_max", 1):
        raise ValueError("visibility_window_count_min must be <= visibility_window_count_max")
    if sim.get("visibility_window_duration_min", 1) > sim.get("visibility_window_duration_max", 1):
        raise ValueError("visibility_window_duration_min must be <= visibility_window_duration_max")
    structured_task_ratio = sim.get("structured_task_ratio")
    if not isinstance(structured_task_ratio, (int, float)) or not (0 <= float(structured_task_ratio) <= 1):
        raise ValueError("structured_task_ratio must be in [0, 1]")
    dependency_density = sim.get("dependency_density")
    if not isinstance(dependency_density, (int, float)) or not (0 <= float(dependency_density) <= 1):
        raise ValueError("dependency_density must be in [0, 1]")

    key_task_probability = sim.get("key_task_probability")
    if not isinstance(key_task_probability, (int, float)) or not (0 <= float(key_task_probability) <= 1):
        raise ValueError("key_task_probability must be in [0, 1]")

    max_hard_key_tasks = sim.get("max_hard_key_tasks")
    if not isinstance(max_hard_key_tasks, int):
        raise ValueError("max_hard_key_tasks must be an integer")
    if max_hard_key_tasks < 0:
        raise ValueError("max_hard_key_tasks must be >= 0")

    free_task_ratio = sim.get("free_task_ratio")
    if free_task_ratio is not None and (not isinstance(free_task_ratio, (int, float)) or not (0 <= float(free_task_ratio) <= 1)):
        raise ValueError("free_task_ratio must be in [0, 1]")

    constraints = cfg["constraints"]
    numeric_positive_keys = (
        "cpu_capacity",
        "gpu_capacity",
        "memory_capacity",
        "storage_capacity",
        "bus_capacity",
        "power_capacity",
        "thermal_capacity",
        "attitude_time_per_degree",
    )
    for key in numeric_positive_keys:
        _ensure_positive(constraints.get(key), key)
