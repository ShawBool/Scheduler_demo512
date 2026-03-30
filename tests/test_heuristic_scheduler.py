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


@pytest.fixture
def composite_problem_fixture():
    window = VisibilityWindow(window_id="w1", start=0, end=40)
    tasks = [
        Task(
            task_id="A_HIGH_VALUE",
            duration=5,
            value=100,
            cpu=1,
            gpu=0,
            memory=1,
            power=18,
            thermal_load=8,
            attitude_angle_deg=0,
            visibility_window=window,
        ),
        Task(
            task_id="B_BALANCED_TASK",
            duration=5,
            value=85,
            cpu=1,
            gpu=0,
            memory=1,
            power=4,
            thermal_load=2,
            attitude_angle_deg=0,
            visibility_window=window,
        ),
    ]
    return build_problem(
        tasks,
        {"w1": window},
        horizon=40,
        capacities={"cpu": 2, "gpu": 1, "memory": 20, "power": 30},
        attitude_time_per_degree=0.01,
        thermal_config={
            "thermal_time_step": 1.0,
            "initial_temperature": 25.0,
            "warning_threshold": 40.0,
            "danger_threshold": 100.0,
            "max_warning_duration": 100.0,
            "env_temperature": 20.0,
            "coefficients": {
                "a_p": 0.3,
                "a_c": 0.0,
                "lambda_concurrency": 0.0,
                "k_cool": 0.1,
                "b_att": 0.0,
            },
            "objective_profiles": {
                "base": {
                    "task_value": 0.1,
                    "completion": 0.2,
                    "association": 0.0,
                    "thermal_safety": 0.6,
                    "power_smoothing": 0.1,
                    "resource_utilization": 0.0,
                    "smoothness": 0.0,
                },
            },
        },
    )


def test_heuristic_prefers_higher_composite_score_over_raw_value(composite_problem_fixture):
    result = build_initial_schedule(composite_problem_fixture, seed=7, initial_attitude_angle_deg=0)
    assert result.schedule[0].task_id == "B_BALANCED_TASK"


def test_heuristic_keeps_static_base_profile_when_temperature_high(composite_problem_fixture):
    hot_problem = composite_problem_fixture
    hot_problem.thermal_config["initial_temperature"] = 81.0
    hot_problem.thermal_config["danger_threshold"] = 100.0

    result = build_initial_schedule(hot_problem, seed=8, initial_attitude_angle_deg=0)
    assert result.solver_metadata["active_weight_profile"] == "base"
    assert result.solver_metadata["switch_reason"] == "static_profile"


def test_heuristic_keeps_static_base_profile_when_temperature_low(composite_problem_fixture):
    cool_problem = composite_problem_fixture
    cool_problem.thermal_config["initial_temperature"] = 50.0
    cool_problem.thermal_config["danger_threshold"] = 100.0

    result = build_initial_schedule(cool_problem, seed=9, initial_attitude_angle_deg=0)
    assert result.solver_metadata["active_weight_profile"] == "base"
    assert result.solver_metadata["switch_reason"] == "static_profile"


def test_heuristic_uses_constraint_value_engine_for_thermal_scoring(monkeypatch, composite_problem_fixture):
    import scheduler.constraint_value_engine as cve

    called = {"hit": False}

    def fake_score_task_candidate(*args, **kwargs):
        called["hit"] = True
        return {"total_score": 1.0, "objective_breakdown": {"thermal_safety": 1.0}}

    monkeypatch.setattr(cve, "score_task_candidate", fake_score_task_candidate)
    build_initial_schedule(composite_problem_fixture, seed=1, initial_attitude_angle_deg=0)

    assert called["hit"] is True
