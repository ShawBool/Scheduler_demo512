"""静态基线规划配置加载与校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config(path: str | Path) -> dict[str, Any]:
    """加载配置目录。

    说明：
    1. 一期仅做静态基线规划，因此只依赖 runtime/constraints/logging/replan。
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
    replan = _read_json(cfg_path / "replan.json")

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
        "replan": replan,
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
    runtime.setdefault("solver_progress_enable", True)
    runtime.setdefault("solver_progress_every_n_solutions", 10)
    runtime.setdefault("heuristic_log_every_n", int(runtime["solver_progress_every_n_solutions"]))
    runtime.setdefault("cpsat_log_every_n", int(runtime["solver_progress_every_n_solutions"]))
    runtime.setdefault("log_full_solution_content", True)

    data_dir = Path(str(runtime["data_dir"]))
    runtime.setdefault("static_tasks_file", str(data_dir / str(runtime["tasks_file"])))
    runtime.setdefault("static_windows_file", str(data_dir / str(runtime["windows_file"])))
    constraints.setdefault("attitude_power_reserve", 0.0)

    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    """校验一期静态规划配置。

    这里坚持“尽量早失败”的原则，让错误在配置阶段就暴露，
    而不是推迟到求解阶段才报模糊错误。
    """
    for section in ("runtime", "constraints", "logging", "objective_weights", "replan"):
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

    constraints = cfg["constraints"]
    for key in ("cpu_capacity", "gpu_capacity", "memory_capacity", "power_capacity", "attitude_time_per_degree"):
        value = constraints.get(key)
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"constraints.{key} must be positive")

    attitude_power_reserve = constraints.get("attitude_power_reserve")
    if not isinstance(attitude_power_reserve, (int, float)) or attitude_power_reserve < 0:
        raise ValueError("constraints.attitude_power_reserve must be non-negative")

    objective_weights = cfg["objective_weights"]
    for key in ("task_value", "key_task_bonus", "attitude_switch_penalty"):
        value = objective_weights.get(key)
        if not isinstance(value, (int, float)):
            raise ValueError(f"objective_weights.{key} must be number")
