from scheduler.thermal_model import (
    NoOpThermalModel,
    SemiEmpiricalThermalModelV1,
    ThermalCoefficients,
    derive_concurrency,
)


def test_concurrency_is_derived_from_resource_utilization_not_direct_literal():
    features = {
        "cpu_used": 2.0,
        "gpu_used": 1.0,
        "cpu_capacity": 4.0,
        "gpu_capacity": 2.0,
    }
    assert derive_concurrency(features) == 1.0


def test_update_temperature_includes_quadratic_concurrency_term():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(
            a_p=0.1,
            a_c=0.0,
            lambda_concurrency=0.2,
            k_cool=0.0,
        ),
        env_temperature=20.0,
    )

    nxt = model.update(
        state={"temperature": 30.0},
        features={
            "power_total": 1.0,
            "cpu_used": 2.0,
            "gpu_used": 1.0,
            "cpu_capacity": 4.0,
            "gpu_capacity": 2.0,
        },
        dt=1.0,
    )

    assert nxt["temperature"] == 30.3


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
        ),
        env_temperature=20.0,
    )

    nxt = model.update(
        state={"temperature": 20.0},
        features={
            "power_total": 0.0,
            "cpu_used": 0.0,
            "gpu_used": 0.0,
            "cpu_capacity": 4.0,
            "gpu_capacity": 2.0,
        },
        dt=1.0,
    )

    assert nxt["temperature"] == 20.0


def test_update_falls_back_to_direct_concurrency_when_capacity_missing():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(
            a_p=0.1,
            a_c=0.0,
            lambda_concurrency=0.2,
            k_cool=0.0,
        ),
        env_temperature=20.0,
    )

    nxt = model.update(
        state={"temperature": 30.0},
        features={
            "power_total": 1.0,
            "concurrency": 1.0,
        },
        dt=1.0,
    )

    assert nxt["temperature"] == 30.3


def test_noop_model_returns_input_temperature():
    model = NoOpThermalModel()
    nxt = model.update(state={"temperature": 42.0}, features={}, dt=1.0)
    assert nxt["temperature"] == 42.0


def test_model_ignores_cpu_gpu_memory_fields_in_features():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(a_p=0.5, a_c=0.5, lambda_concurrency=0.0, k_cool=0.0),
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
