"""基线规划求解器（CP-SAT）。"""

from __future__ import annotations

from typing import Any

from ortools.sat.python import cp_model

from .models import DangerRule, LinkWindow, ScheduleItem, ScheduleResult, Task


def _to_windows(raw_windows: list[dict[str, Any]]) -> list[LinkWindow]:
    return [
        LinkWindow(
            kind=w["kind"],
            start=int(w["start"]),
            end=int(w["end"]),
            bandwidth=int(w.get("bandwidth", 1)),
        )
        for w in raw_windows
    ]


def _to_danger_rules(raw_rules: list[dict[str, Any]]) -> list[DangerRule]:
    return [
        DangerRule(
            rule_id=r["rule_id"],
            min_power=int(r["min_power"]),
            min_thermal=int(r["min_thermal"]),
            forbidden_attitudes=list(r["forbidden_attitudes"]),
            description=r.get("description", ""),
        )
        for r in raw_rules
    ]


def plan_baseline(tasks: list[Task], config: dict[str, Any]) -> ScheduleResult:
    model = cp_model.CpModel()
    runtime = config["runtime"]
    constraints = config["constraints"]
    weights = config["objective_weights"]

    time_step = max(1, int(runtime.get("time_step", 1)))
    horizon = int(runtime["time_horizon"])

    windows = _to_windows(constraints.get("link_windows", []))
    danger_rules = _to_danger_rules(constraints.get("danger_rules", []))
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

        x = model.NewBoolVar(f"sel_{idx}")
        if earliest_slot + dur_slot > latest_end_slot:
            # 时间窗无法容纳该任务时，显式标记为不可选，避免构建无效变量域。
            s = model.NewIntVar(0, 0, f"start_{idx}")
            e = model.NewIntVar(0, 0, f"end_{idx}")
            model.Add(x == 0)
            interval = model.NewOptionalIntervalVar(s, 1, e, x, f"iv_{idx}")
        else:
            s = model.NewIntVar(earliest_slot, latest_start_slot, f"start_{idx}")
            e = model.NewIntVar(earliest_slot + dur_slot, latest_end_slot, f"end_{idx}")
            interval = model.NewOptionalIntervalVar(s, dur_slot, e, x, f"iv_{idx}")
            model.Add(e == s + dur_slot)

        if task.is_key_task:
            model.Add(x == 1)

        starts.append(s)
        ends.append(e)
        selected.append(x)
        intervals.append(interval)

    # 依赖约束：后继必须依赖前驱且时间不早于前驱完成
    for succ_idx, succ_task in enumerate(tasks):
        for pred_id in succ_task.predecessors:
            if pred_id not in task_index:
                model.Add(selected[succ_idx] == 0)
                continue
            pred_idx = task_index[pred_id]
            model.Add(selected[succ_idx] <= selected[pred_idx])
            model.Add(starts[succ_idx] >= ends[pred_idx]).OnlyEnforceIf(
                [selected[succ_idx], selected[pred_idx]]
            )

    # 姿态切换：不同姿态任务若都被调度，必须有先后并留切换时间
    switch_gap = int(constraints.get("attitude_switch_time", 0))
    switch_slot = max(0, (switch_gap + time_step - 1) // time_step)
    for i in range(n):
        for j in range(i + 1, n):
            if tasks[i].attitude_mode == tasks[j].attitude_mode:
                continue
            both = model.NewBoolVar(f"both_{i}_{j}")
            model.AddBoolAnd([selected[i], selected[j]]).OnlyEnforceIf(both)
            model.AddBoolOr([selected[i].Not(), selected[j].Not(), both])

            i_before_j = model.NewBoolVar(f"i_before_j_{i}_{j}")
            j_before_i = model.NewBoolVar(f"j_before_i_{i}_{j}")
            model.AddBoolOr([i_before_j, j_before_i]).OnlyEnforceIf(both)
            model.Add(starts[j] >= ends[i] + switch_slot).OnlyEnforceIf([both, i_before_j])
            model.Add(starts[i] >= ends[j] + switch_slot).OnlyEnforceIf([both, j_before_i])

    # 资源约束（并发累计）
    resource_specs = [
        ("cpu", "cpu_capacity"),
        ("gpu", "gpu_capacity"),
        ("memory", "memory_capacity"),
        ("storage", "storage_capacity"),
        ("bus", "bus_capacity"),
        ("container_slots", "container_capacity"),
        ("power", "power_capacity"),
        ("thermal_load", "thermal_capacity"),
    ]
    for task_attr, cap_key in resource_specs:
        cap = int(constraints.get(cap_key, 0))
        demands = [int(getattr(t, task_attr)) for t in tasks]
        model.AddCumulative(intervals, demands, cap)

    # 载荷绑定约束：任务要求的载荷类型/载荷ID必须可用
    for idx, task in enumerate(tasks):
        if payload_type_capacity:
            for payload_type in task.payload_type_requirements:
                if payload_type not in payload_type_capacity or payload_type_capacity[payload_type] <= 0:
                    model.Add(selected[idx] == 0)
                    break
        if critical_payload_ids and any(payload_id not in critical_payload_ids for payload_id in task.payload_id_requirements):
            model.Add(selected[idx] == 0)

    # 载荷类型并发容量约束
    for payload_type, cap in payload_type_capacity.items():
        demands = [1 if payload_type in t.payload_type_requirements else 0 for t in tasks]
        if any(demands):
            model.AddCumulative(intervals, demands, cap)

    # 通信窗口约束
    for idx, task in enumerate(tasks):
        if not task.comm_kind:
            continue
        kind_windows = [w for w in windows if w.kind == task.comm_kind]
        if not kind_windows:
            model.Add(selected[idx] == 0)
            continue
        w_bools = [model.NewBoolVar(f"w_{idx}_{k}") for k in range(len(kind_windows))]
        model.Add(sum(w_bools) == selected[idx])
        for wb, w in zip(w_bools, kind_windows):
            ws = w.start // time_step
            we = w.end // time_step
            model.Add(starts[idx] >= ws).OnlyEnforceIf(wb)
            model.Add(ends[idx] <= we).OnlyEnforceIf(wb)

    # 通信带宽预算约束：同类型通信并发需求不得超过窗口带宽
    comm_kinds = {w.kind for w in windows}
    for kind in comm_kinds:
        kind_tasks = [idx for idx, t in enumerate(tasks) if t.comm_kind == kind]
        if not kind_tasks:
            continue
        min_slot = 0
        max_slot = max(1, horizon // time_step)
        active_per_slot: dict[int, list[cp_model.BoolVar]] = {}
        for slot in range(min_slot, max_slot):
            active_bools = active_per_slot.setdefault(slot, [])
            bandwidth_caps: list[int] = []
            for w in windows:
                if w.kind != kind:
                    continue
                ws = w.start // time_step
                we = w.end // time_step
                if ws <= slot < we:
                    bandwidth_caps.append(max(0, int(w.bandwidth)))
            if not bandwidth_caps:
                for idx in kind_tasks:
                    before_or_at = model.NewBoolVar(f"comm_{kind}_{idx}_before_{slot}")
                    after = model.NewBoolVar(f"comm_{kind}_{idx}_after_{slot}")
                    is_active = model.NewBoolVar(f"comm_{kind}_{idx}_at_{slot}")
                    model.Add(starts[idx] <= slot).OnlyEnforceIf(before_or_at)
                    model.Add(starts[idx] > slot).OnlyEnforceIf(before_or_at.Not())
                    model.Add(ends[idx] > slot).OnlyEnforceIf(after)
                    model.Add(ends[idx] <= slot).OnlyEnforceIf(after.Not())
                    model.AddBoolAnd([selected[idx], before_or_at, after]).OnlyEnforceIf(is_active)
                    model.AddBoolOr([selected[idx].Not(), before_or_at.Not(), after.Not(), is_active])
                    active_bools.append(is_active)
                if active_bools:
                    model.Add(sum(active_bools) == 0)
                continue
            cap = max(bandwidth_caps)
            for idx in kind_tasks:
                is_active = model.NewBoolVar(f"comm_{kind}_{idx}_at_{slot}")
                before_or_at = model.NewBoolVar(f"comm_{kind}_{idx}_before_{slot}")
                after = model.NewBoolVar(f"comm_{kind}_{idx}_after_{slot}")
                model.Add(starts[idx] <= slot).OnlyEnforceIf(before_or_at)
                model.Add(starts[idx] > slot).OnlyEnforceIf(before_or_at.Not())
                model.Add(ends[idx] > slot).OnlyEnforceIf(after)
                model.Add(ends[idx] <= slot).OnlyEnforceIf(after.Not())
                model.AddBoolAnd([selected[idx], before_or_at, after]).OnlyEnforceIf(is_active)
                model.AddBoolOr([selected[idx].Not(), before_or_at.Not(), after.Not(), is_active])
                active_bools.append(is_active)
            model.Add(sum(active_bools) <= cap)

    # 危险组合约束（任务级）
    danger_blocked_task_ids: set[str] = set()
    for idx, task in enumerate(tasks):
        for rule in danger_rules:
            if (
                task.power >= rule.min_power
                and task.thermal_load >= rule.min_thermal
                and task.attitude_mode in rule.forbidden_attitudes
            ):
                model.Add(selected[idx] == 0)
                danger_blocked_task_ids.add(task.task_id)

    # 目标函数：收益最大化 + 轻微抑制迟启动
    task_value_weight = int(weights.get("task_value", 1))
    late_penalty_weight = int(weights.get("lateness_penalty", 0))

    objective_terms: list[cp_model.LinearExpr] = []
    for idx, task in enumerate(tasks):
        earliest_slot = max(0, task.earliest_start // time_step)
        objective_terms.append(selected[idx] * int(task.value) * task_value_weight)
        if late_penalty_weight > 0:
            lateness = model.NewIntVar(0, horizon // time_step, f"late_{idx}")
            model.Add(lateness == starts[idx] - earliest_slot).OnlyEnforceIf(selected[idx])
            model.Add(lateness == 0).OnlyEnforceIf(selected[idx].Not())
            objective_terms.append(-lateness * late_penalty_weight)

    objective_expr = sum(objective_terms)
    model.Maximize(objective_expr)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(runtime.get("solver_timeout_sec", 10))
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ScheduleResult(
            scheduled_items=[],
            unscheduled_tasks=tasks,
            objective_value=0.0,
            constraint_stats={
                "scheduled_count": 0,
                "unscheduled_count": len(tasks),
                "solver_status": int(status),
            },
        )

    scheduled_items: list[ScheduleItem] = []
    unscheduled_tasks: list[Task] = []
    for idx, task in enumerate(tasks):
        if solver.Value(selected[idx]) == 1:
            start = solver.Value(starts[idx]) * time_step
            end = solver.Value(ends[idx]) * time_step
            scheduled_items.append(
                ScheduleItem(
                    task_id=task.task_id,
                    start=start,
                    end=end,
                    attitude_mode=task.attitude_mode,
                    comm_kind=task.comm_kind,
                    value=task.value,
                )
            )
        else:
            unscheduled_tasks.append(task)

    scheduled_items.sort(key=lambda x: (x.start, x.end, x.task_id))
    scheduled_ids = {item.task_id for item in scheduled_items}
    objective_value = float(solver.ObjectiveValue())
    constraint_stats = {
        "scheduled_count": len(scheduled_items),
        "unscheduled_count": len(unscheduled_tasks),
        "solver_status": "optimal" if status == cp_model.OPTIMAL else "feasible",
        "resource_overflow_count": 0,
        "danger_rule_block_count": sum(1 for t in unscheduled_tasks if t.task_id in danger_blocked_task_ids),
        "link_window_violation_count": sum(
            1 for t in unscheduled_tasks if t.comm_kind and any(w.kind == t.comm_kind for w in windows)
        ),
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
        objective_value=objective_value,
        constraint_stats=constraint_stats,
        rolling_segments=rolling_segments,
    )
