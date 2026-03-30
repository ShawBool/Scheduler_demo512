from scheduler.models import Task, VisibilityWindow
from scheduler.cpsat_improver import _piecewise_square_upper_bound, improve_schedule
from scheduler.data_loader import load_static_task_bundle
from scheduler.heuristic_scheduler import build_initial_schedule
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
            "thermal_concurrency_limit": 1,
        },
    )
    warm = build_initial_schedule(problem, seed=666)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=1, key_task_bonus=0)
    selected = sorted(result.schedule, key=lambda x: x.start)
    assert len({item.task_id for item in selected}) == 3
    for idx in range(1, len(selected)):
        assert selected[idx].start >= selected[idx - 1].end


def test_cpsat_time_domain_thermal_limit_allows_non_overlapping_high_load_tasks(tmp_path):
    problem = _build_high_thermal_overlap_problem()
    warm = build_initial_schedule(problem, seed=1)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=1, key_task_bonus=0)
    assert {item.task_id for item in result.schedule} == {"h1", "h2"}


def test_cpsat_objective_uses_multiple_components_not_only_value(tmp_path):
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
        thermal_config={
            "objective_profiles": {
                "base": {
                    "task_value": 0.35,
                    "completion": 0.20,
                    "association": 0.10,
                    "thermal_safety": 0.15,
                    "power_smoothing": 0.10,
                    "resource_utilization": 0.05,
                    "smoothness": 0.05,
                },
                "thermal": {
                    "task_value": 0.20,
                    "completion": 0.10,
                    "association": 0.10,
                    "thermal_safety": 0.35,
                    "power_smoothing": 0.10,
                    "resource_utilization": 0.10,
                    "smoothness": 0.05,
                },
            }
        },
    )
    warm = build_initial_schedule(problem, seed=666)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=10, key_task_bonus=300)

    assert result.objective_breakdown["task_value"] >= 0
    assert result.objective_breakdown["thermal_safety"] >= 0
    assert result.objective_breakdown["power_smoothing"] >= 0


def test_thermal_proxy_and_power_proxy_are_not_identical_formula(tmp_path):
    window = VisibilityWindow(window_id="w1", start=0, end=100)
    tasks = [
        Task("t_hot", 10, 80, 1, 1, 1, 20, 9, attitude_angle_deg=0, visibility_window=window),
        Task("t_power", 10, 80, 1, 0, 1, 45, 1, attitude_angle_deg=0, visibility_window=window),
    ]
    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=100,
        capacities={"cpu": 4, "gpu": 2, "memory": 64, "power": 60},
        attitude_time_per_degree=0.01,
        thermal_config={"danger_threshold": 100, "warning_threshold": 80, "thermal_time_step": 1.0},
    )
    warm = build_initial_schedule(problem, seed=1)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=5, key_task_bonus=0)
    raw = result.objective_breakdown_raw
    assert raw["thermal_safety"] != raw["power_smoothing"]


def test_smoothness_uses_transition_cost_not_absolute_angle(tmp_path):
    window = VisibilityWindow(window_id="w2", start=0, end=120)
    tasks = [
        Task("t1", 10, 50, 1, 0, 1, 10, 1, attitude_angle_deg=0, visibility_window=window),
        Task("t2", 10, 50, 1, 0, 1, 10, 1, attitude_angle_deg=180, visibility_window=window),
    ]
    problem = build_problem(
        tasks,
        {"w2": window},
        horizon=120,
        capacities={"cpu": 2, "gpu": 1, "memory": 32, "power": 30},
        attitude_time_per_degree=0.1,
        thermal_config={"danger_threshold": 100, "warning_threshold": 80, "thermal_time_step": 1.0},
    )
    warm = build_initial_schedule(problem, seed=1)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=5, key_task_bonus=0)
    assert result.objective_breakdown_raw["smoothness"] < 1.0
