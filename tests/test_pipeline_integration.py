from pathlib import Path
import json
import shutil

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


def test_pipeline_outputs_objective_breakdown_and_active_profile(tmp_path):
    out = run_pipeline("config", seed=42, output_dir=tmp_path.as_posix())
    assert "objective_breakdown" in out["solver_summary"]
    assert "active_weight_profile" in out["solver_summary"]
    assert "switch_reason" in out["solver_summary"]


def test_dynamic_weight_profile_changes_after_simulated_thermal_replay(tmp_path):
    config_dir = tmp_path / "config_case_reweight"
    config_dir.mkdir(parents=True, exist_ok=True)
    for name in ("runtime.json", "constraints.json", "logging.json", "replan.json"):
        shutil.copy(Path("config") / name, config_dir / name)

    runtime_path = config_dir / "runtime.json"
    runtime_cfg = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime_cfg["dynamic_weight_enable"] = True
    runtime_cfg["thermal_weight_trigger_ratio"] = 0.2
    runtime_cfg["max_reweight_rounds"] = 3
    runtime_path.write_text(json.dumps(runtime_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    out = run_pipeline(str(config_dir), seed=42, output_dir=tmp_path.as_posix())
    history = out["solver_summary"].get("weight_profile_history", [])
    assert len(history) >= 2
    assert any(item["profile"] == "thermal" for item in history)


def test_thermal_profile_increases_thermal_safety_weight_effect(tmp_path):
    config_dir = tmp_path / "config_case"
    config_dir.mkdir(parents=True, exist_ok=True)
    for name in ("runtime.json", "constraints.json", "logging.json", "replan.json"):
        shutil.copy(Path("config") / name, config_dir / name)

    runtime_path = config_dir / "runtime.json"
    runtime_cfg = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime_cfg["thermal_weight_trigger_ratio"] = 0.9
    runtime_path.write_text(json.dumps(runtime_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    constraints_path = config_dir / "constraints.json"
    constraints_cfg = json.loads(constraints_path.read_text(encoding="utf-8"))
    constraints_cfg.setdefault("thermal", {})["danger_threshold"] = 100
    constraints_path.write_text(json.dumps(constraints_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    base_out = run_pipeline(str(config_dir), seed=42, output_dir=(tmp_path / "base").as_posix())
    assert base_out["solver_summary"]["active_weight_profile"] == "base"

    runtime_cfg["thermal_weight_trigger_ratio"] = 0.2
    runtime_path.write_text(json.dumps(runtime_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    thermal_out = run_pipeline(str(config_dir), seed=42, output_dir=(tmp_path / "thermal").as_posix())

    assert thermal_out["solver_summary"]["active_weight_profile"] == "thermal"
