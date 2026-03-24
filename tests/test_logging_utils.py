import json

from scheduler.logging_utils import (  # pyright: ignore[reportAttributeAccessIssue]
    append_cycle_log,
    append_solver_progress_log,
    ensure_jsonl_file,
    write_schedule_result,
    write_task_pool,
)
from scheduler.models import ScheduleItem, ScheduleResult, Task


def test_logging_utils_write_and_append(tmp_path):
    result = ScheduleResult(
        scheduled_items=[ScheduleItem("t1", 0, 5, 30.0, 10)],
        unscheduled_tasks=[
            Task(
                task_id="t2",
                duration=3,
                value=5,
                cpu=1,
                gpu=0,
                memory=1,
                power=1,
                payload_type_requirements=[],
                predecessors=[],
                attitude_angle_deg=45.0,
                is_key_task=False,
                visibility_window=None,
            )
        ],
        objective_value=10,
        constraint_stats={"scheduled_count": 1, "unscheduled_count": 1},
    )

    schedule_path = tmp_path / "latest_schedule.json"
    task_pool_path = tmp_path / "latest_task_pool.json"
    cycle_log_path = tmp_path / "cycle_log.jsonl"

    write_schedule_result(result, schedule_path)
    write_task_pool(result.unscheduled_tasks, task_pool_path)
    append_cycle_log(
        cycle_log_path,
        cycle_id=1,
        state_snapshot={"temperature": 20},
        selected_tasks=["t1"],
        unscheduled_tasks=["t2"],
        constraint_violations={"missing_key_tasks": []},
        objective_value=10,
    )

    schedule_payload = json.loads(schedule_path.read_text(encoding="utf-8"))
    assert schedule_payload["scheduled_items"][0]["task_id"] == "t1"
    assert schedule_payload["unscheduled_tasks"][0]["task_id"] == "t2"
    pool_payload = json.loads(task_pool_path.read_text(encoding="utf-8"))
    assert pool_payload["task_count"] == 1
    assert pool_payload["tasks"][0]["task_id"] == "t2"

    line = cycle_log_path.read_text(encoding="utf-8").strip().splitlines()[-1]
    cycle_payload = json.loads(line)
    assert cycle_payload["cycle_id"] == 1
    assert cycle_payload["selected_tasks"] == ["t1"]


def test_solver_progress_jsonl_file_contract_and_fields(tmp_path):
    solver_progress_path = tmp_path / "solver_progress.jsonl"

    ensure_jsonl_file(solver_progress_path)
    assert solver_progress_path.exists()
    assert solver_progress_path.read_text(encoding="utf-8") == ""

    append_solver_progress_log(
        solver_progress_path,
        solution_index=1,
        objective=123.5,
        wall_time=0.25,
        best_bound=120.0,
    )

    lines = solver_progress_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["solution_index"] == 1
    assert payload["objective"] == 123.5
    assert payload["wall_time"] == 0.25
    assert payload["best_bound"] == 120.0
