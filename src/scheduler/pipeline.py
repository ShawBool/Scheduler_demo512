"""静态基线规划主流程编排。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime 
import json
import time
from pathlib import Path

from .config import load_config, validate_config
from .cpsat_improver import improve_schedule
from .data_loader import load_static_task_bundle
from .heuristic_scheduler import build_initial_schedule
from .models import ScheduleResult
from .problem_builder import build_problem
from .result_writer import append_iteration_log, initialize_iteration_log, materialize_att_segments, write_schedule_result
from .thermal_model import SemiEmpiricalThermalModelV1, ThermalCoefficients


def _build_metrics(schedule, unscheduled, all_tasks_count: int, total_key_tasks: int) -> dict[str, float | int]:
    """统计结果指标。

    说明：关键任务总数来自输入任务本身，避免通过字符串猜测导致统计偏差。
    """
    key_total = total_key_tasks
    key_done = sum(1 for item in schedule if item.is_key_task)
    total_value = sum(item.value for item in schedule)
    return {
        "total_value": total_value,
        "scheduled_task_count": len(schedule),
        "unscheduled_task_count": len(unscheduled),
        "scheduled_task_ratio": round(len(schedule) / max(all_tasks_count, 1), 4),
        "key_task_completion_ratio": round(key_done / max(key_total, 1), 4),
    }


def _resolve_initial_temperature(runtime_cfg: dict, output_root: Path) -> float:
    fallback = float(runtime_cfg.get("initial_temperature_fallback", 25.0))
    if str(runtime_cfg.get("thermal_initial_source", "last_state_first")) != "last_state_first":
        return fallback

    last_state_file = output_root / "last_state.json"
    if not last_state_file.exists():
        return fallback

    try:
        payload = json.loads(last_state_file.read_text(encoding="utf-8"))
    except Exception:
        return fallback

    temperature = payload.get("temperature")
    if not isinstance(temperature, (int, float)):
        return fallback

    max_age = float(runtime_cfg.get("replan_state_max_age_sec", 600))
    ts = payload.get("timestamp")
    if isinstance(ts, (int, float)):
        now = time.time()
        if now - float(ts) > max_age:
            return fallback

    return float(temperature)


def _simulate_thermal_metrics(
    schedule: list,
    *,
    task_map: dict,
    capacities: dict[str, int],
    thermal_cfg: dict,
    initial_temperature: float,
) -> dict[str, float]:
    coeff = thermal_cfg.get("coefficients", {})
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(
            a_p=float(coeff.get("a_p", 0.0)),
            a_c=float(coeff.get("a_c", 0.0)),
            lambda_concurrency=float(coeff.get("lambda_concurrency", 0.0)),
            k_cool=float(coeff.get("k_cool", 0.0)),
        ),
        env_temperature=float(thermal_cfg.get("env_temperature", 20.0)),
    )
    warning = float(thermal_cfg.get("warning_threshold", 0.0))
    danger = float(thermal_cfg.get("danger_threshold", warning + 1.0))
    dt = float(thermal_cfg.get("thermal_time_step", 1.0))

    state = {"temperature": float(initial_temperature)}
    peak = state["temperature"]
    warning_steps = 0
    max_warning_steps = 0
    running_warning = 0
    penalty_total = 0.0

    ordered = sorted([x for x in schedule if x.item_type == "BUSINESS"], key=lambda x: (x.start, x.task_id))
    current_time = 0

    for item in ordered:
        idle = max(0, int(item.start - current_time))
        for _ in range(idle):
            state = model.update(
                state,
                {
                    "power_total": 0.0,
                    "cpu_used": 0.0,
                    "gpu_used": 0.0,
                    "cpu_capacity": max(float(capacities.get("cpu", 1)), 1.0),
                    "gpu_capacity": max(float(capacities.get("gpu", 1)), 1.0),
                },
                dt,
            )
            temp = float(state["temperature"])
            peak = max(peak, temp)
            if warning <= temp < danger:
                warning_steps += 1
                running_warning += 1
            else:
                running_warning = 0
            max_warning_steps = max(max_warning_steps, running_warning)
            penalty_total += max(0.0, temp - warning)

        task = task_map[item.task_id]
        for _ in range(int(task.duration)):
            state = model.update(
                state,
                {
                    "power_total": float(task.power),
                    "cpu_used": float(task.cpu),
                    "gpu_used": float(task.gpu),
                    "cpu_capacity": max(float(capacities.get("cpu", 1)), 1.0),
                    "gpu_capacity": max(float(capacities.get("gpu", 1)), 1.0),
                },
                dt,
            )
            temp = float(state["temperature"])
            peak = max(peak, temp)
            if warning <= temp < danger:
                warning_steps += 1
                running_warning += 1
            else:
                running_warning = 0
            max_warning_steps = max(max_warning_steps, running_warning)
            penalty_total += max(0.0, temp - warning)

        current_time = int(item.end)

    return {
        "peak_temperature": float(round(peak, 4)),
        "min_thermal_margin": float(round(danger - peak, 4)),
        "warning_duration": float(round(warning_steps * dt, 4)),
        "max_continuous_warning_duration": float(round(max_warning_steps * dt, 4)),
        "thermal_penalty_total": float(round(penalty_total, 4)),
    }


def run_pipeline(config_path: str, *, seed: int, output_dir: str) -> dict:
    """运行静态基线规划。

    关键流程：
    1. 读配置 + 校验
    2. 读静态输入
    3. 构建问题
    4. 启发式初解
    5. CP-SAT 改进
    6. 写结果与迭代日志
    """
    started = time.perf_counter()

    cfg = load_config(config_path)
    cfg["runtime"]["seed"] = seed
    validate_config(cfg)

    tasks, windows, _ = load_static_task_bundle(cfg)

    constraints = cfg["constraints"]
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    initial_temperature = _resolve_initial_temperature(cfg["runtime"], output_root)
    problem = build_problem(
        tasks=tasks,
        windows=windows,
        horizon=int(cfg["runtime"]["time_horizon"]),
        capacities={
            "cpu": int(constraints["cpu_capacity"]),
            "gpu": int(constraints["gpu_capacity"]),
            "memory": int(constraints["memory_capacity"]),
            "power": int(constraints["power_capacity"]),
        },
        attitude_time_per_degree=float(constraints["attitude_time_per_degree"]),
        thermal_config={
            **dict(constraints.get("thermal", {})),
            "thermal_time_step": float(cfg["runtime"]["thermal_time_step"]),
            "initial_temperature": float(initial_temperature),
            "initial_temperature_fallback": float(cfg["runtime"]["initial_temperature_fallback"]),
            "objective_scaling": dict(constraints.get("objective_scaling", {})),
        },
    )

    heuristic_started = time.perf_counter()
    warm = build_initial_schedule(
        problem,
        seed=seed,
        initial_attitude_angle_deg=float(cfg["runtime"]["initial_attitude_angle_deg"]),
    )
    # 这里打印启发式结果，方便调试和验证初解质量。
    # 使用 asdict 递归转换所有 dataclass 对象
    warm_dict = asdict(warm)
    print(json.dumps(warm_dict, ensure_ascii=False, indent=2))
    heuristic_runtime_ms = int((time.perf_counter() - heuristic_started) * 1000)

    progress_file = output_root / "solver_progress.jsonl"
    initialize_iteration_log(progress_file)

    append_iteration_log(
        progress_file,
        {
            "event_type": "heuristic_initial_solution",
            "phase": "heuristic",
            "iteration": 0,
            "solution": {"schedule": [asdict(item) for item in warm.schedule]},
        },
    )

    append_iteration_log(
        progress_file,
        {
            "event_type": "heuristic_final_solution",
            "phase": "heuristic",
            "iteration": 1,
            "solution": {"schedule": [asdict(item) for item in warm.schedule]},
        },
    )

    improve = improve_schedule(
        problem,
        warm,
        log_path=progress_file,
        timeout_sec=float(cfg["runtime"]["solver_timeout_sec"]),
        progress_every_n=int(cfg["runtime"]["cpsat_log_every_n"]),
        key_task_bonus=float(cfg["objective_weights"]["key_task_bonus"]),
        initial_attitude_angle_deg=float(cfg["runtime"]["initial_attitude_angle_deg"]),
    )

    final_thermal_metrics = _simulate_thermal_metrics(
        improve.schedule,
        task_map=problem.task_map,
        capacities=problem.capacities,
        thermal_cfg=problem.thermal_config,
        initial_temperature=initial_temperature,
    )

    materialized_schedule = materialize_att_segments(
        improve.schedule,
        task_map=problem.task_map,
        initial_attitude_angle_deg=float(cfg["runtime"]["initial_attitude_angle_deg"]),
        attitude_time_per_degree=float(constraints["attitude_time_per_degree"]),
    )

    metrics = _build_metrics(
        improve.schedule,
        improve.unscheduled,
        len(tasks),
        total_key_tasks=sum(1 for t in tasks if t.is_key_task),
    )
    metrics.update(final_thermal_metrics)
    total_runtime_ms = int((time.perf_counter() - started) * 1000)

    solver_summary = {
        "status": improve.solver_status,
        "objective_value": improve.objective_value,
        "objective_breakdown": improve.objective_breakdown,
        "heuristic_runtime_ms": heuristic_runtime_ms,
        "cpsat_runtime_ms": improve.runtime_ms,
        "total_runtime_ms": total_runtime_ms,
        "iteration_log_count": improve.iteration_log_count,
        "best_effort": improve.solver_status in {"FEASIBLE", "UNKNOWN"},
    }

    append_iteration_log(
        progress_file,
        {
            "event_type": "terminal",
            "phase": "terminal",
            "iteration": improve.iteration_log_count,
            "objective_value": improve.objective_value,
            "scheduled_task_count": len(improve.schedule),
            "key_task_scheduled_count": sum(1 for x in improve.schedule if x.is_key_task),
            "unscheduled_task_count": len(improve.unscheduled),
            "feasible": improve.solver_status in {"OPTIMAL", "FEASIBLE"},
            "improvement_delta": 0,
            "note": improve.solver_status.lower(),
        },
    )

    result = ScheduleResult(
        schedule=materialized_schedule,
        unscheduled=improve.unscheduled,
        metrics=metrics,
        solver_summary=solver_summary,
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 1. 生成带时间戳的持久化文件（永不覆盖）
    history_file = output_root / f"schedule_{timestamp}.json"

    return write_schedule_result(history_file, result)
