"""CP-SAT 限时改进器。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ortools.sat.python import cp_model

from .heuristic_scheduler import HeuristicResult
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

    # 关键任务仍是“尽量必排”，通过目标奖励提升优先级，而非强制必须选中。
    objective_terms: list[cp_model.LinearExpr] = []
    for task in problem.tasks:
        weight = task.value + (key_task_bonus if task.is_key_task else 0.0)
        objective_terms.append(int(weight * 100) * selected[task.task_id])

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
    runtime_ms = int((time.perf_counter() - started) * 1000)
    return ImproveResult(
        schedule=chosen,
        unscheduled=unscheduled,
        solver_status=solver.StatusName(status),
        objective_value=float(solver.ObjectiveValue()),
        iteration_log_count=callback.log_count,
        runtime_ms=runtime_ms,
    )
