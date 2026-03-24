import pytest
from copy import deepcopy
import warnings

from scheduler.config import load_config, validate_config


def _base_cfg() -> dict:
    return {
        "runtime": {"time_horizon": 10, "time_step": 1, "solver_timeout_sec": 1},
        "simulation": {
            "task_count_min": 1,
            "task_count_max": 2,
            "dag_group_min": 1,
            "dag_group_max": 1,
            "key_task_probability": 0.1,
            "visibility_window_count_min": 2,
            "visibility_window_count_max": 3,
            "visibility_window_duration_min": 2,
            "visibility_window_duration_max": 3,
            "structured_task_ratio": 0.7,
            "dependency_density": 0.6,
            "window_reuse_target": 3,
            "max_hard_key_tasks": 1,
        },
        "constraints": {
            "cpu_capacity": 1,
            "gpu_capacity": 1,
            "memory_capacity": 1,
            "storage_capacity": 1,
            "bus_capacity": 1,
            "power_capacity": 1,
            "thermal_capacity": 1,
            "attitude_time_per_degree": 0.1,
        },
        "objective_weights": {"task_value": 1, "lateness_penalty": 0},
        "replan": {"gain_threshold": 10, "window_levels": {"L1": 1}, "disturbance_rules": {}},
        "logging": {},
    }


def test_load_config_loads_split_json_files():
    cfg = load_config("config")
    validate_config(cfg)
    assert "runtime" in cfg
    assert "simulation" in cfg
    assert "constraints" in cfg
    assert "objective_weights" in cfg
    assert "replan" in cfg
    assert "logging" in cfg


def test_validate_config_allows_nonpositive_dag_groups_for_compatibility():
    cfg = _base_cfg()
    cfg["simulation"]["dag_group_min"] = 0
    cfg["simulation"]["dag_group_max"] = 0
    validate_config(cfg)


def test_validate_config_rejects_invalid_visibility_window_ranges():
    cfg = _base_cfg()
    cfg["simulation"]["visibility_window_count_min"] = 5
    cfg["simulation"]["visibility_window_count_max"] = 3

    with pytest.raises(ValueError, match="visibility_window_count_min must be <= visibility_window_count_max"):
        validate_config(cfg)

def test_validate_config_rejects_new_surface_ratio_ranges():
    cfg = _base_cfg()
    cfg["simulation"]["structured_task_ratio"] = 1.1
    with pytest.raises(ValueError, match=r"structured_task_ratio must be in \[0, 1\]"):
        validate_config(cfg)

    cfg = _base_cfg()
    cfg["simulation"]["structured_task_ratio"] = 0.59
    with pytest.raises(ValueError, match=r"structured_task_ratio must be >= 0\.6"):
        validate_config(cfg)

    cfg = _base_cfg()
    cfg["simulation"]["dependency_density"] = -0.1
    with pytest.raises(ValueError, match=r"dependency_density must be in \[0, 1\]"):
        validate_config(cfg)

    cfg = _base_cfg()
    cfg["simulation"]["window_reuse_target"] = 0
    with pytest.raises(ValueError, match="window_reuse_target must be positive"):
        validate_config(cfg)


def test_validate_config_rejects_invalid_key_task_controls():
    cfg = _base_cfg()
    cfg["simulation"]["key_task_probability"] = 1.1
    with pytest.raises(ValueError, match=r"key_task_probability must be in \[0, 1\]"):
        validate_config(cfg)

    cfg = _base_cfg()
    cfg["simulation"]["max_hard_key_tasks"] = -1
    with pytest.raises(ValueError, match="max_hard_key_tasks must be >= 0"):
        validate_config(cfg)

    cfg = _base_cfg()
    cfg["simulation"]["max_hard_key_tasks"] = 1.5
    with pytest.raises(ValueError, match="max_hard_key_tasks must be an integer"):
        validate_config(cfg)


