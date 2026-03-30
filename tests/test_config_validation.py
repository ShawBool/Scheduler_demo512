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


def test_validate_config_maps_old_thermal_capacity_to_danger_threshold():
    cfg = _base_cfg()
    cfg["constraints"].pop("thermal", None)
    cfg["constraints"]["thermal_capacity"] = 88

    validate_config(cfg)

    assert cfg["constraints"]["thermal"]["danger_threshold"] == 88


def test_validate_config_rejects_objective_weights_not_sum_to_one():
    cfg = _base_cfg()
    cfg["constraints"]["objective_profiles"] = {
        "base": {"task_value": 0.6, "completion": 0.6},
        "thermal": {"task_value": 0.3, "completion": 0.7},
    }

    with pytest.raises(ValueError, match="sum to 1"):
        validate_config(cfg)
