"""日志写入工具。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScheduleResult


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
