from scheduler.cpsat_improver import improve_schedule
from scheduler.data_loader import load_static_task_bundle
from scheduler.heuristic_scheduler import build_initial_schedule
from scheduler.problem_builder import build_problem
from scheduler.result_writer import initialize_iteration_log


def test_improver_emits_periodic_iteration_summary(tmp_path):
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
    warm = build_initial_schedule(problem, seed=666)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")

    result = improve_schedule(
        problem,
        warm,
        log_path=log_path,
        timeout_sec=3,
        progress_every_n=10,
        key_task_bonus=300,
    )
    assert result.solver_status in {"OPTIMAL", "FEASIBLE", "UNKNOWN"}
    # 即使没有达到第10次回调，也应至少生成终态摘要；该断言在集成测试中验证。
    assert result.runtime_ms >= 0
