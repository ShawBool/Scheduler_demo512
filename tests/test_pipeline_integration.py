from pathlib import Path
import json

from scheduler.pipeline import run_pipeline
from scheduler.replan_interface import ReplanRequest, ReplanResponse


def test_main_pipeline_returns_schedule_and_unscheduled_sections(tmp_path):
    result = run_pipeline("config", seed=666, output_dir=str(tmp_path))
    assert "schedule" in result
    assert "unscheduled" in result
    assert "metrics" in result
    assert "solver_summary" in result

    assert (tmp_path / "solver_progress.jsonl").exists()

    history_files = list(tmp_path.glob("schedule_*.json"))
    assert history_files

    rows = [
        json.loads(line)
        for line in (tmp_path / "solver_progress.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_types = {row.get("event_type") for row in rows}
    assert "heuristic_initial_solution" in event_types
    assert "heuristic_final_solution" in event_types
    assert "terminal" in event_types

    assert any(item.get("item_type") == "ATTITUDE" for item in result["schedule"])


def test_replan_contract_types_exist():
    req = ReplanRequest(reason="disturbance")
    resp = ReplanResponse(accepted=False, message="not implemented")
    assert req.reason == "disturbance"
    assert resp.accepted is False


def test_doc_mentions_iteration_log_every_10_generations():
    content = Path("docs/地面站基线任务规划组件开发的初步计划.md").read_text(encoding="utf-8")
    assert "每隔10" in content or "每10代" in content


def test_pipeline_outputs_thermal_metrics(tmp_path):
    result = run_pipeline("config", seed=42, output_dir=str(tmp_path))
    metrics = result["metrics"]
    assert "peak_temperature" in metrics
    assert "min_thermal_margin" in metrics
    assert "warning_duration" in metrics
    assert "max_continuous_warning_duration" in metrics
    assert "thermal_penalty_total" in metrics
