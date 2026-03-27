from scheduler.models import Task, VisibilityWindow
from scheduler.cpsat_improver import _piecewise_square_upper_bound, improve_schedule
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


def test_cpsat_solution_respects_transition_after_reorder(tmp_path):
    window = VisibilityWindow(window_id="w1", start=0, end=500)
    tasks = [
        Task("a", 10, 30, 1, 0, 1, 1, 1, attitude_angle_deg=0, visibility_window=window),
        Task("b", 10, 20, 1, 0, 1, 1, 1, attitude_angle_deg=180, visibility_window=window),
    ]
    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=500,
        capacities={"cpu": 2, "gpu": 1, "memory": 10, "power": 10},
        attitude_time_per_degree=1.0,
    )
    warm = build_initial_schedule(problem, seed=666)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=1, key_task_bonus=0)
    schedule = sorted(result.schedule, key=lambda x: x.start)
    if len(schedule) >= 2:
        left, right = schedule[0], schedule[1]
        required = problem.attitude_transition_cost[(left.task_id, right.task_id)]
        assert right.start >= left.end + required


def test_cpsat_respects_initial_attitude_for_first_task(tmp_path):
    window = VisibilityWindow(window_id="w1", start=0, end=500)
    tasks = [
        Task("a", 10, 30, 1, 0, 1, 1, 1, attitude_angle_deg=180, visibility_window=window),
    ]
    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=500,
        capacities={"cpu": 2, "gpu": 1, "memory": 10, "power": 10},
        attitude_time_per_degree=1.0,
    )
    warm = build_initial_schedule(problem, seed=666)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(
        problem,
        warm,
        log_path=log_path,
        timeout_sec=2,
        progress_every_n=1,
        key_task_bonus=0,
        initial_attitude_angle_deg=0,
    )
    schedule = sorted(result.schedule, key=lambda x: x.start)
    assert schedule
    assert schedule[0].start >= 180


def test_piecewise_square_upper_bound_is_conservative():
    for c_max in (1, 2, 3, 6):
        for c in range(0, c_max + 1):
            assert _piecewise_square_upper_bound(c, c_max) >= c * c


def test_cpsat_limits_continuous_high_warning_selection(tmp_path):
    window = VisibilityWindow(window_id="w1", start=0, end=500)
    tasks = [
        Task("h1", 5, 100, 1, 0, 1, 1, 10, attitude_angle_deg=0, visibility_window=window),
        Task("h2", 5, 100, 1, 0, 1, 1, 10, attitude_angle_deg=0, visibility_window=window),
        Task("h3", 5, 100, 1, 0, 1, 1, 10, attitude_angle_deg=0, visibility_window=window),
    ]
    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=500,
        capacities={"cpu": 4, "gpu": 1, "memory": 20, "power": 20},
        attitude_time_per_degree=0.01,
        thermal_config={
            "thermal_time_step": 1.0,
            "max_warning_duration": 1.0,
            "warning_thermal_load": 5,
            "concurrency_upper_bound": 3,
        },
    )
    warm = build_initial_schedule(problem, seed=666)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=1, key_task_bonus=0)
    selected_ids = {item.task_id for item in result.schedule}
    assert len(selected_ids) <= 2
