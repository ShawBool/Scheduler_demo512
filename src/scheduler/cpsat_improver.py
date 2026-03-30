"""CP-SAT 限时改进器。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ortools.sat.python import cp_model

from .heuristic_scheduler import HeuristicResult
from .objective_engine import build_scale_config, normalize_to_scale, select_active_weights
from .models import ScheduleItem, Task, UnscheduledItem
from .problem_builder import ProblemInstance
from .result_writer import append_iteration_log


@dataclass(slots=True)
class ImproveResult:
    schedule: list[ScheduleItem]
    unscheduled: list[UnscheduledItem]
    solver_status: str
    objective_value: float
    iteration_log_count: int
    runtime_ms: int
    objective_breakdown: dict[str, float]
    objective_breakdown_raw: dict[str, float]
    active_weight_profile: str
    switch_reason: str


def _piecewise_square_upper_bound(c: int, c_max: int) -> int:
    """并发平方项保守上界。"""
    if c_max <= 0:
        return 0
    c_int = max(0, min(int(c), int(c_max)))
    c_max_int = int(c_max)
    if c_max_int < 3:
        return c_max_int * c_int

    c1 = c_max_int // 3
    c2 = (2 * c_max_int) // 3
    if c1 <= 0:
        c1 = 1
    if c2 <= c1:
        c2 = c1 + 1

    bounds: list[int] = []
    for left, right in ((0, c1), (c1, c2), (c2, c_max_int)):
        if right == left:
            bounds.append(right * right)
            continue
        slope = (right * right - left * left) / (right - left)
        intercept = left * left - slope * left
        bounds.append(int(round(slope * c_int + intercept)))
    return max(bounds)


class _ProgressCallback(cp_model.CpSolverSolutionCallback):
    """解回调：按配置周期写出中间摘要。"""

    def __init__(
        self,
        *,
        log_path: Path,
        progress_every_n: int,
        key_task_ids: set[str],
        selected_vars: dict[str, cp_model.IntVar],
        objective_expr: cp_model.LinearExpr,
    ) -> None:
        super().__init__()
        self._log_path = log_path
        self._progress_every_n = progress_every_n
        self._key_task_ids = key_task_ids
        self._selected_vars = selected_vars
        self._objective_expr = objective_expr
        self.solution_count = 0
        self.log_count = 0

    def on_solution_callback(self) -> None:
        self.solution_count += 1
        if self.solution_count % self._progress_every_n != 0:
            return

        selected = {tid for tid, var in self._selected_vars.items() if self.Value(var) == 1}
        key_done = len(selected & self._key_task_ids)
        append_iteration_log(
            self._log_path,
            {
                "phase": "progress",
                "iteration": self.solution_count,
                "objective_value": float(self.Value(self._objective_expr)),
                "scheduled_task_count": len(selected),
                "key_task_scheduled_count": key_done,
                "unscheduled_task_count": len(self._selected_vars) - len(selected),
                "feasible": True,
                "improvement_delta": 0,
                "note": "periodic_solution",
            },
        )
        self.log_count += 1


def _safe_window_bounds(task: Task, horizon: int) -> tuple[int, int]:
    earliest = 0
    latest = horizon - task.duration
    if task.visibility_window is not None:
        earliest = max(earliest, task.visibility_window.start)
        latest = min(latest, task.visibility_window.end - task.duration)
    return earliest, latest


def _transition_time_from_initial(initial_angle: float, task_angle: float | None, per_degree: float) -> int:
    if task_angle is None:
        return 0
    delta = abs(float(initial_angle) - float(task_angle))
    delta = min(delta, 360.0 - delta)
    return int(round(delta * per_degree))


def improve_schedule(
    problem: ProblemInstance,
    warm_start: HeuristicResult,
    *,
    log_path: str | Path,
    timeout_sec: float,
    progress_every_n: int,
    key_task_bonus: float,
    initial_attitude_angle_deg: float = 0.0,
    active_profile: str | None = None,
) -> ImproveResult:
    """使用可选区间 + 累积约束构建 CP-SAT，并在时限内优化。"""
    started = time.perf_counter()
    model = cp_model.CpModel()

    starts: dict[str, cp_model.IntVar] = {}
    ends: dict[str, cp_model.IntVar] = {}
    selected: dict[str, cp_model.IntVar] = {}
    intervals: dict[str, cp_model.IntervalVar] = {}

    for task in problem.tasks:
        earliest, latest = _safe_window_bounds(task, problem.horizon)
        if latest < earliest:
            # 明确无窗口可行域时，不允许被选择。
            sel = model.NewBoolVar(f"sel_{task.task_id}")
            model.Add(sel == 0)
            selected[task.task_id] = sel
            starts[task.task_id] = model.NewIntVar(0, 0, f"start_{task.task_id}")
            ends[task.task_id] = model.NewIntVar(0, 0, f"end_{task.task_id}")
            continue

        start = model.NewIntVar(earliest, latest, f"start_{task.task_id}")
        end = model.NewIntVar(earliest + task.duration, latest + task.duration, f"end_{task.task_id}")
        sel = model.NewBoolVar(f"sel_{task.task_id}")
        interval = model.NewOptionalIntervalVar(start, task.duration, end, sel, f"iv_{task.task_id}")

        starts[task.task_id] = start
        ends[task.task_id] = end
        selected[task.task_id] = sel
        intervals[task.task_id] = interval

    for task in problem.tasks:
        for pred in task.predecessors:
            model.Add(selected[task.task_id] <= selected[pred])
            model.Add(starts[task.task_id] >= ends[pred]).OnlyEnforceIf([selected[task.task_id], selected[pred]])

    # 初始姿态约束：被选中的任务开始时间必须不早于从初始姿态转到目标姿态的最短时间。
    for task in problem.tasks:
        init_transition = _transition_time_from_initial(
            initial_attitude_angle_deg,
            task.attitude_angle_deg,
            problem.attitude_time_per_degree,
        )
        if init_transition > 0:
            model.Add(starts[task.task_id] >= init_transition).OnlyEnforceIf(selected[task.task_id])

    # 隐式姿态切换约束：当两个有姿态任务都被选中时，必须满足二选一顺序与对应转姿间隔。
    transition_cost_vars: list[cp_model.IntVar] = []
    max_transition_cost = max(problem.attitude_transition_cost.values(), default=1)
    for left_idx in range(len(problem.tasks)):
        left = problem.tasks[left_idx]
        if left.attitude_angle_deg is None:
            continue
        for right_idx in range(left_idx + 1, len(problem.tasks)):
            right = problem.tasks[right_idx]
            if right.attitude_angle_deg is None:
                continue

            left_before_right = model.NewBoolVar(f"ord_{left.task_id}_before_{right.task_id}")
            lr_gap = int(problem.attitude_transition_cost[(left.task_id, right.task_id)])
            rl_gap = int(problem.attitude_transition_cost[(right.task_id, left.task_id)])

            model.Add(starts[right.task_id] >= ends[left.task_id] + lr_gap).OnlyEnforceIf(
                [selected[left.task_id], selected[right.task_id], left_before_right]
            )
            model.Add(starts[left.task_id] >= ends[right.task_id] + rl_gap).OnlyEnforceIf(
                [selected[left.task_id], selected[right.task_id], left_before_right.Not()]
            )

            # 工程语义：平滑度应惩罚“真实转姿成本”，而非绝对姿态角。
            # pair_active 表示两个任务都被选择，cost_var 表示这对任务的实际转姿代价。
            pair_active = model.NewBoolVar(f"pair_{left.task_id}_{right.task_id}")
            model.AddBoolAnd([selected[left.task_id], selected[right.task_id]]).OnlyEnforceIf(pair_active)
            model.AddBoolOr([selected[left.task_id].Not(), selected[right.task_id].Not(), pair_active])

            cost_var = model.NewIntVar(0, max_transition_cost, f"transition_cost_{left.task_id}_{right.task_id}")
            model.Add(cost_var == 0).OnlyEnforceIf(pair_active.Not())
            model.Add(cost_var == lr_gap).OnlyEnforceIf([pair_active, left_before_right])
            model.Add(cost_var == rl_gap).OnlyEnforceIf([pair_active, left_before_right.Not()])
            transition_cost_vars.append(cost_var)

    thermal_cfg = problem.thermal_config or {}
    profiles = thermal_cfg.get("objective_profiles", {})
    base_weights = profiles.get(
        "base",
        {
            "task_value": 0.4,
            "completion": 0.15,
            "association": 0.1,
            "thermal_safety": 0.15,
            "power_smoothing": 0.1,
            "resource_utilization": 0.05,
            "smoothness": 0.05,
        },
    )
    thermal_weights = profiles.get("thermal", base_weights)
    trigger_ratio = float(thermal_cfg.get("thermal_weight_trigger_ratio", 0.8))
    init_temp = float(thermal_cfg.get("initial_temperature", 25.0))
    danger_temp = float(thermal_cfg.get("danger_threshold", 100.0))
    dynamic_enabled = bool(thermal_cfg.get("dynamic_weight_enable", True))

    if active_profile in {"base", "thermal"}:
        if active_profile == "thermal":
            active_weights, switch_reason = select_active_weights(
                base_weights=base_weights,
                thermal_weights=thermal_weights,
                thermal_ratio=1.0,
                trigger_threshold=0.0,
            )
            active_profile = "thermal"
            switch_reason = "forced_thermal_profile"
        else:
            active_weights, switch_reason = select_active_weights(
                base_weights=base_weights,
                thermal_weights=thermal_weights,
                thermal_ratio=0.0,
                trigger_threshold=1.0,
            )
            active_profile = "base"
            switch_reason = "forced_base_profile"
    elif dynamic_enabled:
        active_weights, switch_reason = select_active_weights(
            base_weights=base_weights,
            thermal_weights=thermal_weights,
            thermal_ratio=init_temp / max(danger_temp, 1e-6),
            trigger_threshold=trigger_ratio,
        )
        active_profile = "thermal" if switch_reason != "base_profile" else "base"
    else:
        active_weights, switch_reason = (base_weights, "base_profile")
        active_profile = "base"

    scale_cfg = build_scale_config(thermal_cfg.get("objective_scaling", {}), target_min=0.0, target_max=1.0)
    objective_ranges = scale_cfg.ranges
    component_scale = max(int(thermal_cfg.get("objective_component_scale", 1000)), 1)
    weight_scale = max(int(thermal_cfg.get("objective_weight_scale", 1000)), 1)

    def _coef(metric: str, raw: float) -> int:
        low, high = objective_ranges.get(metric, (0.0, 1.0))
        scaled = normalize_to_scale(
            raw=float(raw),
            lower=float(low),
            upper=float(high),
            target_min=0.0,
            target_max=float(component_scale),
        )
        return int(round(scaled))

    # 关键任务仍是“尽量必排”，通过目标奖励提升优先级，而非强制必须选中。
    total_tasks = max(len(problem.tasks), 1)
    max_pred_count = max(max((len(task.predecessors) for task in problem.tasks), default=0), 1)
    max_thermal_load = max((float(task.thermal_load) for task in problem.tasks), default=1.0)
    power_capacity = max(float(problem.capacities["power"]), 1.0)
    cpu_capacity = max(float(problem.capacities["cpu"]), 1.0)
    gpu_capacity = max(float(problem.capacities["gpu"]), 1.0)
    safe_power_ratio = float(thermal_cfg.get("power_safe_ratio", 0.7))
    safe_power_limit = max(0.0, min(power_capacity, power_capacity * safe_power_ratio))

    task_value_expr = sum(
        _coef("task_value", float(task.value) + (key_task_bonus if task.is_key_task else 0.0)) * selected[task.task_id]
        for task in problem.tasks
    )
    completion_step = _coef("completion", 1.0 / float(total_tasks))
    completion_expr = completion_step * sum(selected[task.task_id] for task in problem.tasks)
    association_expr = sum(
        _coef("association", float(len(task.predecessors)) / float(max_pred_count)) * selected[task.task_id]
        for task in problem.tasks
    )
    thermal_proxy_expr = sum(
        _coef("thermal_safety", min(1.0, float(task.thermal_load) / max(max_thermal_load, 1e-6))) * selected[task.task_id]
        for task in problem.tasks
    )
    power_proxy_expr = sum(
        _coef("power_smoothing", max(0.0, float(task.power) - safe_power_limit) / power_capacity) * selected[task.task_id]
        for task in problem.tasks
    )
    utilization_expr = sum(
        _coef(
            "resource_utilization",
            min(1.0, float(task.cpu) / cpu_capacity + float(task.gpu) / gpu_capacity),
        )
        * selected[task.task_id]
        for task in problem.tasks
    )
    transition_scale = max(max_transition_cost, 1)
    smoothness_proxy_expr: cp_model.LinearExpr = 0
    if transition_cost_vars:
        smoothness_unit = max(1, int(round(component_scale / float(transition_scale))))
        smoothness_proxy_expr = smoothness_unit * sum(transition_cost_vars)

    objective_terms: list[cp_model.LinearExpr] = []
    objective_terms.append(int(active_weights.get("task_value", 0.0) * weight_scale) * task_value_expr)
    objective_terms.append(int(active_weights.get("completion", 0.0) * weight_scale) * completion_expr)
    objective_terms.append(int(active_weights.get("association", 0.0) * weight_scale) * association_expr)
    objective_terms.append(-int(active_weights.get("thermal_safety", 0.0) * weight_scale) * thermal_proxy_expr)
    objective_terms.append(-int(active_weights.get("power_smoothing", 0.0) * weight_scale) * power_proxy_expr)
    objective_terms.append(int(active_weights.get("resource_utilization", 0.0) * weight_scale) * utilization_expr)
    objective_terms.append(-int(active_weights.get("smoothness", 0.0) * weight_scale) * smoothness_proxy_expr)

    warning_load = thermal_cfg.get("warning_thermal_load")
    if isinstance(warning_load, (int, float)):
        thermal_concurrency_limit = max(1, int(thermal_cfg.get("thermal_concurrency_limit", 1)))
        high_heat_intervals = [
            intervals[task.task_id]
            for task in problem.tasks
            if task.task_id in intervals and float(task.thermal_load) >= float(warning_load)
        ]
        if high_heat_intervals:
            # 工程语义：在真实时间轴限制高热任务并发，而非按拓扑序窗口截断。
            model.AddCumulative(high_heat_intervals, [1] * len(high_heat_intervals), thermal_concurrency_limit)

    # 资源累积约束：每种资源都是一个容量约束。
    all_intervals = [intervals[tid] for tid in intervals]
    model.AddCumulative(all_intervals, [problem.task_map[tid].cpu for tid in intervals], problem.capacities["cpu"])
    model.AddCumulative(all_intervals, [problem.task_map[tid].gpu for tid in intervals], problem.capacities["gpu"])
    model.AddCumulative(all_intervals, [problem.task_map[tid].memory for tid in intervals], problem.capacities["memory"])
    model.AddCumulative(all_intervals, [problem.task_map[tid].power for tid in intervals], problem.capacities["power"])

    objective_expr = sum(objective_terms)
    model.Maximize(objective_expr)

    # 使用 warm start 引导搜索，提高找到高质量解的概率。
    warm_map = {item.task_id: item for item in warm_start.schedule}
    for task in problem.tasks:
        if task.task_id in warm_map and task.task_id in intervals:
            model.AddHint(selected[task.task_id], 1)
            model.AddHint(starts[task.task_id], warm_map[task.task_id].start)
        else:
            model.AddHint(selected[task.task_id], 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_sec
    solver.parameters.num_search_workers = 8

    key_task_ids = {t.task_id for t in problem.tasks if t.is_key_task}
    callback = _ProgressCallback(
        log_path=Path(log_path),
        progress_every_n=progress_every_n,
        key_task_ids=key_task_ids,
        selected_vars=selected,
        objective_expr=objective_expr,
    )

    status = solver.Solve(model, callback)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        runtime_ms = int((time.perf_counter() - started) * 1000)
        return ImproveResult(
            schedule=warm_start.schedule,
            unscheduled=warm_start.unscheduled,
            solver_status=solver.StatusName(status),
            objective_value=0.0,
            iteration_log_count=callback.log_count,
            runtime_ms=runtime_ms,
            objective_breakdown={
                "task_value": 0.0,
                "completion": 0.0,
                "association": 0.0,
                "thermal_safety": 0.0,
                "power_smoothing": 0.0,
                "resource_utilization": 0.0,
                "smoothness": 0.0,
            },
            objective_breakdown_raw={
                "task_value": 0.0,
                "completion": 0.0,
                "association": 0.0,
                "thermal_safety": 0.0,
                "power_smoothing": 0.0,
                "resource_utilization": 0.0,
                "smoothness": 0.0,
            },
            active_weight_profile=active_profile,
            switch_reason=switch_reason,
        )

    chosen: list[ScheduleItem] = []
    unscheduled: list[UnscheduledItem] = []

    for task in problem.tasks:
        if solver.Value(selected[task.task_id]) == 1:
            start = solver.Value(starts[task.task_id])
            chosen.append(
                ScheduleItem(
                    task_id=task.task_id,
                    start=start,
                    end=start + task.duration,
                    value=task.value,
                    is_key_task=task.is_key_task,
                    visibility_window_id=task.visibility_window.window_id if task.visibility_window else None,
                )
            )
        else:
            reason = "solver_timeout_best_effort" if status == cp_model.FEASIBLE else "resource_conflict"
            unscheduled.append(
                UnscheduledItem(
                    task_id=task.task_id,
                    reason_code=reason,
                    reason_detail="not selected in final CP-SAT solution",
                )
            )

    chosen.sort(key=lambda x: (x.start, x.task_id))
    if chosen:
        avg_value = sum(float(item.value) for item in chosen) / len(chosen)
        avg_power = sum(float(problem.task_map[item.task_id].power) for item in chosen) / len(chosen)
        avg_thermal_load = sum(float(problem.task_map[item.task_id].thermal_load) for item in chosen) / len(chosen)
        avg_transition = 0.0
        for idx in range(1, len(chosen)):
            left = problem.task_map[chosen[idx - 1].task_id]
            right = problem.task_map[chosen[idx].task_id]
            avg_transition += float(problem.attitude_transition_cost[(left.task_id, right.task_id)])
        avg_transition = avg_transition / max(len(chosen) - 1, 1)
    else:
        avg_value = 0.0
        avg_power = 0.0
        avg_thermal_load = 0.0
        avg_transition = 0.0

    total_tasks = max(len(problem.tasks), 1)
    completion_ratio = len(chosen) / total_tasks
    association_ratio = sum(1 for item in chosen if problem.task_map[item.task_id].predecessors) / max(len(chosen), 1)
    thermal_safety_ratio = max(0.0, 1.0 - min(1.0, avg_thermal_load / max(max_thermal_load, 1e-6)))
    power_over = max(0.0, avg_power - safe_power_limit)
    power_denominator = max(power_capacity - safe_power_limit, 1.0)
    power_smoothing_ratio = max(0.0, 1.0 - min(1.0, power_over / power_denominator))
    utilization_ratio = min(
        1.0,
        sum(problem.task_map[item.task_id].cpu + problem.task_map[item.task_id].gpu for item in chosen)
        / max(float(len(chosen) * (problem.capacities["cpu"] + problem.capacities["gpu"])), 1.0),
    )
    smoothness_ratio = max(0.0, 1.0 - min(1.0, avg_transition / max(float(transition_scale), 1.0)))

    raw_breakdown = {
        "task_value": avg_value,
        "completion": completion_ratio,
        "association": association_ratio,
        "thermal_safety": thermal_safety_ratio,
        "power_smoothing": power_smoothing_ratio,
        "resource_utilization": utilization_ratio,
        "smoothness": smoothness_ratio,
    }
    objective_breakdown = {
        "task_value": normalize_to_scale(
            avg_value,
            objective_ranges["task_value"][0],
            objective_ranges["task_value"][1],
            target_min=0.0,
            target_max=100.0,
        ),
        "completion": normalize_to_scale(
            completion_ratio,
            objective_ranges["completion"][0],
            objective_ranges["completion"][1],
            target_min=0.0,
            target_max=100.0,
        ),
        "association": normalize_to_scale(
            association_ratio,
            objective_ranges["association"][0],
            objective_ranges["association"][1],
            target_min=0.0,
            target_max=100.0,
        ),
        "thermal_safety": normalize_to_scale(
            thermal_safety_ratio,
            objective_ranges["thermal_safety"][0],
            objective_ranges["thermal_safety"][1],
            target_min=0.0,
            target_max=100.0,
        ),
        "power_smoothing": normalize_to_scale(
            power_smoothing_ratio,
            objective_ranges["power_smoothing"][0],
            objective_ranges["power_smoothing"][1],
            target_min=0.0,
            target_max=100.0,
        ),
        "resource_utilization": normalize_to_scale(
            utilization_ratio,
            objective_ranges["resource_utilization"][0],
            objective_ranges["resource_utilization"][1],
            target_min=0.0,
            target_max=100.0,
        ),
        "smoothness": normalize_to_scale(
            smoothness_ratio,
            objective_ranges["smoothness"][0],
            objective_ranges["smoothness"][1],
            target_min=0.0,
            target_max=100.0,
        ),
    }
    runtime_ms = int((time.perf_counter() - started) * 1000)
    return ImproveResult(
        schedule=chosen,
        unscheduled=unscheduled,
        solver_status=solver.StatusName(status),
        objective_value=float(solver.ObjectiveValue()),
        iteration_log_count=callback.log_count,
        runtime_ms=runtime_ms,
        objective_breakdown=objective_breakdown,
        objective_breakdown_raw=raw_breakdown,
        active_weight_profile=active_profile,
        switch_reason=switch_reason,
    )
