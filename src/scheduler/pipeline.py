"""调度流水线入口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_config, validate_config
from .logging_utils import append_cycle_log, write_schedule_result
from .planner import plan_baseline
from .replanner import evaluate_replan_trigger
from .simulation import generate_task_pool


def run_pipeline(config_path: str = "config", seed: int | None = None, output_dir: str | Path | None = None) -> dict[str, Any]:
    cfg = load_config(config_path)
    validate_config(cfg)

    use_seed = cfg["runtime"].get("seed", 42) if seed is None else seed
    tasks = generate_task_pool(cfg, seed=use_seed)
    result = plan_baseline(tasks, cfg)

    log_cfg = cfg["logging"]
    out_dir = Path(output_dir) if output_dir is not None else Path(log_cfg.get("output_dir", "output"))
    schedule_file = out_dir / log_cfg.get("schedule_file", "latest_schedule.json")
    cycle_log_file = out_dir / log_cfg.get("cycle_log_file", "cycle_log.jsonl")

    write_schedule_result(result, schedule_file)
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

    for cycle_id, segment in enumerate(result.rolling_segments or [{"start": 0, "end": int(cfg["runtime"]["time_horizon"])}], start=1):
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
        "scheduled_items": [x.task_id for x in result.scheduled_items],
        "unscheduled_tasks": [x.task_id for x in result.unscheduled_tasks],
        "objective_value": result.objective_value,
        "constraint_stats": result.constraint_stats,
        "rolling_segments": result.rolling_segments,
        "replan_decision": replan_decision,
        "output_dir": str(out_dir),
    }


def _collect_missing_key_tasks(tasks, result) -> list[str]:
    scheduled = {item.task_id for item in result.scheduled_items}
    return [t.task_id for t in tasks if t.is_key_task and t.task_id not in scheduled]
