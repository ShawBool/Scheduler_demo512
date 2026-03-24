"""任务池仿真生成。"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import TypedDict

from .config import STRUCTURED_TASK_RATIO_MIN
from .models import Task, VisibilityWindow


class SimulationSnapshot(TypedDict):
    seed: int
    horizon: int
    tasks: list[Task]
    visibility_windows: list[VisibilityWindow]


def _rint(rng: random.Random, low: int, high: int) -> int:
    if high < low:
        return low
    return rng.randint(low, high)


def _angle_step(rng: random.Random, current: float, step_limit: float = 24.0) -> float:
    delta = rng.uniform(-step_limit, step_limit)
    nxt = (current + delta) % 360.0
    return float(nxt)


def _pick_payload_type(rng: random.Random, payload_types: list[str], index_hint: int) -> str:
    if payload_types:
        return payload_types[index_hint % len(payload_types)]
    return rng.choice(["camera", "radar", "relay"])


def _resource_profile(task_type: str) -> dict[str, tuple[int, int]]:
    # 任务类型资源画像：确保不同类型在资源占用上有明显差异。
    profiles: dict[str, dict[str, tuple[int, int]]] = {
        "camera": {
            "cpu": (1, 2),
            "gpu": (0, 1),
            "memory": (2, 5),
            "storage": (2, 6),
            "bus": (2, 4),
            "concurrency_cores": (1, 2),
            "power": (2, 5),
            "thermal_load": (2, 5),
            "duration": (3, 9),
            "value": (18, 45),
        },
        "radar": {
            "cpu": (2, 2),
            "gpu": (1, 2),
            "memory": (4, 8),
            "storage": (1, 3),
            "bus": (1, 3),
            "concurrency_cores": (2, 3),
            "power": (4, 8),
            "thermal_load": (4, 8),
            "duration": (5, 12),
            "value": (25, 60),
        },
        "relay": {
            "cpu": (1, 2),
            "gpu": (0, 1),
            "memory": (2, 4),
            "storage": (1, 2),
            "bus": (2, 5),
            "concurrency_cores": (1, 2),
            "power": (1, 4),
            "thermal_load": (1, 4),
            "duration": (2, 7),
            "value": (12, 35),
        },
        "compute": {
            "cpu": (1, 2),
            "gpu": (1, 2),
            "memory": (1, 3),
            "storage": (1, 2),
            "bus": (1, 2),
            "concurrency_cores": (1, 2),
            "power": (1, 3),
            "thermal_load": (1, 3),
            "duration": (2, 8),
            "value": (10, 28),
        },
    }
    return profiles.get(task_type, profiles["camera"])


def _clamp_range(low: int, high: int, cap: int, floor: int = 1) -> tuple[int, int]:
    upper = max(floor, min(high, cap))
    lower = max(floor, min(low, upper))
    return lower, upper


def _bounded_sample(rng: random.Random, low: int, high: int, cap: int, floor: int = 1) -> int:
    lo, hi = _clamp_range(low, high, cap, floor=floor)
    return _rint(rng, lo, hi)


def _build_visibility_window(window_id: str, start: int, end: int, horizon: int) -> VisibilityWindow | None:
    start_bound = max(0, min(start, horizon - 1))
    end_bound = max(start_bound + 1, min(end, horizon))
    if end_bound <= start_bound:
        return None
    return VisibilityWindow(window_id=window_id, start=start_bound, end=end_bound)


def _task_domain(task: Task, horizon: int) -> tuple[int, int]:
    if task.visibility_window is None:
        return 0, horizon
    return max(0, task.visibility_window.start), min(horizon, task.visibility_window.end)


def _can_precede(pred: Task, succ_window: VisibilityWindow | None, succ_duration: int, horizon: int) -> bool:
    pred_start, _ = _task_domain(pred, horizon)
    succ_end = horizon if succ_window is None else succ_window.end
    latest_succ_start = succ_end - succ_duration
    return pred_start + pred.duration <= latest_succ_start


def _generate_visibility_windows(
    sim: dict,
    horizon: int,
    rng: random.Random,
) -> list[VisibilityWindow]:
    count_min = int(sim.get("visibility_window_count_min", 8))
    count_max = int(sim.get("visibility_window_count_max", 20))
    win_count = _rint(rng, max(1, count_min), max(max(1, count_min), count_max))

    dur_min = int(sim.get("visibility_window_duration_min", 12))
    dur_max = int(sim.get("visibility_window_duration_max", 48))
    dur_min = max(1, dur_min)
    dur_max = max(dur_min, dur_max)

    windows: list[VisibilityWindow] = []
    for idx in range(win_count):
        w_dur = _rint(rng, dur_min, min(dur_max, max(dur_min, horizon)))
        w_dur = min(w_dur, horizon)
        w_start = _rint(rng, 0, max(0, horizon - w_dur))
        w_end = min(horizon, w_start + w_dur)
        window = _build_visibility_window(f"vw_{idx}", w_start, w_end, horizon)
        if window is not None:
            windows.append(window)

    return windows


def _apply_hard_key_task_cap(tasks: list[Task], candidate_task_ids: list[str], max_hard_key_tasks: int) -> None:
    if max_hard_key_tasks <= 0 or not tasks:
        return
    task_by_id = {task.task_id: task for task in tasks}
    hard_slots = 0
    for task_id in candidate_task_ids:
        task = task_by_id.get(task_id)
        if task is None:
            continue
        if hard_slots >= max_hard_key_tasks:
            break
        task.is_key_task = True
        hard_slots += 1


def generate_simulation_snapshot(config: dict, seed: int) -> SimulationSnapshot:
    rng = random.Random(seed)
    sim = config["simulation"]
    cst = config["constraints"]
    runtime = config["runtime"]

    task_count = rng.randint(sim["task_count_min"], sim["task_count_max"])
    time_horizon = runtime["time_horizon"]
    critical_payload_ids = cst.get("critical_payload_ids", [])
    payload_types = list(cst.get("payload_type_capacity", {}).keys()) or ["camera"]
    dependency_density = min(1.0, max(0.0, float(sim.get("dependency_density", 0.6))))
    max_predecessors = max(1, int(sim.get("max_predecessors", 2)))
    structured_ratio = float(sim.get("structured_task_ratio", 1.0 - float(sim.get("free_task_ratio", 0.35))))
    structured_ratio = min(1.0, max(STRUCTURED_TASK_RATIO_MIN, structured_ratio))
    structured_target_count = min(task_count, max(0, int(round(task_count * structured_ratio))))
    seq_count = 0
    if structured_target_count > 0:
        seq_count = min(4, max(1, structured_target_count // 12))
        if structured_target_count >= 24:
            seq_count = max(seq_count, 2)
        if structured_target_count >= 42:
            seq_count = max(seq_count, 3)
    key_task_probability = min(1.0, max(0.0, float(sim.get("key_task_probability", 0.06))))
    key_task_value_bonus = max(0, int(sim.get("key_task_value_bonus", 35)))
    max_hard_key_tasks = max(0, int(sim.get("max_hard_key_tasks", 1)))
    window_reuse_target = max(1.0, float(sim.get("window_reuse_target", 3.0)))
    window_share_task_min = max(1, int(window_reuse_target))
    window_share_task_max = max(window_share_task_min, int(round(window_reuse_target + 1)))

    tasks: list[Task] = []
    visibility_windows = _generate_visibility_windows(sim, time_horizon, rng)
    if not visibility_windows:
        visibility_windows = [VisibilityWindow(window_id="vw_fallback_0", start=0, end=max(1, time_horizon))]
    seq_count = min(seq_count, structured_target_count) if structured_target_count > 0 else 0
    if seq_count > 0:
        base_seq_size = structured_target_count // seq_count
        extra_tasks = structured_target_count % seq_count
        planned_seq_sizes = [base_seq_size + (1 if i < extra_tasks else 0) for i in range(seq_count)]
    else:
        planned_seq_sizes = []
    seq_total = sum(planned_seq_sizes)
    flex_count = max(0, task_count - seq_total)

    task_by_id: dict[str, Task] = {}
    seq_task_ids: list[str] = []
    key_task_candidates: list[str] = []
    window_use_counter: dict[str, int] = defaultdict(int)
    global_time_anchor = 0
    for seq_idx, seq_size in enumerate(planned_seq_sizes, start=1):
        seq_name = f"seq{seq_idx}"
        chain_count = max(2, min(4, max(2, seq_size // 3)))
        chain_ids: dict[int, list[str]] = defaultdict(list)
        seq_angle = rng.uniform(0.0, 359.9)
        seq_base = _rint(rng, 0, max(0, time_horizon // 3))
        global_time_anchor = _rint(rng, 0, max(0, time_horizon // 8))

        for idx in range(seq_size):
            chain = idx % chain_count
            task_type = _pick_payload_type(rng, payload_types, idx + seq_idx)
            profile = _resource_profile(task_type)
            candidate_windows = visibility_windows
            underused = [w for w in candidate_windows if window_use_counter[w.window_id] < window_share_task_min]
            reusable = [w for w in candidate_windows if window_use_counter[w.window_id] < window_share_task_max]
            if underused:
                window = rng.choice(underused)
            elif reusable:
                window = rng.choice(reusable)
            else:
                window = rng.choice(candidate_windows)

            window_span = max(1, window.end - window.start)
            duration = _bounded_sample(rng, *profile["duration"], cap=max(1, min(12, window_span)))
            duration = min(duration, window_span)

            predecessors: list[str] = []
            chain_pred = chain_ids[chain][-1] if chain_ids[chain] else None
            if chain_pred:
                pred_task = task_by_id[chain_pred]
                # 共享窗口依赖时，确保窗口内总时长可行。
                if pred_task.visibility_window is not None and pred_task.visibility_window.window_id == window.window_id:
                    if pred_task.duration + duration <= (window.end - window.start):
                        predecessors.append(chain_pred)
                elif _can_precede(pred_task, window, duration, time_horizon):
                    predecessors.append(chain_pred)
            if idx > 0 and rng.random() < dependency_density:
                other_candidates = [tid for c, tids in chain_ids.items() if c != chain for tid in tids]
                if other_candidates:
                    max_extra = min(max_predecessors - len(predecessors), len(other_candidates))
                    if max_extra > 0:
                        extra_pred_num = _rint(rng, 1, max_extra)
                        for pred_id in rng.sample(other_candidates, k=max(0, extra_pred_num)):
                            pred_task = task_by_id[pred_id]
                            if pred_task.visibility_window is not None and pred_task.visibility_window.window_id == window.window_id:
                                if pred_task.duration + duration <= (window.end - window.start):
                                    predecessors.append(pred_id)
                            elif _can_precede(pred_task, window, duration, time_horizon):
                                predecessors.append(pred_id)
            predecessors = list(dict.fromkeys(predecessors))

            seq_angle = _angle_step(rng, seq_angle, step_limit=22.0)
            tid = f"{seq_name}_{idx}"
            payload_id_req = [rng.choice(critical_payload_ids)] if critical_payload_ids and task_type == "camera" and rng.random() < 0.25 else []
            task = Task(
                task_id=tid,
                duration=duration,
                value=_rint(rng, *profile["value"]),
                cpu=_bounded_sample(rng, *profile["cpu"], cap=cst["cpu_capacity"]),
                gpu=_bounded_sample(rng, *profile["gpu"], cap=cst["gpu_capacity"], floor=0),
                memory=_bounded_sample(rng, *profile["memory"], cap=cst["memory_capacity"]),
                storage=_bounded_sample(rng, *profile["storage"], cap=cst["storage_capacity"]),
                bus=_bounded_sample(rng, *profile["bus"], cap=cst["bus_capacity"]),
                concurrency_cores=_bounded_sample(rng, *profile["concurrency_cores"], cap=cst["cpu_capacity"]),
                power=_bounded_sample(rng, *profile["power"], cap=cst["power_capacity"]),
                thermal_load=_bounded_sample(rng, *profile["thermal_load"], cap=cst["thermal_capacity"]),
                payload_type_requirements=[task_type],
                payload_id_requirements=payload_id_req,
                predecessors=predecessors,
                attitude_angle_deg=seq_angle,
                is_key_task=False,
                visibility_window=window,
            )
            if rng.random() < key_task_probability:
                task.value += key_task_value_bonus
                key_task_candidates.append(task.task_id)
            tasks.append(task)
            task_by_id[tid] = task
            chain_ids[chain].append(tid)
            seq_task_ids.append(tid)
            window_use_counter[window.window_id] += 1
    # 兜底：保证至少存在一个被复用的可见窗口。
    if seq_task_ids and all(c < 2 for c in window_use_counter.values()):
        payload_tasks = [task_by_id[tid] for tid in seq_task_ids if task_by_id[tid].visibility_window is not None]
        if len(payload_tasks) >= 2:
            payload_tasks[1].visibility_window = payload_tasks[0].visibility_window

    for flex_idx in range(flex_count):
        profile = _resource_profile("compute")
        duration = _bounded_sample(rng, *profile["duration"], cap=max(1, min(10, time_horizon)))
        is_dep_flex = flex_idx % 2 == 0 and bool(seq_task_ids)
        predecessors: list[str] = []
        if is_dep_flex:
            pred = rng.choice(seq_task_ids)
            pred_task = task_by_id[pred]
            if _can_precede(pred_task, None, duration, time_horizon):
                predecessors = [pred]
        tid = f"flex_{flex_idx}"
        angle = _angle_step(rng, rng.uniform(0.0, 359.9), step_limit=18.0)
        task = Task(
            task_id=tid,
            duration=duration,
            # 自由任务价值做轻微向中值收敛，降低低价值尾部占比。
            value=max(8, int(round(rng.triangular(profile["value"][0], profile["value"][1], 17.0)))),
            cpu=_bounded_sample(rng, *profile["cpu"], cap=cst["cpu_capacity"]),
            gpu=_bounded_sample(rng, *profile["gpu"], cap=cst["gpu_capacity"], floor=0),
            memory=_bounded_sample(rng, *profile["memory"], cap=cst["memory_capacity"]),
            storage=_bounded_sample(rng, *profile["storage"], cap=cst["storage_capacity"]),
            bus=_bounded_sample(rng, *profile["bus"], cap=cst["bus_capacity"]),
            concurrency_cores=_bounded_sample(rng, *profile["concurrency_cores"], cap=cst["cpu_capacity"]),
            power=_bounded_sample(rng, *profile["power"], cap=cst["power_capacity"]),
            thermal_load=_bounded_sample(rng, *profile["thermal_load"], cap=cst["thermal_capacity"]),
            payload_type_requirements=[],
            payload_id_requirements=[],
            predecessors=predecessors,
            attitude_angle_deg=angle,
            is_key_task=False,
            visibility_window=None,
        )
        if rng.random() < key_task_probability * 0.5:
            task.value += key_task_value_bonus
            key_task_candidates.append(task.task_id)
        tasks.append(task)
        task_by_id[tid] = task
    trimmed_tasks = tasks[: sim["task_count_max"]]
    _apply_hard_key_task_cap(trimmed_tasks, key_task_candidates, max_hard_key_tasks)
    return {
        "seed": seed,
        "horizon": time_horizon,
        "tasks": trimmed_tasks,
        "visibility_windows": visibility_windows,
    }


def generate_task_pool(config: dict, seed: int) -> list[Task]:
    snapshot = generate_simulation_snapshot(config, seed)
    return snapshot["tasks"]