def test_load_config_sets_default_key_task_controls_when_missing(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    (cfg_dir / "runtime.json").write_text('{"time_horizon": 20, "time_step": 1, "solver_timeout_sec": 2}', encoding="utf-8")
    (cfg_dir / "constraints.json").write_text(
        '{"cpu_capacity": 2, "gpu_capacity": 1, "memory_capacity": 2, "storage_capacity": 2, '
        '"bus_capacity": 2, "power_capacity": 2, "thermal_capacity": 2, "attitude_time_per_degree": 0.1}',
        encoding="utf-8",
    )
    (cfg_dir / "objective_weights.json").write_text('{"task_value": 1, "lateness_penalty": 0}', encoding="utf-8")
    (cfg_dir / "replan.json").write_text('{"gain_threshold": 10, "window_levels": {"L1": 1}, "disturbance_rules": {}}', encoding="utf-8")
    (cfg_dir / "logging.json").write_text('{}', encoding="utf-8")
    (cfg_dir / "simulation.json").write_text(
        """
        {
          "task_count_min": 20,
          "task_count_max": 40,
          "dag_group_min": 2,
          "dag_group_max": 4,
          "structured_task_ratio": 0.7,
          "dependency_density": 0.3,
          "window_reuse_target": 4.0,
          "visibility_window_count_min": 3,
          "visibility_window_count_max": 6,
          "visibility_window_duration_min": 2,
          "visibility_window_duration_max": 8
        }
        """,
        encoding="utf-8",
    )

    cfg = load_config(cfg_dir)
    assert cfg["simulation"]["key_task_probability"] == pytest.approx(0.01)
    assert cfg["simulation"]["max_hard_key_tasks"] == 1


def test_load_config_maps_legacy_keys_with_warning_when_new_keys_absent(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    (cfg_dir / "runtime.json").write_text('{"time_horizon": 20, "time_step": 1, "solver_timeout_sec": 2}', encoding="utf-8")
    (cfg_dir / "constraints.json").write_text(
        '{"cpu_capacity": 2, "gpu_capacity": 1, "memory_capacity": 2, "storage_capacity": 2, '
        '"bus_capacity": 2, "power_capacity": 2, "thermal_capacity": 2, "attitude_time_per_degree": 0.1}',
        encoding="utf-8",
    )
    (cfg_dir / "objective_weights.json").write_text('{"task_value": 1, "lateness_penalty": 0}', encoding="utf-8")
    (cfg_dir / "replan.json").write_text('{"gain_threshold": 10, "window_levels": {"L1": 1}, "disturbance_rules": {}}', encoding="utf-8")
    (cfg_dir / "logging.json").write_text('{}', encoding="utf-8")
    (cfg_dir / "simulation.json").write_text(
        """
        {
          "task_count_min": 20,
          "task_count_max": 40,
          "dag_group_min": 2,
          "dag_group_max": 4,
          "sequence_count_min": 2,
          "sequence_count_max": 3,
          "sequence_task_min": 6,
          "sequence_task_max": 10,
          "dag_chains_per_sequence_min": 2,
          "dag_chains_per_sequence_max": 4,
          "visibility_window_count_min": 3,
          "visibility_window_count_max": 6,
          "visibility_window_duration_min": 2,
          "visibility_window_duration_max": 8,
          "window_share_task_min": 2,
          "window_share_task_max": 4,
          "predecessor_probability": 0.55,
          "key_task_probability": 0.1
        }
        """,
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="legacy simulation keys"):
        cfg = load_config(cfg_dir)

    sim = cfg["simulation"]
    assert "structured_task_ratio" in sim
    assert "dependency_density" in sim
    assert "window_reuse_target" in sim
    assert sim["dependency_density"] == pytest.approx(0.55)
    assert sim["window_reuse_target"] == pytest.approx(3.0)


def test_validate_config_does_not_emit_warning_or_mutate_input_for_legacy_keys():
    cfg = _base_cfg()
    sim = cfg["simulation"]
    sim.pop("structured_task_ratio")
    sim.pop("dependency_density")
    sim.pop("window_reuse_target")
    sim["sequence_count_min"] = 2
    sim["sequence_count_max"] = 4
    sim["sequence_task_min"] = 3
    sim["sequence_task_max"] = 5
    sim["predecessor_probability"] = 0.4
    sim["window_share_task_min"] = 2
    sim["window_share_task_max"] = 3
    before = deepcopy(sim)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        validate_config(cfg)

    assert not caught
    assert sim == before


def test_load_config_prefers_new_keys_without_compat_warning_when_both_present(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    (cfg_dir / "runtime.json").write_text('{"time_horizon": 20, "time_step": 1, "solver_timeout_sec": 2}', encoding="utf-8")
    (cfg_dir / "constraints.json").write_text(
        '{"cpu_capacity": 2, "gpu_capacity": 1, "memory_capacity": 2, "storage_capacity": 2, '
        '"bus_capacity": 2, "power_capacity": 2, "thermal_capacity": 2, "attitude_time_per_degree": 0.1}',
        encoding="utf-8",
    )
    (cfg_dir / "objective_weights.json").write_text('{"task_value": 1, "lateness_penalty": 0}', encoding="utf-8")
    (cfg_dir / "replan.json").write_text('{"gain_threshold": 10, "window_levels": {"L1": 1}, "disturbance_rules": {}}', encoding="utf-8")
    (cfg_dir / "logging.json").write_text('{}', encoding="utf-8")
    (cfg_dir / "simulation.json").write_text(
        """
        {
          "task_count_min": 20,
          "task_count_max": 40,
          "dag_group_min": 2,
          "dag_group_max": 4,
                    "structured_task_ratio": 0.7,
          "dependency_density": 0.3,
          "window_reuse_target": 4.0,
          "visibility_window_count_min": 3,
          "visibility_window_count_max": 6,
          "visibility_window_duration_min": 2,
          "visibility_window_duration_max": 8,
          "sequence_count_min": 3,
          "sequence_count_max": 4,
          "sequence_task_min": 10,
          "sequence_task_max": 12,
          "window_share_task_min": 8,
          "window_share_task_max": 10,
          "predecessor_probability": 0.9
        }
        """,
        encoding="utf-8",
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = load_config(cfg_dir)

    assert not caught
    sim = cfg["simulation"]
    assert sim["structured_task_ratio"] == pytest.approx(0.7)
    assert sim["dependency_density"] == pytest.approx(0.3)
    assert sim["window_reuse_target"] == pytest.approx(4.0)


def test_load_config_clamps_structured_task_ratio_to_minimum_with_warning(tmp_path):
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    (cfg_dir / "runtime.json").write_text('{"time_horizon": 20, "time_step": 1, "solver_timeout_sec": 2}', encoding="utf-8")
    (cfg_dir / "constraints.json").write_text(
        '{"cpu_capacity": 2, "gpu_capacity": 1, "memory_capacity": 2, "storage_capacity": 2, '
        '"bus_capacity": 2, "power_capacity": 2, "thermal_capacity": 2, "attitude_time_per_degree": 0.1}',
        encoding="utf-8",
    )
    (cfg_dir / "objective_weights.json").write_text('{"task_value": 1, "lateness_penalty": 0}', encoding="utf-8")
    (cfg_dir / "replan.json").write_text('{"gain_threshold": 10, "window_levels": {"L1": 1}, "disturbance_rules": {}}', encoding="utf-8")
    (cfg_dir / "logging.json").write_text('{}', encoding="utf-8")
    (cfg_dir / "simulation.json").write_text(
        """
        {
          "task_count_min": 20,
          "task_count_max": 40,
          "dag_group_min": 2,
          "dag_group_max": 4,
          "structured_task_ratio": 0.2,
          "dependency_density": 0.3,
          "window_reuse_target": 4.0,
          "visibility_window_count_min": 3,
          "visibility_window_count_max": 6,
          "visibility_window_duration_min": 2,
          "visibility_window_duration_max": 8
        }
        """,
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="structured_task_ratio"):
        cfg = load_config(cfg_dir)

    assert cfg["simulation"]["structured_task_ratio"] == pytest.approx(0.6)

