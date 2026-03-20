import json
from pathlib import Path

from scheduler.pipeline import run_pipeline


def test_pipeline_outputs_schedule_and_cycle_log(tmp_path):
    output_dir = tmp_path / "output"
    result = run_pipeline(config_path="config/planner_config.json", seed=7, output_dir=output_dir)

    schedule_path = output_dir / "latest_schedule.json"
    cycle_log_path = output_dir / "cycle_log.jsonl"

    assert schedule_path.exists()
    assert cycle_log_path.exists()

    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    assert "scheduled_items" in schedule
    assert "unscheduled_tasks" in schedule
    assert "objective_value" in schedule
    assert "constraint_stats" in schedule

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
    assert "danger_rule_block_count" in payload["constraint_violations"]
    assert "link_window_violation_count" in payload["constraint_violations"]
    assert "replan_decision" in payload["state_snapshot"]
    assert "trigger" in payload["state_snapshot"]["replan_decision"]
    assert isinstance(result["rolling_segments"], list)
    assert len(lines) == len(result["rolling_segments"])
    assert "replan_decision" in result
    assert "level" in result["replan_decision"]

    assert isinstance(result["objective_value"], (int, float))
