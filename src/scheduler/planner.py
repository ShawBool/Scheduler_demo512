"""基线规划求解器（CP-SAT）。"""

from __future__ import annotations

from typing import Any

from ortools.sat.python import cp_model

from .models import ScheduleItem, ScheduleResult, Task

def _angle_delta(a: float, b: float) -> float:
    diff = abs(a - b)
    return min(diff, 360.0 - diff)


def plan_baseline(tasks: list[Task], config: dict[str, Any]) -> ScheduleResult:
    model = cp_model.CpModel()
    runtime = config["runtime"]
    constraints = config["constraints"]
    weights = config["objective_weights"]

    time_step = max(1, int(runtime.get("time_step", 1)))
    horizon = int(runtime["time_horizon"])
    attitude_time_per_degree = float(constraints.get("attitude_time_per_degree", 0.0))
    payload_type_capacity: dict[str, int] = {
        str(k): int(v) for k, v in constraints.get("payload_type_capacity", {}).items()
    }
    critical_payload_ids = set(constraints.get("critical_payload_ids", []))

    n = len(tasks)
    task_index = {t.task_id: i for i, t in enumerate(tasks)}

    starts: list[cp_model.IntVar] = []
    ends: list[cp_model.IntVar] = []
    selected: list[cp_model.BoolVar] = []
    intervals: list[cp_model.IntervalVar] = []
    for idx, task in enumerate(tasks):
        dur_slot = max(1, (task.duration + time_step - 1) // time_step)
        earliest_slot = max(0, task.earliest_start // time_step)
        latest_end_slot = min(horizon // time_step, task.latest_end // time_step)
        latest_start_slot = max(earliest_slot, latest_end_slot - dur_slot)

        x = model.new_bool_var(f"sel_{idx}")
        if earliest_slot + dur_slot > latest_end_slot:
            s = model.new_int_var(0, 0, f"start_{idx}")
            e = model.new_int_var(0, 0, f"end_{idx}")
            model.add(x == 0)
            interval = model.new_optional_interval_var(s, 1, e, x, f"iv_{idx}")
        else:
            s = model.new_int_var(earliest_slot, latest_start_slot, f"start_{idx}")
            e = model.new_int_var(earliest_slot + dur_slot, latest_end_slot, f"end_{idx}")
            interval = model.new_optional_interval_var(s, dur_slot, e, x, f"iv_{idx}")
            model.add(e == s + dur_slot)

        if task.is_key_task:
            model.add(x == 1)

        starts.append(s)
        ends.append(e)
        selected.append(x)
        intervals.append(interval)

    for succ_idx, succ_task in enumerate(tasks):
        for pred_id in succ_task.predecessors:
            if pred_id not in task_index:
                model.add(selected[succ_idx] == 0)
                continue
            pred_idx = task_index[pred_id]
            model.add(selected[succ_idx] <= selected[pred_idx])
            model.add(starts[succ_idx] >= ends[pred_idx]).only_enforce_if(
                [selected[succ_idx], selected[pred_idx]]
            )

    for i in range(n):
        for j in range(i + 1, n):
            angle = _angle_delta(tasks[i].attitude_angle_deg, tasks[j].attitude_angle_deg)
            switch_gap = int(round(angle * attitude_time_per_degree))
            switch_slot = max(0, (switch_gap + time_step - 1) // time_step)
            if switch_slot == 0:
                continue
            both = model.new_bool_var(f"both_{i}_{j}")
            model.add_bool_and([selected[i], selected[j]]).only_enforce_if(both)
            model.add_bool_or([selected[i].Not(), selected[j].Not(), both])
            i_before_j = model.new_bool_var(f"i_before_j_{i}_{j}")
            j_before_i = model.new_bool_var(f"j_before_i_{i}_{j}")
            model.add_bool_or([i_before_j, j_before_i]).only_enforce_if(both)
            model.add(starts[j] >= ends[i] + switch_slot).only_enforce_if([both, i_before_j])
            model.add(starts[i] >= ends[j] + switch_slot).only_enforce_if([both, j_before_i])

    resource_specs = [
        ("cpu", "cpu_capacity"),
        ("gpu", "gpu_capacity"),
        ("memory", "memory_capacity"),
        ("storage", "storage_capacity"),
        ("bus", "bus_capacity"),
        ("concurrency_cores", "max_concurrency_cores"),
        ("power", "power_capacity"),
        ("thermal_load", "thermal_capacity"),
    ]
    for task_attr, cap_key in resource_specs:
        cap = int(constraints.get(cap_key, 0))
        demands = [int(getattr(t, task_attr)) for t in tasks]
        model.add_cumulative(intervals, demands, cap)

    for idx, task in enumerate(tasks):
        if payload_type_capacity:
            for payload_type in task.payload_type_requirements:
                if payload_type not in payload_type_capacity or payload_type_capacity[payload_type] <= 0:
                    model.add(selected[idx] == 0)
                    break
        if critical_payload_ids and any(payload_id not in critical_payload_ids for payload_id in task.payload_id_requirements):
            model.add(selected[idx] == 0)

    for payload_type, cap in payload_type_capacity.items():
        demands = [1 if payload_type in t.payload_type_requirements else 0 for t in tasks]
        if any(demands):
            model.add_cumulative(intervals, demands, cap)

    task_value_weight = int(weights.get("task_value", 1))
    late_penalty_weight = int(weights.get("lateness_penalty", 0))
    objective_terms: list[cp_model.LinearExpr] = []
    for idx, task in enumerate(tasks):
        earliest_slot = max(0, task.earliest_start // time_step)
        objective_terms.append(selected[idx] * int(task.value) * task_value_weight)
        if late_penalty_weight > 0:
            lateness = model.new_int_var(0, horizon // time_step, f"late_{idx}")
            model.add(lateness == starts[idx] - earliest_slot).only_enforce_if(selected[idx])
            model.add(lateness == 0).only_enforce_if(selected[idx].Not())
            objective_terms.append(-lateness * late_penalty_weight)

    model.maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(runtime.get("solver_timeout_sec", 10))
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ScheduleResult(
            scheduled_items=[],
            unscheduled_tasks=tasks,
            objective_value=0.0,
            constraint_stats={"scheduled_count": 0, "unscheduled_count": len(tasks), "solver_status": int(status)},
        )

    scheduled_items: list[ScheduleItem] = []
    unscheduled_tasks: list[Task] = []
    for idx, task in enumerate(tasks):
        if solver.value(selected[idx]) == 1:
            start = solver.value(starts[idx]) * time_step
            end = solver.value(ends[idx]) * time_step
            scheduled_items.append(
                ScheduleItem(task_id=task.task_id, start=start, end=end, attitude_angle_deg=task.attitude_angle_deg, value=task.value)
            )
        else:
            unscheduled_tasks.append(task)

    scheduled_items.sort(key=lambda x: (x.start, x.end, x.task_id))
    constraint_stats = {
        "scheduled_count": len(scheduled_items),
        "unscheduled_count": len(unscheduled_tasks),
        "solver_status": "optimal" if status == cp_model.OPTIMAL else "feasible",
        "resource_overflow_count": 0,
    }

    rolling_size = int(constraints.get("rolling_window_size", max(1, horizon // 4)))
    rolling_segments: list[dict[str, int]] = []
    seg_start = 0
    while seg_start < horizon:
        seg_end = min(horizon, seg_start + rolling_size)
        rolling_segments.append({"start": seg_start, "end": seg_end})
        seg_start = seg_end

    return ScheduleResult(
        scheduled_items=scheduled_items,
        unscheduled_tasks=unscheduled_tasks,
        objective_value=float(solver.objective_value),
        constraint_stats=constraint_stats,
        rolling_segments=rolling_segments,
    )

