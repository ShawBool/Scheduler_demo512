import copy

import pytest

from scheduler.config import load_config, validate_config


def _base_cfg() -> dict:
    cfg = load_config("config")
    return copy.deepcopy(cfg)


def test_validate_config_requires_initial_attitude_angle_deg():
    cfg = _base_cfg()
    cfg["runtime"].pop("initial_attitude_angle_deg", None)

    with pytest.raises(ValueError, match="runtime.initial_attitude_angle_deg"):
        validate_config(cfg)


def test_validate_config_rejects_out_of_range_initial_attitude_angle_deg():
    cfg = _base_cfg()
    cfg["runtime"]["initial_attitude_angle_deg"] = 361

    with pytest.raises(ValueError, match="runtime.initial_attitude_angle_deg"):
        validate_config(cfg)


def test_validate_config_rejects_non_positive_phase_log_frequency():
    cfg = _base_cfg()
    cfg["runtime"]["initial_attitude_angle_deg"] = 10
    cfg["runtime"]["heuristic_log_every_n"] = 0

    with pytest.raises(ValueError, match="runtime.heuristic_log_every_n"):
        validate_config(cfg)


def test_validate_config_requires_positive_thermal_time_step():
    cfg = _base_cfg()
    cfg["runtime"]["thermal_time_step"] = 0

    with pytest.raises(ValueError, match="runtime.thermal_time_step"):
        validate_config(cfg)


def test_validate_config_rejects_warning_not_less_than_danger():
    cfg = _base_cfg()
    cfg["constraints"]["thermal"] = {
        "warning_threshold": 100,
        "danger_threshold": 100,
    }

    with pytest.raises(ValueError, match="warning_threshold"):
        validate_config(cfg)


def test_validate_config_sets_default_thermal_thresholds_when_missing():
    cfg = _base_cfg()
    cfg["constraints"].pop("thermal", None)

    validate_config(cfg)

    assert cfg["constraints"]["thermal"]["danger_threshold"] == 100.0


def test_validate_config_rejects_invalid_objective_scaling_bounds():
    cfg = _base_cfg()
    cfg["constraints"]["objective_scaling"]["task_value"] = [10, 10]

    with pytest.raises(ValueError, match="max must be greater"):
        validate_config(cfg)


def test_validate_config_rejects_removed_runtime_dynamic_weight_fields():
    cfg = load_config("config")
    assert "dynamic_weight_enable" not in cfg["runtime"]
    assert "thermal_weight_trigger_ratio" not in cfg["runtime"]
    assert "max_reweight_rounds" not in cfg["runtime"]


def test_validate_config_no_longer_requires_replan_section():
    cfg = load_config("config")
    cfg.pop("replan", None)
    validate_config(cfg)
