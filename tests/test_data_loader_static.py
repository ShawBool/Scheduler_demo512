import json

import pytest

from scheduler.data_loader import load_static_task_bundle


def test_loader_rejects_unknown_visibility_window(tmp_path):
    windows_file = tmp_path / "w.json"
    tasks_file = tmp_path / "t.json"
    windows_file.write_text(json.dumps({"visibility_windows": [{"window_id": "w1", "start": 0, "end": 10}]}), encoding="utf-8")
    tasks_file.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "t1",
                        "duration": 2,
                        "value": 1,
                        "cpu": 1,
                        "gpu": 0,
                        "memory": 1,
                        "power": 1,
                        "thermal_load": 1,
                        "payload_type_requirements": [],
                        "predecessors": [],
                        "visibility_window": "missing",
                        "attitude_angle_deg": None,
                        "is_key_task": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cfg = {"runtime": {"static_tasks_file": str(tasks_file), "static_windows_file": str(windows_file)}}

    with pytest.raises(ValueError, match="unknown visibility_window"):
        load_static_task_bundle(cfg)


def test_loader_loads_current_static_bundle():
    cfg = {
        "runtime": {
            "static_tasks_file": "data/latest_small_tasks_pool.json",
            "static_windows_file": "data/latest_windows.json",
        }
    }
    tasks, windows, meta = load_static_task_bundle(cfg)
    assert len(tasks) == 40
    assert len(windows) == 8
    assert meta["task_count"] == 40
