"""静态基线规划主流程编排。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime 
import time
from pathlib import Path

from .config import load_config, validate_config
from .cpsat_improver import improve_schedule
from .data_loader import load_static_task_bundle
from .heuristic_scheduler import build_initial_schedule
from .models import ScheduleResult
from .problem_builder import build_problem
from .result_writer import append_iteration_log, initialize_iteration_log, materialize_att_segments, write_schedule_result


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
    )

    heuristic_started = time.perf_counter()
    warm = build_initial_schedule(
        problem,
        seed=seed,
        initial_attitude_angle_deg=float(cfg["runtime"]["initial_attitude_angle_deg"]),
    )
    heuristic_runtime_ms = int((time.perf_counter() - heuristic_started) * 1000)

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

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
    total_runtime_ms = int((time.perf_counter() - started) * 1000)

    solver_summary = {
        "status": improve.solver_status,
        "objective_value": improve.objective_value,
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
