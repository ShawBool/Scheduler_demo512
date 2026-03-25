"""静态任务与可见窗口加载器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from .models import Task, VisibilityWindow
except ImportError:  # pragma: no cover - 允许测试时以顶层模块方式导入
    from models import Task, VisibilityWindow


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_base_dir(cfg: dict[str, Any]) -> Path:
    runtime = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}

    config_dir = runtime.get("config_dir")
    if isinstance(config_dir, str) and config_dir.strip():
        candidate = Path(config_dir)
        return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)

    config_file = runtime.get("config_file")
    if isinstance(config_file, str) and config_file.strip():
        config_path = Path(config_file)
        resolved = config_path if config_path.is_absolute() else (PROJECT_ROOT / config_path)
        return resolved.parent

    return PROJECT_ROOT


def _resolve_runtime_path(cfg: dict[str, Any], key: str, default: str) -> Path:
    runtime = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}
    path_value = runtime.get(key, default)
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate

    return _resolve_base_dir(cfg) / candidate


def _parse_strict_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"{field_name} must be a boolean-like value (bool/0/1/true/false)")

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False

    raise ValueError(f"{field_name} must be a boolean-like value (bool/0/1/true/false)")


def load_static_task_bundle(cfg: dict[str, Any]) -> tuple[list[Task], dict[str, VisibilityWindow], dict[str, Any]]:
    windows_path = _resolve_runtime_path(cfg, "static_windows_file", "data/latest_windows.json")
    tasks_path = _resolve_runtime_path(cfg, "static_tasks_file", "data/latest_small_tasks_pool.json")

    windows_payload = _read_json(windows_path)
    windows_items = windows_payload.get("visibility_windows", windows_payload.get("windows", []))

    windows: dict[str, VisibilityWindow] = {}
    for item in windows_items:
        window = VisibilityWindow(
            window_id=str(item["window_id"]),
            start=int(item["start"]),
            end=int(item["end"]),
        )
        windows[window.window_id] = window

    tasks_payload = _read_json(tasks_path)
    task_items = tasks_payload.get("tasks", [])

    tasks: list[Task] = []
    for item in task_items:
        window_ref = item.get("visibility_window")
        visibility_window = None
        if window_ref is not None:
            if window_ref not in windows:
                raise ValueError(f"unknown visibility_window: {window_ref}")
            visibility_window = windows[window_ref]

        task = Task(
            task_id=str(item["task_id"]),
            duration=int(item["duration"]),
            value=int(item["value"]),
            cpu=int(item["cpu"]),
            gpu=int(item["gpu"]),
            memory=int(item["memory"]),
            power=int(item["power"]),
            payload_type_requirements=list(item.get("payload_type_requirements", [])),
            predecessors=list(item.get("predecessors", [])),
            attitude_angle_deg=float(item.get("attitude_angle_deg"),None),
            is_key_task=_parse_strict_bool(item.get("is_key_task", False), "is_key_task"),
            visibility_window=visibility_window,
        )
        tasks.append(task)

    meta = {
        "task_count": len(tasks),
        "window_count": len(windows),
        "tasks_file": str(tasks_path),
        "windows_file": str(windows_path),
    }
    return tasks, windows, meta
