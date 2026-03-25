from scheduler.data_loader import load_static_task_bundle
from scheduler.problem_builder import build_problem


def test_build_problem_computes_topological_order():
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
    assert len(problem.topological_tasks) == len(tasks)
    assert "group01_att" in problem.topological_tasks
    assert problem.attitude_transition_cost[("group01_radar", "group01_relay")] >= 0
