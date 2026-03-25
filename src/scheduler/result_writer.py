"""结果与日志写入模块。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScheduleResult


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
