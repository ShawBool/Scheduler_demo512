import pytest

from scheduler.config import load_config, validate_config


def test_load_config_loads_split_json_files():
    cfg = load_config("config")
    validate_config(cfg)
    assert "runtime" in cfg
    assert "simulation" in cfg
    assert "constraints" in cfg
    assert "objective_weights" in cfg
    assert "replan" in cfg
    assert "logging" in cfg


def test_validate_config_rejects_nonpositive_dag_groups():
    cfg = {
        "runtime": {"time_horizon": 10, "time_step": 1, "solver_timeout_sec": 1},
        "simulation": {
            "task_count_min": 1,
            "task_count_max": 2,
            "dag_group_min": 0,
            "dag_group_max": 1,
            "key_task_name": "k",
        },
        "constraints": {
            "cpu_capacity": 1,
            "gpu_capacity": 1,
            "memory_capacity": 1,
            "storage_capacity": 1,
            "bus_capacity": 1,
            "max_concurrency_cores": 1,
            "power_capacity": 1,
            "thermal_capacity": 1,
            "attitude_time_per_degree": 0.1,
        },
        "objective_weights": {"task_value": 1, "lateness_penalty": 0},
        "replan": {"gain_threshold": 10, "window_levels": {"L1": 1}, "disturbance_rules": {}},
        "logging": {},
    }

    with pytest.raises(ValueError, match="dag_group_min must be positive"):
        validate_config(cfg)

    cfg["simulation"]["dag_group_min"] = 1
    cfg["simulation"]["dag_group_max"] = 0
    with pytest.raises(ValueError, match="dag_group_max must be positive"):
        validate_config(cfg)

