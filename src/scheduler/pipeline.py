"""调度流水线入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_config, validate_config
from .data_loader import load_static_task_bundle
from .logging_utils import append_cycle_log, write_schedule_result, write_task_pool, write_visibility_windows
from .planner import plan_baseline
from .replanner import evaluate_replan_trigger


@dataclass
class _PlannerTaskCompat:
    task_id: str
    duration: int
    value: int
    cpu: int
    gpu: int
    memory: int
    power: int
    payload_type_requirements: list[str] = field(default_factory=list)
    payload_id_requirements: list[str] = field(default_factory=list)
    predecessors: list[str] = field(default_factory=list)
    attitude_angle_deg: float = 0.0
    is_key_task: bool = False
    visibility_window: Any = None
    storage: int = 0
    bus: int = 0
    concurrency_cores: int = 0
    thermal_load: int = 0


def _build_planner_tasks(tasks: list[Any]) -> list[_PlannerTaskCompat]:
    compat_tasks: list[_PlannerTaskCompat] = []
    for task in tasks:
        cpu_val = int(getattr(task, "cpu", 0) or 0)
        power_val = int(getattr(task, "power", 0) or 0)
        compat_tasks.append(
            _PlannerTaskCompat(
                task_id=str(task.task_id),
                duration=int(task.duration),
                value=int(task.value),
                cpu=cpu_val,
                gpu=int(getattr(task, "gpu", 0) or 0),
                memory=int(getattr(task, "memory", 0) or 0),
                power=power_val,
                payload_type_requirements=list(getattr(task, "payload_type_requirements", []) or []),
                payload_id_requirements=list(getattr(task, "payload_id_requirements", []) or []),
                predecessors=list(getattr(task, "predecessors", []) or []),
                attitude_angle_deg=float(getattr(task, "attitude_angle_deg", 0.0) or 0.0),
                is_key_task=bool(getattr(task, "is_key_task", False)),
                visibility_window=getattr(task, "visibility_window", None),
                storage=int(getattr(task, "storage", 0) or 0),
                bus=int(getattr(task, "bus", 0) or 0),
                concurrency_cores=int(getattr(task, "concurrency_cores", cpu_val) or 0),
                thermal_load=int(getattr(task, "thermal_load", power_val) or 0),
            )
        )
    return compat_tasks


def run_pipeline(config_path: str = "config", seed: int | None = None, output_dir: str | Path | None = None) -> dict[str, Any]:
    cfg = load_config(config_path)
    validate_config(cfg)

    use_seed = cfg["runtime"].get("seed", 42) if seed is None else seed
    input_mode = str(cfg["runtime"].get("input_mode", "static")).strip().lower()
    if input_mode == "static":
        tasks, windows_map, _ = load_static_task_bundle(cfg)
        visibility_windows = list(windows_map.values())
        horizon = int(cfg["runtime"]["time_horizon"])
    else:
        from .simulation import generate_simulation_snapshot

        simulation_snapshot = generate_simulation_snapshot(cfg, seed=use_seed)
        tasks = simulation_snapshot["tasks"]
        visibility_windows = simulation_snapshot["visibility_windows"]
        horizon = simulation_snapshot["horizon"]
    planner_tasks = _build_planner_tasks(tasks)
    result = plan_baseline(planner_tasks, cfg)

    log_cfg = cfg["logging"]
    out_dir = Path(output_dir) if output_dir is not None else Path(log_cfg.get("output_dir", "output"))
    schedule_file = out_dir / log_cfg.get("schedule_file", "latest_schedule.json")
    cycle_log_file = out_dir / log_cfg.get("cycle_log_file", "cycle_log.jsonl")
    task_pool_file = out_dir / log_cfg.get("task_pool_file", "latest_task_pool.json")
    visibility_windows_file = out_dir / log_cfg.get("visibility_windows_file", "latest_visibility_windows.json")

    write_schedule_result(result, schedule_file)
    write_task_pool(tasks, task_pool_file)
    write_visibility_windows(visibility_windows, visibility_windows_file, seed=use_seed, horizon=horizon)
    log_prefix = f"[pipeline:{input_mode}]"
    print(f"{log_prefix} task pool persisted: {task_pool_file}")
    print(f"{log_prefix} visibility windows persisted: {visibility_windows_file}")
    violations = {
        "missing_key_tasks": _collect_missing_key_tasks(tasks, result),
        "resource_overflow_count": int(result.constraint_stats.get("resource_overflow_count", 0)),
    }

    replan_decision = evaluate_replan_trigger(
        {
            "temp": float(result.constraint_stats.get("unscheduled_count", 0)) + 60.0,
            "power": float(result.constraint_stats.get("resource_overflow_count", 0)) + 50.0,
        },
        cfg,
        predicted_gain=float(max(0, len(result.unscheduled_tasks))),
    )

    effective_segments = result.rolling_segments or [{"start": 0, "end": int(cfg["runtime"]["time_horizon"])}]
    for cycle_id, segment in enumerate(effective_segments, start=1):
        selected_in_seg = [
            x.task_id for x in result.scheduled_items if segment["start"] <= x.start < segment["end"]
        ]
        append_cycle_log(
            cycle_log_file,
            cycle_id=cycle_id,
            state_snapshot={
                "task_pool_size": len(tasks),
                "scheduled_count": len(result.scheduled_items),
                "unscheduled_count": len(result.unscheduled_tasks),
                "time_horizon": int(cfg["runtime"]["time_horizon"]),
                "segment_start": segment["start"],
                "segment_end": segment["end"],
                "replan_decision": replan_decision,
            },
            selected_tasks=selected_in_seg,
            unscheduled_tasks=[x.task_id for x in result.unscheduled_tasks],
            constraint_violations=violations,
            objective_value=result.objective_value,
        )

    return {
        "input_mode": input_mode,
        "scheduled_items": [x.task_id for x in result.scheduled_items],
        "unscheduled_tasks": [x.task_id for x in result.unscheduled_tasks],
        "objective_value": result.objective_value,
        "constraint_stats": result.constraint_stats,
        "rolling_segments": effective_segments,
        "replan_decision": replan_decision,
        "output_dir": str(out_dir),
        "task_pool_file": str(task_pool_file),
        "visibility_windows_file": str(visibility_windows_file),
    }


def _collect_missing_key_tasks(tasks, result) -> list[str]:
    scheduled = {item.task_id for item in result.scheduled_items}
    return [t.task_id for t in tasks if t.is_key_task and t.task_id not in scheduled]
