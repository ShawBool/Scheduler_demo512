"""启发式初解：快速构造可行解并给出未排原因。"""

from __future__ import annotations

from dataclasses import dataclass

from . import constraint_value_engine
from .models import ScheduleItem, Task, UnscheduledItem
from .objective_engine import DEFAULT_OBJECTIVE_KEYS, build_scale_config
from .problem_builder import ProblemInstance
from .thermal_model import SemiEmpiricalThermalModelV1, ThermalCoefficients


@dataclass(slots=True)
class HeuristicResult:
    schedule: list[ScheduleItem]
    unscheduled: list[UnscheduledItem]
    solver_metadata: dict[str, str | float] | None = None


def _task_priority(task: Task) -> tuple[int, float, int]:
    """排序规则：关键任务优先 -> 单位时长收益高优先 -> 任务ID稳定排序。"""
    density = task.value / max(task.duration, 1)
    return (0 if task.is_key_task else 1, -density, hash(task.task_id))


def _fits_time_window(task: Task, start: int) -> bool:
    end = start + task.duration
    if task.visibility_window is None:
        return end <= 10**9
    return start >= task.visibility_window.start and end <= task.visibility_window.end


def _resources_ok(task: Task, usage: dict[int, dict[str, int]], capacities: dict[str, int], start: int) -> bool:
    """逐时间片检查资源是否越界。"""
    for t in range(start, start + task.duration):
        point = usage.setdefault(t, {"cpu": 0, "gpu": 0, "memory": 0, "power": 0})
        if point["cpu"] + task.cpu > capacities["cpu"]:
            return False
        if point["gpu"] + task.gpu > capacities["gpu"]:
            return False
        if point["memory"] + task.memory > capacities["memory"]:
            return False
        if point["power"] + task.power > capacities["power"]:
            return False
    return True


def _apply_usage(task: Task, usage: dict[int, dict[str, int]], start: int) -> None:
    for t in range(start, start + task.duration):
        point = usage.setdefault(t, {"cpu": 0, "gpu": 0, "memory": 0, "power": 0})
        point["cpu"] += task.cpu
        point["gpu"] += task.gpu
        point["memory"] += task.memory
        point["power"] += task.power


def _transition_time(current_angle: float | None, target_angle: float | None, per_degree: float) -> int:
    if current_angle is None or target_angle is None:
        return 0
    delta = abs(float(current_angle) - float(target_angle))
    delta = min(delta, 360.0 - delta)
    return int(round(delta * per_degree))


def _simulate_task_thermal_trace(
    *,
    model: SemiEmpiricalThermalModelV1,
    task: Task,
    state: dict[str, float],
    capacities: dict[str, int],
    dt: float,
) -> tuple[list[float], dict[str, float]]:
    cursor = dict(state)
    temperatures: list[float] = []
    cpu_capacity = max(float(capacities.get("cpu", 1)), 1.0)
    gpu_capacity = max(float(capacities.get("gpu", 1)), 1.0)
    for _ in range(task.duration):
        cursor = model.update(
            cursor,
            {
                "power_total": float(task.power),
                "cpu_used": float(task.cpu),
                "gpu_used": float(task.gpu),
                "cpu_capacity": cpu_capacity,
                "gpu_capacity": gpu_capacity,
            },
            dt,
        )
        temperatures.append(float(cursor.get("temperature", 0.0)))
    return temperatures, cursor


def _simulate_idle_thermal(
    *,
    model: SemiEmpiricalThermalModelV1,
    state: dict[str, float],
    idle_duration: int,
    dt: float,
) -> dict[str, float]:
    cursor = dict(state)
    for _ in range(max(idle_duration, 0)):
        cursor = model.update(
            cursor,
            {
                "power_total": 0.0,
                "cpu_used": 0.0,
                "gpu_used": 0.0,
                "cpu_capacity": 1.0,
                "gpu_capacity": 1.0,
            },
            dt,
        )
    return cursor


def _default_profiles() -> dict[str, dict[str, float]]:
    return {
        "base": {
            "task_value": 0.40,
            "completion": 0.15,
            "association": 0.10,
            "thermal_safety": 0.15,
            "power_smoothing": 0.10,
            "resource_utilization": 0.05,
            "smoothness": 0.05,
        },
        "thermal": {
            "task_value": 0.25,
            "completion": 0.10,
            "association": 0.05,
            "thermal_safety": 0.35,
            "power_smoothing": 0.10,
            "resource_utilization": 0.10,
            "smoothness": 0.05,
        },
    }


