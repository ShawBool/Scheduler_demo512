from scheduler.constraint_value_engine import simulate_task_trace_with_thermal_model
from scheduler.models import Task


def test_thermal_trace_uses_same_model_kernel_as_thermal_model_module():
    task = Task(
        task_id="t1",
        duration=3,
        value=1,
        cpu=2,
        gpu=1,
        memory=1,
        power=10,
        thermal_load=2,
    )
    trace = simulate_task_trace_with_thermal_model(
        task=task,
        initial_temperature=25.0,
        capacities={"cpu": 4, "gpu": 2},
        thermal_cfg={
            "thermal_time_step": 1.0,
            "env_temperature": 20.0,
            "coefficients": {
                "a_p": 0.002,
                "a_c": 0.03,
                "lambda_concurrency": 0.01,
                "k_cool": 0.005,
            },
        },
    )

    assert len(trace) == 3
    assert trace[-1] > trace[0]
