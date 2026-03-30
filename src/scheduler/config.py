"""静态基线规划配置加载与校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _default_thermal_coefficients() -> dict[str, float]:
    return {
        "a_p": 0.002,
        "a_c": 0.03,
        "lambda_concurrency": 0.01,
        "k_cool": 0.005,
    }


def _default_objective_scaling() -> dict[str, list[float]]:
    return {
        "task_value": [0.0, 100.0],
        "completion": [0.0, 1.0],
        "association": [0.0, 1.0],
        "thermal_safety": [0.0, 1.0],
        "power_smoothing": [0.0, 1.0],
        "resource_utilization": [0.0, 1.0],
        "smoothness": [0.0, 1.0],
    }


def load_config(path: str | Path) -> dict[str, Any]:
    """加载配置目录。

    说明：
    1. 一期仅做静态基线规划，因此只依赖 runtime/constraints/logging。
    2. objective_weights 仍保留，便于控制关键任务权重与收益权重。
    """
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = PROJECT_ROOT / cfg_path

    if not cfg_path.is_dir():
        raise ValueError(f"config path must be directory: {cfg_path}")

    runtime = _read_json(cfg_path / "runtime.json")
    constraints = _read_json(cfg_path / "constraints.json")
    logging_cfg = _read_json(cfg_path / "logging.json")

    # 一期默认目标权重，避免额外配置文件缺失导致程序无法运行。
    objective_weights = {
        "task_value": 1.0,
        "key_task_bonus": 300.0,
        "attitude_switch_penalty": 1.0,
    }

    cfg = {
        "runtime": runtime,
        "constraints": constraints,
        "logging": logging_cfg,
        "objective_weights": objective_weights,
    }

    runtime.setdefault("input_mode", "static")
    runtime.setdefault("seed", 666)
    runtime.setdefault("time_step", 1)
    runtime.setdefault("time_horizon", 240)
    runtime.setdefault("data_dir", "data")
    runtime.setdefault("tasks_file", "latest_small_tasks_pool.json")
    runtime.setdefault("windows_file", "latest_windows.json")
    runtime.setdefault("solver_timeout_sec", 30)
    runtime.setdefault("solver_progress_every_n_solutions", 10)
    runtime.setdefault("heuristic_log_every_n", int(runtime["solver_progress_every_n_solutions"]))
    runtime.setdefault("cpsat_log_every_n", int(runtime["solver_progress_every_n_solutions"]))
    runtime.setdefault("thermal_time_step", int(runtime["time_step"]))
    runtime.setdefault("initial_temperature_fallback", 25.0)
    runtime.setdefault("thermal_initial_source", "last_state_first")
    runtime.setdefault("replan_state_max_age_sec", 600)

    data_dir = Path(str(runtime["data_dir"]))
    runtime.setdefault("static_tasks_file", str(data_dir / str(runtime["tasks_file"])))
    runtime.setdefault("static_windows_file", str(data_dir / str(runtime["windows_file"])))

    thermal_cfg = constraints.setdefault("thermal", {})
    thermal_cfg.setdefault("danger_threshold", 100.0)
    thermal_cfg.setdefault("warning_threshold", float(thermal_cfg["danger_threshold"]) - 10.0)
    thermal_cfg.setdefault("max_warning_duration", 60)
    thermal_cfg.setdefault("env_temperature", 20.0)
    coefficients = thermal_cfg.setdefault("coefficients", {})
    for key, value in _default_thermal_coefficients().items():
        coefficients.setdefault(key, value)

    objective_scaling = constraints.setdefault("objective_scaling", _default_objective_scaling())
    if not isinstance(objective_scaling, dict):
        constraints["objective_scaling"] = _default_objective_scaling()
    else:
        for key, default_range in _default_objective_scaling().items():
            value = objective_scaling.get(key)
            if not isinstance(value, list) or len(value) != 2:
                objective_scaling[key] = list(default_range)

    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    """校验一期静态规划配置。

    这里坚持“尽量早失败”的原则，让错误在配置阶段就暴露，
    而不是推迟到求解阶段才报模糊错误。
    """
    for section in ("runtime", "constraints", "logging", "objective_weights"):
        if section not in cfg:
            raise ValueError(f"missing required config section: {section}")

    runtime = cfg["runtime"]
    if str(runtime.get("input_mode", "static")).lower() != "static":
        raise ValueError("phase-1 only supports runtime.input_mode=static")

    horizon = runtime.get("time_horizon")
    if not isinstance(horizon, int) or horizon <= 0:
        raise ValueError("runtime.time_horizon must be positive integer")

    timeout_sec = runtime.get("solver_timeout_sec")
    if not isinstance(timeout_sec, (int, float)) or timeout_sec <= 0:
        raise ValueError("runtime.solver_timeout_sec must be positive")

    initial_attitude = runtime.get("initial_attitude_angle_deg")
    if not isinstance(initial_attitude, (int, float)) or not (0 <= float(initial_attitude) <= 360):
        raise ValueError("runtime.initial_attitude_angle_deg must be number in [0, 360]")

    progress_n = runtime.get("solver_progress_every_n_solutions")
    if not isinstance(progress_n, int) or progress_n <= 0:
        raise ValueError("runtime.solver_progress_every_n_solutions must be positive integer")

    heuristic_n = runtime.get("heuristic_log_every_n")
    if not isinstance(heuristic_n, int) or heuristic_n <= 0:
        raise ValueError("runtime.heuristic_log_every_n must be positive integer")

    cpsat_n = runtime.get("cpsat_log_every_n")
    if not isinstance(cpsat_n, int) or cpsat_n <= 0:
        raise ValueError("runtime.cpsat_log_every_n must be positive integer")

    thermal_step = runtime.get("thermal_time_step")
    if not isinstance(thermal_step, (int, float)) or float(thermal_step) <= 0:
        raise ValueError("runtime.thermal_time_step must be positive")

    replan_state_max_age_sec = runtime.get("replan_state_max_age_sec")
    if not isinstance(replan_state_max_age_sec, (int, float)) or float(replan_state_max_age_sec) < 0:
        raise ValueError("runtime.replan_state_max_age_sec must be non-negative")

    constraints = cfg["constraints"]
    for key in ("cpu_capacity", "gpu_capacity", "memory_capacity", "power_capacity", "attitude_time_per_degree"):
        value = constraints.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"constraints.{key} must be positive")

    thermal_cfg = constraints.get("thermal")
    if thermal_cfg is None:
        thermal_cfg = {}
        constraints["thermal"] = thermal_cfg
    if not isinstance(thermal_cfg, dict):
        raise ValueError("constraints.thermal must be object")
    if "danger_threshold" not in thermal_cfg:
        thermal_cfg["danger_threshold"] = 100.0
    if "warning_threshold" not in thermal_cfg:
        thermal_cfg["warning_threshold"] = float(thermal_cfg["danger_threshold"]) - 10.0
    if "max_warning_duration" not in thermal_cfg:
        thermal_cfg["max_warning_duration"] = 60
    if "coefficients" not in thermal_cfg:
        thermal_cfg["coefficients"] = _default_thermal_coefficients()

    warning = thermal_cfg.get("warning_threshold")
    danger = thermal_cfg.get("danger_threshold")
    if not isinstance(warning, (int, float)) or not isinstance(danger, (int, float)):
        raise ValueError("constraints.thermal.warning_threshold and danger_threshold must be number")
    if float(warning) >= float(danger):
        raise ValueError("constraints.thermal.warning_threshold must be less than danger_threshold")

    max_warning_duration = thermal_cfg.get("max_warning_duration")
    if not isinstance(max_warning_duration, (int, float)) or float(max_warning_duration) < 0:
        raise ValueError("constraints.thermal.max_warning_duration must be non-negative")

    coefficients = thermal_cfg.get("coefficients")
    if not isinstance(coefficients, dict):
        raise ValueError("constraints.thermal.coefficients must be object")
    for key in _default_thermal_coefficients():
        value = coefficients.get(key)
        if not isinstance(value, (int, float)):
            raise ValueError(f"constraints.thermal.coefficients.{key} must be number")

    objective_weights = cfg["objective_weights"]
    for key in ("task_value", "key_task_bonus", "attitude_switch_penalty"):
        value = objective_weights.get(key)
        if not isinstance(value, (int, float)):
            raise ValueError(f"objective_weights.{key} must be number")

    objective_scaling = constraints.get("objective_scaling")
    if not isinstance(objective_scaling, dict):
        raise ValueError("constraints.objective_scaling must be object")
    for key in _default_objective_scaling().keys():
        bounds = objective_scaling.get(key)
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise ValueError(f"constraints.objective_scaling.{key} must be [min, max]")
        low = bounds[0]
        high = bounds[1]
        if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
            raise ValueError(f"constraints.objective_scaling.{key} bounds must be numbers")
        if float(high) <= float(low):
            raise ValueError(f"constraints.objective_scaling.{key} max must be greater than min")
