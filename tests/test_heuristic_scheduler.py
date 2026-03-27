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
