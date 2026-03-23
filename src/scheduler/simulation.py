"""任务池仿真生成。"""

from __future__ import annotations

import random
from collections import defaultdict

from .models import Task


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
    }
    return profiles.get(task_type, profiles["camera"])


def _clamp_range(low: int, high: int, cap: int) -> tuple[int, int]:
    upper = max(1, min(high, cap))
    lower = max(1, min(low, upper))
    return lower, upper


def _bounded_sample(rng: random.Random, low: int, high: int, cap: int) -> int:
    lo, hi = _clamp_range(low, high, cap)
    return _rint(rng, lo, hi)


def generate_task_pool(config: dict, seed: int) -> list[Task]:
    rng = random.Random(seed)
    sim = config["simulation"]
    cst = config["constraints"]
    runtime = config["runtime"]

    task_count = rng.randint(sim["task_count_min"], sim["task_count_max"])
    time_horizon = runtime["time_horizon"]
    critical_payload_ids = cst.get("critical_payload_ids", [])
    payload_types = list(cst.get("payload_type_capacity", {}).keys()) or ["camera"]
    predecessor_prob = float(sim.get("predecessor_probability", 0.6))
    max_predecessors = max(1, int(sim.get("max_predecessors", 2)))
    seq_count = _rint(rng, int(sim.get("sequence_count_min", 2)), int(sim.get("sequence_count_max", 3)))
    seq_task_min = max(10, int(sim.get("sequence_task_min", 10)))
    seq_task_max = max(seq_task_min, int(sim.get("sequence_task_max", 20)))
    chains_min = max(2, int(sim.get("dag_chains_per_sequence_min", 2)))
    chains_max = max(chains_min, int(sim.get("dag_chains_per_sequence_max", 4)))

    tasks: list[Task] = []

    planned_seq_sizes = [_rint(rng, seq_task_min, seq_task_max) for _ in range(seq_count)]
    seq_total = sum(planned_seq_sizes)
    reserved_key = 1
    remaining = max(0, task_count - seq_total - reserved_key)
    # 允许插入无刚性时间约束任务，覆盖“有依赖”和“独立”两类。
    flex_count = max(4, remaining) if remaining > 0 else 4

    task_by_id: dict[str, Task] = {}
    seq_task_ids: list[str] = []
    global_time_anchor = 0
    for seq_idx, seq_size in enumerate(planned_seq_sizes, start=1):
        seq_name = f"seq{seq_idx}"
        chain_count = _rint(rng, chains_min, min(chains_max, max(2, seq_size // 3)))
        chain_ids: dict[int, list[str]] = defaultdict(list)
        seq_angle = rng.uniform(0.0, 359.9)
        seq_base = _rint(rng, 0, max(0, time_horizon // 3))
        cursor = seq_base + global_time_anchor
        global_time_anchor = _rint(rng, 0, max(0, time_horizon // 8))

        for idx in range(seq_size):
            chain = idx % chain_count
            task_type = _pick_payload_type(rng, payload_types, idx + seq_idx)
            profile = _resource_profile(task_type)
            duration = _bounded_sample(rng, *profile["duration"], cap=max(1, min(12, time_horizon)))

            predecessors: list[str] = []
            chain_pred = chain_ids[chain][-1] if chain_ids[chain] else None
            if chain_pred:
                predecessors.append(chain_pred)
            if idx > 0 and rng.random() < predecessor_prob:
                other_candidates = [tid for c, tids in chain_ids.items() if c != chain for tid in tids]
                if other_candidates:
                    extra_pred_num = _rint(rng, 1, min(max_predecessors - len(predecessors), len(other_candidates)))
                    predecessors.extend(rng.sample(other_candidates, k=max(0, extra_pred_num)))
            predecessors = list(dict.fromkeys(predecessors))

            pred_end_floor = 0
            pred_latest_end = 0
            if predecessors:
                pred_end_floor = max(task_by_id[p].earliest_start + task_by_id[p].duration for p in predecessors)
                pred_latest_end = max(task_by_id[p].latest_end for p in predecessors)

            max_start = max(0, time_horizon - duration)
            if pred_end_floor > max_start:
                # 依赖窗口过紧时收缩时长，优先保持依赖可执行而非生成冲突数据。
                duration = max(1, time_horizon - pred_end_floor)
                max_start = max(0, time_horizon - duration)

            earliest = min(max_start, max(0, cursor + _rint(rng, 0, 4), pred_end_floor))
            slack = _rint(rng, 3, 18)
            latest_start = min(max_start, earliest + slack)
            latest_start = max(latest_start, pred_end_floor)
            latest_start = max(latest_start, max(0, pred_latest_end - duration))
            latest = min(time_horizon, latest_start + duration)

            seq_angle = _angle_step(rng, seq_angle, step_limit=22.0)
            tid = f"{seq_name}_{idx}"
            payload_id_req = [rng.choice(critical_payload_ids)] if critical_payload_ids and task_type == "camera" and rng.random() < 0.25 else []
            task = Task(
                task_id=tid,
                earliest_start=earliest,
                latest_end=latest,
                duration=duration,
                value=_rint(rng, *profile["value"]),
                cpu=_bounded_sample(rng, *profile["cpu"], cap=cst["cpu_capacity"]),
                gpu=_bounded_sample(rng, *profile["gpu"], cap=max(1, cst["gpu_capacity"])),
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
            )
            tasks.append(task)
            task_by_id[tid] = task
            chain_ids[chain].append(tid)
            seq_task_ids.append(tid)
            cursor = min(time_horizon - 1, earliest + _rint(rng, 1, 4))

    for flex_idx in range(flex_count):
        task_type = _pick_payload_type(rng, payload_types, flex_idx)
        profile = _resource_profile(task_type)
        duration = _bounded_sample(rng, *profile["duration"], cap=max(1, min(10, time_horizon)))
        is_dep_flex = flex_idx % 2 == 0 and bool(seq_task_ids)
        predecessors = []
        if is_dep_flex:
            pred = rng.choice(seq_task_ids)
            predecessors = [pred]
            pred_task = task_by_id[pred]
            # 无固定开始时刻，但确保依赖可执行。
            if pred_task.earliest_start + pred_task.duration > time_horizon - duration:
                predecessors = []
        tid = f"flex_{flex_idx}"
        angle = _angle_step(rng, rng.uniform(0.0, 359.9), step_limit=18.0)
        task = Task(
            task_id=tid,
            earliest_start=0,
            latest_end=time_horizon,
            duration=duration,
            value=max(8, _rint(rng, profile["value"][0], profile["value"][1])),
            cpu=_bounded_sample(rng, *profile["cpu"], cap=cst["cpu_capacity"]),
            gpu=_bounded_sample(rng, *profile["gpu"], cap=max(1, cst["gpu_capacity"])),
            memory=_bounded_sample(rng, *profile["memory"], cap=cst["memory_capacity"]),
            storage=_bounded_sample(rng, *profile["storage"], cap=cst["storage_capacity"]),
            bus=_bounded_sample(rng, *profile["bus"], cap=cst["bus_capacity"]),
            concurrency_cores=_bounded_sample(rng, *profile["concurrency_cores"], cap=cst["cpu_capacity"]),
            power=_bounded_sample(rng, *profile["power"], cap=cst["power_capacity"]),
            thermal_load=_bounded_sample(rng, *profile["thermal_load"], cap=cst["thermal_capacity"]),
            payload_type_requirements=[task_type],
            payload_id_requirements=[],
            predecessors=predecessors,
            attitude_angle_deg=angle,
            is_key_task=False,
        )
        tasks.append(task)
        task_by_id[tid] = task

    key_id = f"{sim['key_task_name']}_0"
    key_type = payload_types[0]
    key_profile = _resource_profile(key_type)
    key_duration = min(int(sim.get("key_task_duration", 5)), max(1, time_horizon // 3))
    key_start = min(int(sim.get("key_task_earliest_start", 0)), max(0, time_horizon - key_duration))
    key_end = min(time_horizon, max(key_start + key_duration + 2, int(sim.get("key_task_latest_end", 30))))
    key_task = Task(
        task_id=key_id,
        earliest_start=key_start,
        latest_end=key_end,
        duration=key_duration,
        value=max(80, int(sim.get("key_task_value", 120))),
        cpu=_bounded_sample(rng, key_profile["cpu"][0], key_profile["cpu"][1], cst["cpu_capacity"]),
        gpu=_bounded_sample(rng, key_profile["gpu"][0], key_profile["gpu"][1], max(1, cst["gpu_capacity"])),
        memory=_bounded_sample(rng, key_profile["memory"][0], key_profile["memory"][1], cst["memory_capacity"]),
        storage=_bounded_sample(rng, key_profile["storage"][0], key_profile["storage"][1], cst["storage_capacity"]),
        bus=_bounded_sample(rng, key_profile["bus"][0], key_profile["bus"][1], cst["bus_capacity"]),
        concurrency_cores=_bounded_sample(
            rng,
            key_profile["concurrency_cores"][0],
            key_profile["concurrency_cores"][1],
            cst["cpu_capacity"],
        ),
        power=_bounded_sample(rng, key_profile["power"][0], key_profile["power"][1], cst["power_capacity"]),
        thermal_load=_bounded_sample(rng, key_profile["thermal_load"][0], key_profile["thermal_load"][1], cst["thermal_capacity"]),
        payload_type_requirements=[key_type],
        payload_id_requirements=critical_payload_ids[:1],
        predecessors=[],
        attitude_angle_deg=float(sim.get("key_task_attitude_angle_deg", 15.0)),
        is_key_task=True,
    )
    tasks.append(key_task)
    return tasks[: sim["task_count_max"]]
