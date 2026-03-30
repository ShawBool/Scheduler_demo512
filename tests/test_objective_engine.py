from scheduler.objective_engine import normalize_0_100


def test_normalize_clamps_into_0_100():
    assert normalize_0_100(raw=120, lower=0, upper=100) == 100.0
    assert normalize_0_100(raw=-10, lower=0, upper=100) == 0.0


def test_objective_engine_no_longer_exports_dynamic_profile_selector():
    import scheduler.objective_engine as engine

    assert not hasattr(engine, "select_active_weights")
