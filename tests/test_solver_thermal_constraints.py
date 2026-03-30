from scheduler.cpsat_improver import improve_schedule
from scheduler.heuristic_scheduler import build_initial_schedule
from scheduler.models import Task, VisibilityWindow
from scheduler.problem_builder import build_problem
from scheduler.result_writer import initialize_iteration_log


def _build_high_thermal_overlap_problem():
    w1 = VisibilityWindow(window_id="w1", start=0, end=20)
    w2 = VisibilityWindow(window_id="w2", start=30, end=50)
    tasks = [
        Task("h1", 5, 100, 1, 0, 1, 2, 10, attitude_angle_deg=0, visibility_window=w1),
        Task("h2", 5, 100, 1, 0, 1, 2, 10, attitude_angle_deg=0, visibility_window=w2),
    ]
    return build_problem(
        tasks,
        {"w1": w1, "w2": w2},
        horizon=60,
        capacities={"cpu": 4, "gpu": 1, "memory": 20, "power": 20},
        attitude_time_per_degree=0.01,
        thermal_config={
            "thermal_time_step": 1.0,
            "max_warning_duration": 1.0,
            "warning_thermal_load": 5,
            "thermal_concurrency_limit": 1,
        },
    )


def test_high_thermal_load_limit_uses_real_start_time_not_topology(tmp_path):
    problem = _build_high_thermal_overlap_problem()
    warm = build_initial_schedule(problem, seed=1)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(
        problem,
        warm,
        log_path=log_path,
        timeout_sec=2,
        progress_every_n=5,
        key_task_bonus=0,
        initial_attitude_angle_deg=0,
    )
    assert result.solver_status in {"OPTIMAL", "FEASIBLE"}
    assert {item.task_id for item in result.schedule} == {"h1", "h2"}
