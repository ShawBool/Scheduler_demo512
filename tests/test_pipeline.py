import json
from pathlib import Path

from scheduler.pipeline import run_pipeline


def test_pipeline_outputs_schedule_and_cycle_log(tmp_path):
    output_dir = tmp_path / "output"
    result = run_pipeline(config_path="config", seed=7, output_dir=output_dir)

    schedule_path = output_dir / "latest_schedule.json"
    cycle_log_path = output_dir / "cycle_log.jsonl"
    task_pool_path = output_dir / "latest_task_pool.json"
    visibility_windows_path = output_dir / "latest_visibility_windows.json"

    assert schedule_path.exists()
    assert cycle_log_path.exists()
    assert task_pool_path.exists()
    assert visibility_windows_path.exists()

    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    assert "scheduled_items" in schedule
    assert "unscheduled_tasks" in schedule
    assert "objective_value" in schedule
    assert "constraint_stats" in schedule

    task_pool = json.loads(task_pool_path.read_text(encoding="utf-8"))
    assert "schema_version" in task_pool
    assert task_pool["schema_version"] == "2.0"
    assert "task_count" in task_pool
    assert "tasks" in task_pool
    assert task_pool["task_count"] == len(task_pool["tasks"])

    visibility_windows = json.loads(visibility_windows_path.read_text(encoding="utf-8"))
    assert "schema_version" in visibility_windows
    assert visibility_windows["schema_version"] == "2.0"
    assert "seed" in visibility_windows
    assert "horizon" in visibility_windows
    assert "window_count" in visibility_windows
    assert "windows" in visibility_windows
    assert visibility_windows["seed"] == 7
    assert visibility_windows["window_count"] == len(visibility_windows["windows"])

    window_ids = {window["window_id"] for window in visibility_windows["windows"]}
    for task in task_pool["tasks"]:
        window = task["visibility_window"]
        if window is not None:
            assert window["window_id"] in window_ids

    for window in visibility_windows["windows"]:
        assert "window_id" in window
        assert "start" in window
        assert "end" in window
        assert window["start"] < window["end"]

    assert "task_pool_file" in result
    assert result["task_pool_file"].endswith("latest_task_pool.json")
    assert "visibility_windows_file" in result
    assert result["visibility_windows_file"].endswith("latest_visibility_windows.json")
    for task in task_pool["tasks"]:
        if task["payload_type_requirements"]:
            assert task["visibility_window"] is not None
        else:
            assert task["visibility_window"] is None

    lines = cycle_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert "cycle_id" in payload
    assert "timestamp" in payload
    assert "state_snapshot" in payload
    assert "selected_tasks" in payload
    assert "unscheduled_tasks" in payload
    assert "constraint_violations" in payload
    assert "objective_value" in payload
    assert "scheduled_count" in payload["state_snapshot"]
    assert "unscheduled_count" in payload["state_snapshot"]
    assert "missing_key_tasks" in payload["constraint_violations"]
    assert "resource_overflow_count" in payload["constraint_violations"]
    assert "replan_decision" in payload["state_snapshot"]
    assert "trigger" in payload["state_snapshot"]["replan_decision"]
    assert isinstance(result["rolling_segments"], list)
    assert len(lines) == len(result["rolling_segments"])
    assert "replan_decision" in result
    assert "level" in result["replan_decision"]

    assert isinstance(result["objective_value"], (int, float))
