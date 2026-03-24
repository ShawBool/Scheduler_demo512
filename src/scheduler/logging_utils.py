"""日志写入工具。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScheduleResult, Task, VisibilityWindow

TASK_POOL_SCHEMA_VERSION = "2.0"
VISIBILITY_WINDOWS_SCHEMA_VERSION = "2.0"


def write_schedule_result(result: ScheduleResult, path: str | Path) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scheduled_items": [asdict(item) for item in result.scheduled_items],
        "unscheduled_tasks": [asdict(task) for task in result.unscheduled_tasks],
        "objective_value": result.objective_value,
        "constraint_stats": result.constraint_stats,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_task_pool(tasks: list[Task], path: str | Path) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": TASK_POOL_SCHEMA_VERSION,
        "task_count": len(tasks),
        "tasks": [asdict(task) for task in tasks],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_visibility_windows(
    windows: list[VisibilityWindow],
    path: str | Path,
    *,
    seed: int,
    horizon: int,
) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": VISIBILITY_WINDOWS_SCHEMA_VERSION,
        "seed": seed,
        "horizon": horizon,
        "window_count": len(windows),
        "windows": [asdict(window) for window in windows],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_cycle_log(
    path: str | Path,
    *,
    cycle_id: int,
    state_snapshot: dict[str, Any],
    selected_tasks: list[str],
    unscheduled_tasks: list[str],
    constraint_violations: dict[str, Any],
    objective_value: float,
) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "cycle_id": cycle_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state_snapshot": state_snapshot,
        "selected_tasks": selected_tasks,
        "unscheduled_tasks": unscheduled_tasks,
        "constraint_violations": constraint_violations,
        "objective_value": objective_value,
    }
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def ensure_jsonl_file(path: str | Path) -> None:
    """确保 jsonl 文件存在；用于需要空文件契约的日志输出。"""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("", encoding="utf-8")


def append_solver_progress_log(
    path: str | Path,
    *,
    solution_index: int,
    objective: float,
    wall_time: float,
    best_bound: float,
) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "solution_index": solution_index,
        "objective": objective,
        "wall_time": wall_time,
        "best_bound": best_bound,
    }
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