def build_initial_schedule(
    problem: ProblemInstance,
    seed: int = 666,
    *,
    initial_attitude_angle_deg: float = 0.0,
) -> HeuristicResult:
    """构建启发式初解。

    设计要点：
    1. 采用固定排序 + 固定扫描策略，确保同seed下可复现。
    2. 先满足前驱，再尝试最早可行起点。
    3. 若无法排入，输出结构化原因。
    """
    del seed  # 当前启发式完全确定性，保留参数是为了与后续扩展兼容。

    usage: dict[int, dict[str, int]] = {}
    scheduled: list[ScheduleItem] = []
    unscheduled: list[UnscheduledItem] = []
    finished_at: dict[str, int] = {}
    current_time = 0
    current_attitude: float | None = float(initial_attitude_angle_deg)

    thermal_cfg = problem.thermal_config or {}
    thermal_coeff = thermal_cfg.get("coefficients", {})
    thermal_enabled = bool(thermal_cfg)
    thermal_model: SemiEmpiricalThermalModelV1 | None = None
    warning_threshold = float(thermal_cfg.get("warning_threshold", 0.0))
    danger_threshold = float(thermal_cfg.get("danger_threshold", 10**9))
    max_warning_duration = float(thermal_cfg.get("max_warning_duration", 10**9))
    thermal_time_step = float(thermal_cfg.get("thermal_time_step", 1.0))
    current_thermal_state: dict[str, float] = {
        "temperature": float(thermal_cfg.get("initial_temperature", thermal_cfg.get("initial_temperature_fallback", 25.0)))
    }
    if thermal_enabled:
        thermal_model = SemiEmpiricalThermalModelV1(
            ThermalCoefficients(
                a_p=float(thermal_coeff.get("a_p", 0.0)),
                a_c=float(thermal_coeff.get("a_c", 0.0)),
                lambda_concurrency=float(thermal_coeff.get("lambda_concurrency", 0.0)),
                k_cool=float(thermal_coeff.get("k_cool", 0.0)),
            ),
            env_temperature=float(thermal_cfg.get("env_temperature", 20.0)),
        )

    objective_profiles = thermal_cfg.get("objective_profiles", _default_profiles())
    base_weights = objective_profiles.get("base", _default_profiles()["base"])

    objective_ranges = build_scale_config(thermal_cfg.get("objective_scaling", {})).ranges

    # 关键点：严格保持拓扑顺序，避免“子任务先于前驱”导致关键任务被错误阻塞。
    # 在当前一期中，优先保证依赖可行性，后续再演进为“就绪队列 + 多目标排序”。
    ordered_ids = list(problem.topological_tasks)
    root_ids = [tid for tid in ordered_ids if not problem.task_map[tid].predecessors]
    if root_ids and thermal_enabled and thermal_model is not None:
        ranked: list[tuple[float, str]] = []
        for tid in root_ids:
            task = problem.task_map[tid]
            temps, _ = _simulate_task_thermal_trace(
                model=thermal_model,
                task=task,
                state=current_thermal_state,
                capacities=problem.capacities,
                dt=thermal_time_step,
            )
            transition = _transition_time(current_attitude, task.attitude_angle_deg, problem.attitude_time_per_degree)
            score_detail = constraint_value_engine.score_task_candidate(
                task=task,
                state_at_candidate=current_thermal_state,
                capacities=problem.capacities,
                thermal_cfg=problem.thermal_config,
                objective_ranges=objective_ranges,
                weights=base_weights,
                transition_time=transition,
                temperatures=temps,
            )
            ranked.append((float(score_detail["total_score"]), tid))
        root_sorted = [tid for _, tid in sorted(ranked, key=lambda x: (-x[0], x[1]))]
        ordered_ids = root_sorted + [tid for tid in ordered_ids if tid not in set(root_ids)]

    for task_id in ordered_ids:
        task = problem.task_map[task_id]

        # 若前驱未完成，则当前任务无法排入。
        missing_preds = [pred for pred in task.predecessors if pred not in finished_at]
        if missing_preds:
            unscheduled.append(
                UnscheduledItem(
                    task_id=task.task_id,
                    reason_code="dependency_blocked",
                    reason_detail=f"predecessors not scheduled: {', '.join(missing_preds)}",
                )
            )
            continue

        earliest = 0 if not task.predecessors else max(finished_at[pred] for pred in task.predecessors)
        transition_ready = _transition_time(current_attitude, task.attitude_angle_deg, problem.attitude_time_per_degree)
        if transition_ready > 0:
            earliest = max(earliest, current_time + transition_ready)
        latest_bound = problem.horizon - task.duration
        if task.visibility_window is not None:
            earliest = max(earliest, task.visibility_window.start)
            latest_bound = min(latest_bound, task.visibility_window.end - task.duration)

        if latest_bound < earliest:
            unscheduled.append(
                UnscheduledItem(
                    task_id=task.task_id,
                    reason_code="window_infeasible",
                    reason_detail="no feasible start in visibility/horizon window",
                )
            )
            continue

        picked_start: int | None = None
        picked_penalty: float | None = None
        thermal_candidate_state = current_thermal_state
        for candidate in range(earliest, latest_bound + 1):
            if not _fits_time_window(task, candidate):
                continue
            if _resources_ok(task, usage, problem.capacities, candidate):
                if thermal_enabled and thermal_model is not None:
                    state_at_candidate = constraint_value_engine.replay_idle_thermal_state(
                        model=thermal_model,
                        state=current_thermal_state,
                        idle_duration=candidate - current_time,
                        dt=thermal_time_step,
                    )
                    temperatures, end_state = _simulate_task_thermal_trace(
                        model=thermal_model,
                        task=task,
                        state=state_at_candidate,
                        capacities=problem.capacities,
                        dt=thermal_time_step,
                    )
                    warning_flags = [1 if warning_threshold <= temp < danger_threshold else 0 for temp in temperatures]
                    if any(temp >= danger_threshold for temp in temperatures):
                        continue
                    max_warning_steps = thermal_model.max_continuous_warning_steps(warning_flags)
                    if max_warning_steps * thermal_time_step > max_warning_duration:
                        continue
                    transition = _transition_time(current_attitude, task.attitude_angle_deg, problem.attitude_time_per_degree)
                    score_detail = constraint_value_engine.score_task_candidate(
                        task=task,
                        state_at_candidate=state_at_candidate,
                        capacities=problem.capacities,
                        thermal_cfg=problem.thermal_config,
                        objective_ranges=objective_ranges,
                        weights=base_weights,
                        transition_time=transition,
                        temperatures=temperatures,
                    )
                    score = float(score_detail["total_score"])
                    if picked_penalty is None:
                        picked_penalty = -1e9
                    better = picked_start is None or score > picked_penalty
                    same_penalty_earlier = picked_start is not None and picked_penalty is not None and score == picked_penalty and candidate < picked_start
                    if better or same_penalty_earlier:
                        thermal_candidate_state = end_state
                        picked_start = candidate
                        picked_penalty = score
                else:
                    picked_start = candidate
                    thermal_candidate_state = current_thermal_state
                    break

        if picked_start is None:
            unscheduled.append(
                UnscheduledItem(
                    task_id=task.task_id,
                    reason_code="resource_conflict",
                    reason_detail="no start time satisfies resource capacities",
                )
            )
            continue

        _apply_usage(task, usage, picked_start)
        end = picked_start + task.duration
        finished_at[task.task_id] = end
        current_time = max(current_time, end)
        if task.attitude_angle_deg is not None:
            current_attitude = float(task.attitude_angle_deg)
        current_thermal_state = thermal_candidate_state
        scheduled.append(
            ScheduleItem(
                task_id=task.task_id,
                start=picked_start,
                end=end,
                value=task.value,
                is_key_task=task.is_key_task,
                visibility_window_id=task.visibility_window.window_id if task.visibility_window else None,
            )
        )

    scheduled.sort(key=lambda x: (x.start, x.task_id))
    metadata = {
        "active_weight_profile": "base",
        "switch_reason": "static_profile",
        "objective_components": ",".join(DEFAULT_OBJECTIVE_KEYS),
    }
    return HeuristicResult(schedule=scheduled, unscheduled=unscheduled, solver_metadata=metadata)
