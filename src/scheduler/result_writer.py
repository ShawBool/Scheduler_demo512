"""结果与日志写入模块。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScheduleResult
from .models import ScheduleItem, Task


def initialize_iteration_log(path: str | Path) -> Path:
    """在求解前创建日志文件，满足“有无改进都必须有文件”的契约。"""
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    return log_path


def append_iteration_log(path: str | Path, payload: dict[str, Any]) -> None:
    log_path = Path(path)
    row = dict(payload)
    row.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    row.setdefault("event_type", "unknown")
    row.setdefault("phase", "unknown")
    row.setdefault("iteration", 0)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_schedule_result(output_file: str | Path, result: ScheduleResult) -> dict[str, Any]:
    """写入主结果文件，并返回可直接 print 的字典。"""
    payload = {
        "schedule": [asdict(item) for item in result.schedule],
        "unscheduled": [asdict(item) for item in result.unscheduled],
        "metrics": result.metrics,
        "solver_summary": result.solver_summary,
    }

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return payload


def _transition_duration(prev_angle: float | None, next_angle: float | None, per_degree: float) -> int:
    if prev_angle is None or next_angle is None:
        return 0
    delta = abs(float(prev_angle) - float(next_angle))
    delta = min(delta, 360.0 - delta)
    return int(round(delta * per_degree))


def materialize_att_segments(
    schedule: list[ScheduleItem],
    *,
    task_map: dict[str, Task],
    initial_attitude_angle_deg: float,
    attitude_time_per_degree: float,
) -> list[ScheduleItem]:
    """根据最终业务序列物化 ATT 记录。"""
    ordered = sorted(schedule, key=lambda x: (x.start, x.task_id))
    materialized: list[ScheduleItem] = []
    current_attitude: float | None = float(initial_attitude_angle_deg)

    for item in ordered:
        task = task_map[item.task_id]
        target_att = task.attitude_angle_deg

        # 兼容历史数据里已显式存在的 *_att 任务，避免重复物化。
        if item.task_id.endswith("_att"):
            materialized.append(
                ScheduleItem(
                    task_id=item.task_id,
                    start=item.start,
                    end=item.end,
                    value=item.value,
                    is_key_task=item.is_key_task,
                    visibility_window_id=item.visibility_window_id,
                    item_type="ATTITUDE",
                )
            )
            if target_att is not None:
                current_attitude = float(target_att)
            continue

        if target_att is not None:
            transition = _transition_duration(current_attitude, target_att, attitude_time_per_degree)
            att_end = item.start
            att_start = att_end - transition
            if materialized and att_start < materialized[-1].end:
                att_start = materialized[-1].end
                if att_start > att_end:
                    att_start = att_end

            materialized.append(
                ScheduleItem(
                    task_id=f"{item.task_id}_att",
                    start=att_start,
                    end=att_end,
                    value=0,
                    is_key_task=False,
                    visibility_window_id=item.visibility_window_id,
                    item_type="ATTITUDE",
                )
            )

        materialized.append(
            ScheduleItem(
                task_id=item.task_id,
                start=item.start,
                end=item.end,
                value=item.value,
                is_key_task=item.is_key_task,
                visibility_window_id=item.visibility_window_id,
                item_type="BUSINESS",
            )
        )

        if target_att is not None:
            current_attitude = float(target_att)

    return materialized
