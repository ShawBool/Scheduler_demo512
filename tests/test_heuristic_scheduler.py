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
