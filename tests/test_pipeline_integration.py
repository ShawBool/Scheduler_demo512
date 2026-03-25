from pathlib import Path

from scheduler.pipeline import run_pipeline
from scheduler.replan_interface import ReplanRequest, ReplanResponse


def test_main_pipeline_returns_schedule_and_unscheduled_sections(tmp_path):
    result = run_pipeline("config", seed=666, output_dir=str(tmp_path))
    assert "schedule" in result
    assert "unscheduled" in result
    assert "metrics" in result
    assert "solver_summary" in result

    assert (tmp_path / "latest_schedule.json").exists()
    assert (tmp_path / "solver_progress.jsonl").exists()


def test_replan_contract_types_exist():
    req = ReplanRequest(reason="disturbance")
    resp = ReplanResponse(accepted=False, message="not implemented")
    assert req.reason == "disturbance"
    assert resp.accepted is False


def test_doc_mentions_iteration_log_every_10_generations():
    content = Path("docs/地面站基线任务规划组件开发的初步计划.md").read_text(encoding="utf-8")
    assert "每隔10" in content or "每10代" in content
