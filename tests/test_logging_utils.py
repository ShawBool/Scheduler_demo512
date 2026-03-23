import json

from scheduler.logging_utils import append_cycle_log, write_schedule_result, write_task_pool # pyright: ignore[reportAttributeAccessIssue]
from scheduler.models import ScheduleItem, ScheduleResult, Task


def test_logging_utils_write_and_append(tmp_path):
    result = ScheduleResult(
        scheduled_items=[ScheduleItem("t1", 0, 5, 30.0, 10)],
        unscheduled_tasks=[
            Task("t2", 0, 10, 3, 5, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], 45.0, False)
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
