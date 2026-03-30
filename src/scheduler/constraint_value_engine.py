"""统一约束值计算引擎（第一阶段）。"""

from __future__ import annotations

from .models import Task
from .objective_engine import normalize_to_scale, score_candidate
from .thermal_model import SemiEmpiricalThermalModelV1, ThermalCoefficients


def _build_model(thermal_cfg: dict) -> SemiEmpiricalThermalModelV1:
    coeff = thermal_cfg.get("coefficients", {})
    return SemiEmpiricalThermalModelV1(
        ThermalCoefficients(
            a_p=float(coeff.get("a_p", 0.0)),
            a_c=float(coeff.get("a_c", 0.0)),
            lambda_concurrency=float(coeff.get("lambda_concurrency", 0.0)),
            k_cool=float(coeff.get("k_cool", 0.0)),
        ),
        env_temperature=float(thermal_cfg.get("env_temperature", 20.0)),
    )


def simulate_task_trace_with_thermal_model(
    *,
    task: Task,
    initial_temperature: float,
    capacities: dict[str, int],
    thermal_cfg: dict,
) -> list[float]:
    model = _build_model(thermal_cfg)
    dt = float(thermal_cfg.get("thermal_time_step", 1.0))
    state = {"temperature": float(initial_temperature)}
    trace: list[float] = []

    for _ in range(int(task.duration)):
        state = model.update(
            state,
            {
                "power_total": float(task.power),
                "cpu_used": float(task.cpu),
                "gpu_used": float(task.gpu),
                "cpu_capacity": max(float(capacities.get("cpu", 1)), 1.0),
                "gpu_capacity": max(float(capacities.get("gpu", 1)), 1.0),
            },
            dt,
        )
        trace.append(float(state["temperature"]))

    return trace


def replay_idle_thermal_state(
    *,
    model: SemiEmpiricalThermalModelV1,
    state: dict[str, float],
    idle_duration: int,
    dt: float,
) -> dict[str, float]:
    cursor = dict(state)
    for _ in range(max(int(idle_duration), 0)):
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


def _candidate_objective_raw(
    *,
    task: Task,
    temperatures: list[float],
    warning_threshold: float,
    danger_threshold: float,
    power_capacity: int,
    transition_time: int,
) -> dict[str, float]:
    peak_temp = max(temperatures) if temperatures else warning_threshold
    denom = max(danger_threshold - warning_threshold, 1e-6)
    thermal_risk = max(0.0, peak_temp - warning_threshold) / denom
    thermal_safety = max(0.0, 1.0 - min(1.0, thermal_risk))
    power_smoothing = max(0.0, 1.0 - float(task.power) / max(float(power_capacity), 1.0))

    return {
        "task_value": float(task.value),
        "completion": 1.0,
        "association": 1.0 if task.predecessors else 0.5,
        "thermal_safety": thermal_safety,
        "power_smoothing": power_smoothing,
        "resource_utilization": min(1.0, float(task.cpu + task.gpu) / 4.0),
        "smoothness": max(0.0, 1.0 - float(transition_time) / 180.0),
    }


def score_task_candidate(
    *,
    task: Task,
    state_at_candidate: dict[str, float],
    capacities: dict[str, int],
    thermal_cfg: dict,
    objective_ranges: dict[str, tuple[float, float]],
    weights: dict[str, float],
    transition_time: int,
    temperatures: list[float] | None = None,
) -> dict[str, float | dict[str, float]]:
    trace = temperatures
    if trace is None:
        trace = simulate_task_trace_with_thermal_model(
            task=task,
            initial_temperature=float(state_at_candidate.get("temperature", thermal_cfg.get("initial_temperature", 25.0))),
            capacities=capacities,
            thermal_cfg=thermal_cfg,
        )

    raw = _candidate_objective_raw(
        task=task,
        temperatures=trace,
        warning_threshold=float(thermal_cfg.get("warning_threshold", 0.0)),
        danger_threshold=float(thermal_cfg.get("danger_threshold", 100.0)),
        power_capacity=int(capacities.get("power", 1)),
        transition_time=int(transition_time),
    )
    detail = score_candidate(
        objective_raw=raw,
        objective_ranges=objective_ranges,
        weights=weights,
    )
    return {
        "total_score": float(detail.total_score),
        "objective_breakdown": dict(detail.weighted),
        "objective_raw": raw,
    }


