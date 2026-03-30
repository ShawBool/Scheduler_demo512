from scheduler.objective_engine import normalize_0_100, select_active_weights


def test_normalize_clamps_into_0_100():
    assert normalize_0_100(raw=120, lower=0, upper=100) == 100.0
    assert normalize_0_100(raw=-10, lower=0, upper=100) == 0.0


def test_dynamic_weights_switch_to_thermal_profile_when_hot_ratio_high():
    base = {"task_value": 0.4, "completion": 0.2, "thermal_safety": 0.2, "power_smoothing": 0.2}
    thermal = {"task_value": 0.2, "completion": 0.2, "thermal_safety": 0.4, "power_smoothing": 0.2}
    active, reason = select_active_weights(
        base_weights=base,
        thermal_weights=thermal,
        thermal_ratio=0.81,
        trigger_threshold=0.80,
    )
    assert active["thermal_safety"] == 0.4
    assert reason == "thermal_ratio_triggered"
