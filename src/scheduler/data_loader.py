"""静态输入加载器：读取任务池与可见窗口，并做严格校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Task, VisibilityWindow


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _to_abs(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def _parse_bool(value: Any, field_name: str) -> bool:
    """严格解析布尔值。

    这样做的目的是避免上游把 'yes'、'ok'、2 等不规范值悄悄混进来。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    raise ValueError(f"{field_name} must be bool-like")


def _resolve_runtime_path(cfg: dict[str, Any], key: str, default: str) -> Path:
    runtime = cfg.get("runtime", {})
    value = runtime.get(key, default)
    return _to_abs(value)


def load_static_task_bundle(cfg: dict[str, Any]) -> tuple[list[Task], dict[str, VisibilityWindow], dict[str, Any]]:
    """加载静态任务与窗口。

    返回：
    1. tasks: 任务列表
    2. windows: window_id -> VisibilityWindow
    3. meta: 统计与输入来源
    """
    windows_path = _resolve_runtime_path(cfg, "static_windows_file", "data/latest_windows.json")
    tasks_path = _resolve_runtime_path(cfg, "static_tasks_file", "data/small_tasks_pool_58.json")

    windows_payload = _read_json(windows_path)
    windows_items = windows_payload.get("visibility_windows", [])

    windows: dict[str, VisibilityWindow] = {}
    for item in windows_items:
        win = VisibilityWindow(
            window_id=str(item["window_id"]),
            start=int(item["start"]),
            end=int(item["end"]),
        )
        if win.end <= win.start:
            raise ValueError(f"window {win.window_id} has invalid range")
        windows[win.window_id] = win

    tasks_payload = _read_json(tasks_path)
    task_items = tasks_payload.get("tasks", [])

    tasks: list[Task] = []
    task_ids: set[str] = set()

    for item in task_items:
        task_id = str(item["task_id"])
        if task_id in task_ids:
            raise ValueError(f"duplicate task_id: {task_id}")
        task_ids.add(task_id)

        duration = int(item["duration"])
        if duration <= 0:
            raise ValueError(f"task {task_id} has non-positive duration")

        window_ref = item.get("visibility_window")
        visibility_window = None
        if window_ref is not None:
            if window_ref not in windows:
                raise ValueError(f"unknown visibility_window: {window_ref}")
            visibility_window = windows[str(window_ref)]

        task = Task(
            task_id=task_id,
            duration=duration,
            value=int(item["value"]),
            cpu=int(item["cpu"]),
            gpu=int(item["gpu"]),
            memory=int(item["memory"]),
            power=int(item["power"]),
            thermal_load=int(item.get("thermal_load", 0)),
            payload_type_requirements=list(item.get("payload_type_requirements", [])),
            predecessors=list(item.get("predecessors", [])),
            attitude_angle_deg=float(item["attitude_angle_deg"]) if item.get("attitude_angle_deg") is not None else None,
            is_key_task=_parse_bool(item.get("is_key_task", False), "is_key_task"),
            visibility_window=visibility_window,
        )
        tasks.append(task)

    # 在加载阶段提前做依赖引用完整性校验，避免后续求解阶段才出现隐式崩溃。
    all_ids = {t.task_id for t in tasks}
    for task in tasks:
        for pred in task.predecessors:
            if pred not in all_ids:
                raise ValueError(f"task {task.task_id} references unknown predecessor {pred}")

    meta = {
        "task_count": len(tasks),
        "window_count": len(windows),
        "tasks_file": str(tasks_path),
        "windows_file": str(windows_path),
    }
    return tasks, windows, meta
