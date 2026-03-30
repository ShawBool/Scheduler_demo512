from pathlib import Path
import json

from scheduler.models import ScheduleItem, Task
from scheduler.result_writer import append_iteration_log, initialize_iteration_log, materialize_att_segments


def test_iteration_log_file_created_before_solver(tmp_path: Path):
    log_path = tmp_path / "solver_progress.jsonl"
    initialize_iteration_log(log_path)
    assert log_path.exists()
    assert log_path.read_text(encoding="utf-8") == ""


def test_progress_event_schema_supports_metrics_and_solution_payload(tmp_path: Path):
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")

    append_iteration_log(log_path, {"event_type": "heuristic_iteration_summary", "metrics": {"score": 10}})
    append_iteration_log(log_path, {"event_type": "heuristic_initial_solution", "solution": {"items": []}})

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert rows[0]["event_type"] == "heuristic_iteration_summary"
    assert rows[0]["phase"] == "unknown"
    assert rows[0]["iteration"] == 0
    assert "metrics" in rows[0]

    assert rows[1]["event_type"] == "heuristic_initial_solution"
    assert rows[1]["phase"] == "unknown"
    assert rows[1]["iteration"] == 0
    assert "solution" in rows[1]


def test_materialize_att_before_attitude_tasks():
    schedule = [
        ScheduleItem(task_id="t1", start=200, end=210, value=10, is_key_task=False, visibility_window_id="w1"),
    ]
    task_map = {
        "t1": Task(
            task_id="t1",
            duration=10,
            value=10,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            thermal_load=1,
            attitude_angle_deg=180,
        )
    }

    materialized = materialize_att_segments(
        schedule,
        task_map=task_map,
        initial_attitude_angle_deg=0,
        attitude_time_per_degree=1.0,
    )

    assert materialized[0].item_type == "ATTITUDE"
    assert materialized[1].item_type == "BUSINESS"
    assert materialized[0].end == materialized[1].start
    assert materialized[0].task_id.endswith("_att")


def test_materialize_skips_attitude_item_when_transition_is_zero():
    schedule = [
        ScheduleItem(task_id="t_same", start=10, end=15, value=1, is_key_task=False, visibility_window_id="w"),
    ]
    task_map = {
        "t_same": Task(
            task_id="t_same",
            duration=5,
            value=1,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            thermal_load=1,
            attitude_angle_deg=0,
        )
    }
    out = materialize_att_segments(
        schedule,
        task_map=task_map,
        initial_attitude_angle_deg=0,
        attitude_time_per_degree=1.0,
    )
    assert len([x for x in out if x.item_type == "ATTITUDE"]) == 0
