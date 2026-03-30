from scheduler.config import load_config
from scheduler.objective_engine import score_candidate


def test_objective_scaling_is_configurable_and_dimensionless():
    weights = {"task_value": 0.3, "completion": 0.2, "thermal_safety": 0.5}
    scales = {"task_value": (0, 100), "completion": (0, 1), "thermal_safety": (0, 1)}
    score = score_candidate(
        objective_raw={"task_value": 80, "completion": 0.8, "thermal_safety": 0.9},
        objective_ranges=scales,
        weights=weights,
    )
    assert 0 <= score.total_score <= 100


def test_load_config_contains_objective_scaling_defaults():
    cfg = load_config("config")
    scaling = cfg["constraints"]["objective_scaling"]
    assert scaling["task_value"] == [0, 100]
    assert scaling["completion"] == [0, 1]
