from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHED_SRC = ROOT / "src" / "scheduler"
if str(SCHED_SRC) not in sys.path:
    sys.path.insert(0, str(SCHED_SRC))

DATA_LOADER_PATH = ROOT / "src" / "scheduler" / "data_loader.py"
SPEC = importlib.util.spec_from_file_location("scheduler_data_loader", DATA_LOADER_PATH)
assert SPEC is not None and SPEC.loader is not None
DATA_LOADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATA_LOADER)
load_static_task_bundle = DATA_LOADER.load_static_task_bundle


def test_load_static_task_bundle_success_and_meta_counts() -> None:
    cfg = {
        "runtime": {
            "static_tasks_file": "data/latest_small_tasks_pool.json",
            "static_windows_file": "data/latest_windows.json",
        }
    }

    tasks, windows, meta = load_static_task_bundle(cfg)

    assert tasks
    assert windows
    assert meta["task_count"] == len(tasks)


def test_load_static_task_bundle_maps_visibility_window_ids() -> None:
    cfg = {
        "runtime": {
            "static_tasks_file": "data/latest_small_tasks_pool.json",
            "static_windows_file": "data/latest_windows.json",
        }
    }

    tasks, windows, _ = load_static_task_bundle(cfg)

    linked_tasks = [task for task in tasks if task.visibility_window is not None]
    assert linked_tasks
    assert all(task.visibility_window.window_id in windows for task in linked_tasks)


def test_load_static_task_bundle_raises_on_missing_required_task_field(tmp_path) -> None:
    windows_payload = {
        "schema_version": "2.0",
        "window_count": 1,
        "visibility_windows": [
            {"window_id": "target_1", "start": 0, "end": 10},
        ],
    }
    tasks_payload = {
        "schema_version": "2.0",
        "task_count": 1,
        "tasks": [
            {
                "duration": 5,
                "value": 10,
                "cpu": 1,
                "gpu": 0,
                "memory": 2,
                "power": 1,
                "payload_type_requirements": [],
                "predecessors": [],
                "attitude_angle_deg": 0.0,
                "is_key_task": False,
                "visibility_window": "target_1",
            }
        ],
    }

    windows_file = tmp_path / "windows.json"
    tasks_file = tmp_path / "tasks.json"
    windows_file.write_text(json.dumps(windows_payload), encoding="utf-8")
    tasks_file.write_text(json.dumps(tasks_payload), encoding="utf-8")

    cfg = {
        "runtime": {
            "static_tasks_file": str(tasks_file),
            "static_windows_file": str(windows_file),
        }
    }

    with pytest.raises((ValueError, KeyError)):
        load_static_task_bundle(cfg)
