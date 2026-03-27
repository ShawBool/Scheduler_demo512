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