def _scale_metric(
    *,
    metric: str,
    raw: float,
    objective_ranges: dict[str, tuple[float, float]],
    component_scale: int,
) -> int:
    low, high = objective_ranges.get(metric, (0.0, 1.0))
    scaled = normalize_to_scale(
        raw=float(raw),
        lower=float(low),
        upper=float(high),
        target_min=0.0,
        target_max=float(component_scale),
    )
    return int(round(scaled))


def build_solver_coefficients(
    *,
    tasks: list[Task],
    capacities: dict[str, int],
    thermal_cfg: dict,
    key_task_bonus: float,
    objective_ranges: dict[str, tuple[float, float]],
    component_scale: int,
) -> dict[str, int | dict[str, int]]:
    if not tasks:
        return {
            "task_value": {},
            "completion_step": 1,
            "association": {},
            "thermal_proxy": {},
            "power_proxy": {},
            "utilization": {},
            "smoothness_scale": 1,
        }

    max_pred_count = max(max((len(task.predecessors) for task in tasks), default=0), 1)
    max_thermal_load = max((float(task.thermal_load) for task in tasks), default=1.0)
    power_capacity = max(float(capacities.get("power", 1)), 1.0)
    cpu_capacity = max(float(capacities.get("cpu", 1)), 1.0)
    gpu_capacity = max(float(capacities.get("gpu", 1)), 1.0)
    safe_power_ratio = float(thermal_cfg.get("power_safe_ratio", 0.7))
    safe_power_limit = max(0.0, min(power_capacity, power_capacity * safe_power_ratio))

    task_value = {
        task.task_id: _scale_metric(
            metric="task_value",
            raw=float(task.value) + (float(key_task_bonus) if task.is_key_task else 0.0),
            objective_ranges=objective_ranges,
            component_scale=component_scale,
        )
        for task in tasks
    }
    association = {
        task.task_id: _scale_metric(
            metric="association",
            raw=float(len(task.predecessors)) / float(max_pred_count),
            objective_ranges=objective_ranges,
            component_scale=component_scale,
        )
        for task in tasks
    }
    thermal_proxy = {
        task.task_id: _scale_metric(
            metric="thermal_safety",
            raw=min(1.0, float(task.thermal_load) / max(max_thermal_load, 1e-6)),
            objective_ranges=objective_ranges,
            component_scale=component_scale,
        )
        for task in tasks
    }
    power_proxy = {
        task.task_id: _scale_metric(
            metric="power_smoothing",
            raw=max(0.0, float(task.power) - safe_power_limit) / power_capacity,
            objective_ranges=objective_ranges,
            component_scale=component_scale,
        )
        for task in tasks
    }
    utilization = {
        task.task_id: _scale_metric(
            metric="resource_utilization",
            raw=min(1.0, float(task.cpu) / cpu_capacity + float(task.gpu) / gpu_capacity),
            objective_ranges=objective_ranges,
            component_scale=component_scale,
        )
        for task in tasks
    }

    completion_step = _scale_metric(
        metric="completion",
        raw=1.0 / float(max(len(tasks), 1)),
        objective_ranges=objective_ranges,
        component_scale=component_scale,
    )

    return {
        "task_value": task_value,
        "completion_step": completion_step,
        "association": association,
        "thermal_proxy": thermal_proxy,
        "power_proxy": power_proxy,
        "utilization": utilization,
        "smoothness_scale": max(1, int(round(component_scale / 180.0))),
    }
