from scheduler.thermal_model import NoOpThermalModel, SemiEmpiricalThermalModelV1, ThermalCoefficients


def test_update_temperature_includes_quadratic_concurrency_term():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(
            a_p=0.1,
            a_c=0.0,
            lambda_concurrency=0.2,
            k_cool=0.0,
            b_att=0.0,
        ),
        env_temperature=20.0,
    )

    nxt = model.update(
        state={"temperature": 30.0},
        features={
            "power_total": 1.0,
            "concurrency": 2,
            "attitude_cooling_disturbance": 0.0,
        },
        dt=1.0,
    )

    assert nxt["temperature"] == 30.9


def test_max_continuous_warning_duration_is_detected():
    flags = [0, 1, 1, 1, 0, 1]
    assert SemiEmpiricalThermalModelV1.max_continuous_warning_steps(flags) == 3


def test_temperature_keeps_when_at_env_and_no_heat_gen():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(
            a_p=0.0,
            a_c=0.0,
            lambda_concurrency=0.0,
            k_cool=0.1,
            b_att=0.0,
        ),
        env_temperature=20.0,
    )

    nxt = model.update(
        state={"temperature": 20.0},
        features={
            "power_total": 0.0,
            "concurrency": 0,
            "attitude_cooling_disturbance": 0.0,
        },
        dt=1.0,
    )

    assert nxt["temperature"] == 20.0


def test_attitude_cooling_disturbance_hook_affects_temperature():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(
            a_p=0.0,
            a_c=0.0,
            lambda_concurrency=0.0,
            k_cool=0.0,
            b_att=1.0,
        ),
        env_temperature=20.0,
    )

    nxt = model.update(
        state={"temperature": 30.0},
        features={
            "power_total": 0.0,
            "concurrency": 0,
            "attitude_cooling_disturbance": 2.0,
        },
        dt=1.0,
    )

    assert nxt["temperature"] == 28.0


def test_noop_model_returns_input_temperature():
    model = NoOpThermalModel()
    nxt = model.update(state={"temperature": 42.0}, features={}, dt=1.0)
    assert nxt["temperature"] == 42.0


def test_model_ignores_cpu_gpu_memory_fields_in_features():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(a_p=0.5, a_c=0.5, lambda_concurrency=0.0, k_cool=0.0, b_att=0.0),
        env_temperature=20.0,
    )
    base = model.update(
        state={"temperature": 10.0},
        features={"power_total": 2.0, "concurrency": 1.0},
        dt=1.0,
    )
    noisy = model.update(
        state={"temperature": 10.0},
        features={
            "power_total": 2.0,
            "concurrency": 1.0,
            "cpu_util": 0.9,
            "gpu_util": 0.8,
            "memory_util": 0.7,
        },
        dt=1.0,
    )
    assert base["temperature"] == noisy["temperature"]
