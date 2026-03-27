import pytest

from scheduler.models import Task, VisibilityWindow
from scheduler.data_loader import load_static_task_bundle
from scheduler.heuristic_scheduler import build_initial_schedule
from scheduler.problem_builder import build_problem


def test_heuristic_prioritizes_key_tasks():
    cfg = {
        "runtime": {
            "static_tasks_file": "data/latest_small_tasks_pool.json",
            "static_windows_file": "data/latest_windows.json",
        }
    }
    tasks, windows, _ = load_static_task_bundle(cfg)
    problem = build_problem(
        tasks,
        windows,
        horizon=240,
        capacities={"cpu": 4, "gpu": 2, "memory": 512, "power": 60},
        attitude_time_per_degree=0.01,
    )
    result = build_initial_schedule(problem, seed=666)
    assert len(result.schedule) > 0
    assert any(item.is_key_task for item in result.schedule)


def test_heuristic_respects_attitude_transition_time():
    window = VisibilityWindow(window_id="w1", start=0, end=500)
    tasks = [
        Task(
            task_id="t1",
            duration=10,
            value=10,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            thermal_load=1,
            attitude_angle_deg=0,
            visibility_window=window,
        ),
        Task(
            task_id="t2",
            duration=10,
            value=10,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            thermal_load=1,
            attitude_angle_deg=180,
            visibility_window=window,
        ),
    ]

    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=500,
        capacities={"cpu": 2, "gpu": 1, "memory": 10, "power": 10},
        attitude_time_per_degree=1.0,
    )
    result = build_initial_schedule(problem, seed=666)
    schedule = {item.task_id: item for item in result.schedule}
    assert schedule["t2"].start >= schedule["t1"].end + 180


@pytest.fixture
def thermal_problem_fixture():
    window = VisibilityWindow(window_id="w1", start=0, end=200)
    tasks = [
        Task(
            task_id="HOT_TASK",
            duration=10,
            value=100,
            cpu=1,
            gpu=1,
            memory=10,
            power=20,
            thermal_load=20,
            attitude_angle_deg=0,
            visibility_window=window,
        ),
        Task(
            task_id="COOLER_TASK",
            duration=10,
            value=50,
            cpu=1,
            gpu=0,
            memory=10,
            power=2,
            thermal_load=1,
            attitude_angle_deg=0,
            visibility_window=window,
        ),
    ]

    return build_problem(
        tasks,
        {"w1": window},
        horizon=200,
        capacities={"cpu": 2, "gpu": 1, "memory": 64, "power": 30},
        attitude_time_per_degree=0.01,
        thermal_config={
            "thermal_time_step": 1.0,
            "initial_temperature": 25.0,
            "warning_threshold": 27.0,
            "danger_threshold": 28.0,
            "max_warning_duration": 100,
            "env_temperature": 20.0,
            "coefficients": {
                "a_p": 0.02,
                "a_c": 0.02,
                "lambda_concurrency": 0.01,
                "k_cool": 0.0,
                "b_att": 0.0,
            },
        },
    )


def test_heuristic_rejects_candidate_when_danger_threshold_would_be_exceeded(thermal_problem_fixture):
    result = build_initial_schedule(thermal_problem_fixture, seed=1, initial_attitude_angle_deg=0)
    assert all(item.task_id != "HOT_TASK" for item in result.schedule)


def test_heuristic_prefers_lower_thermal_penalty_start_time_when_both_feasible():
    window = VisibilityWindow(window_id="w1", start=0, end=30)
    tasks = [
        Task(
            task_id="HOT_BUT_FEASIBLE",
            duration=2,
            value=10,
            cpu=1,
            gpu=0,
            memory=1,
            power=10,
            thermal_load=1,
            attitude_angle_deg=0,
            visibility_window=window,
        )
    ]
    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=30,
        capacities={"cpu": 2, "gpu": 1, "memory": 64, "power": 20},
        attitude_time_per_degree=0.01,
        thermal_config={
            "thermal_time_step": 1.0,
            "initial_temperature": 29.5,
            "warning_threshold": 30.0,
            "danger_threshold": 100.0,
            "max_warning_duration": 100.0,
            "env_temperature": 20.0,
            "coefficients": {
                "a_p": 1.0,
                "a_c": 0.0,
                "lambda_concurrency": 0.0,
                "k_cool": 0.5,
                "b_att": 0.0,
            },
        },
    )

    result = build_initial_schedule(problem, seed=1, initial_attitude_angle_deg=0)
    assert result.schedule[0].start > 0


def test_heuristic_rejects_candidate_exceeding_max_warning_duration():
    window = VisibilityWindow(window_id="w1", start=0, end=20)
    tasks = [
        Task(
            task_id="LONG_WARNING_TASK",
            duration=3,
            value=10,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            thermal_load=1,
            attitude_angle_deg=0,
            visibility_window=window,
        )
    ]
    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=20,
        capacities={"cpu": 2, "gpu": 1, "memory": 64, "power": 20},
        attitude_time_per_degree=0.01,
        thermal_config={
            "thermal_time_step": 1.0,
            "initial_temperature": 30.0,
            "warning_threshold": 29.0,
            "danger_threshold": 35.0,
            "max_warning_duration": 2.0,
            "env_temperature": 20.0,
            "coefficients": {
                "a_p": 0.0,
                "a_c": 0.0,
                "lambda_concurrency": 0.0,
                "k_cool": 0.0,
                "b_att": 0.0,
            },
        },
    )

    result = build_initial_schedule(problem, seed=1, initial_attitude_angle_deg=0)
    assert "LONG_WARNING_TASK" not in {item.task_id for item in result.schedule}


def test_heuristic_allows_candidate_at_warning_duration_boundary():
    window = VisibilityWindow(window_id="w1", start=0, end=20)
    tasks = [
        Task(
            task_id="BOUNDARY_WARNING_TASK",
            duration=2,
            value=10,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            thermal_load=1,
            attitude_angle_deg=0,
            visibility_window=window,
        )
    ]
    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=20,
        capacities={"cpu": 2, "gpu": 1, "memory": 64, "power": 20},
        attitude_time_per_degree=0.01,
        thermal_config={
            "thermal_time_step": 1.0,
            "initial_temperature": 30.0,
            "warning_threshold": 29.0,
            "danger_threshold": 35.0,
            "max_warning_duration": 2.0,
            "env_temperature": 20.0,
            "coefficients": {
                "a_p": 0.0,
                "a_c": 0.0,
                "lambda_concurrency": 0.0,
                "k_cool": 0.0,
                "b_att": 0.0,
            },
        },
    )

    result = build_initial_schedule(problem, seed=1, initial_attitude_angle_deg=0)
    assert "BOUNDARY_WARNING_TASK" in {item.task_id for item in result.schedule}
