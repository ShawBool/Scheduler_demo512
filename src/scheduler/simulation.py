"""任务池仿真生成。"""

from __future__ import annotations

import random

from .models import Task


def _rint(rng: random.Random, low: int, high: int) -> int:
    if high < low:
        return low
    return rng.randint(low, high)


def generate_task_pool(config: dict, seed: int) -> list[Task]:
    rng = random.Random(seed)
    sim = config["simulation"]
    cst = config["constraints"]
    runtime = config["runtime"]

    task_count = rng.randint(sim["task_count_min"], sim["task_count_max"])
    dag_groups = rng.randint(sim["dag_group_min"], sim["dag_group_max"])
    time_horizon = runtime["time_horizon"]
    critical_payload_ids = cst.get("critical_payload_ids", [])
    payload_types = list(cst.get("payload_type_capacity", {}).keys()) or ["camera"]
    angle_min = float(sim.get("attitude_angle_min", 0.0))
    angle_max = float(sim.get("attitude_angle_max", 359.9))
    predecessor_prob = float(sim.get("predecessor_probability", 0.65))
    max_predecessors = int(sim.get("max_predecessors", 2))
    duration_min = int(sim.get("duration_min", 2))
    duration_max = int(sim.get("duration_max", 12))
    value_min = int(sim.get("value_min", 5))
    value_max = int(sim.get("value_max", 50))

    tasks: list[Task] = []
    base_task_count = max(1, task_count - 1)
    group_sizes = [base_task_count // dag_groups] * dag_groups
    for i in range(base_task_count % dag_groups):
        group_sizes[i] += 1

    task_index = 0
    for g in range(dag_groups):
        gname = f"g{g+1}"
        group_task_ids: list[str] = []
        for k in range(group_sizes[g]):
            duration = _rint(rng, duration_min, duration_max)
            earliest = _rint(rng, 0, max(0, time_horizon - duration - 1))
            latest = _rint(rng, earliest + duration, time_horizon)
            tid = f"{gname}_{task_index}"
            task_index += 1

            preds: list[str] = []
            if group_task_ids and rng.random() < predecessor_prob:
                max_pred = min(max_predecessors, len(group_task_ids))
                pred_count = _rint(rng, 1, max_pred)
                preds = rng.sample(group_task_ids, k=pred_count)

            payload_type_req = [rng.choice(payload_types)] if rng.random() < 0.5 else []
            payload_id_req = [rng.choice(critical_payload_ids)] if critical_payload_ids and rng.random() < 0.35 else []
            attitude_angle_deg = rng.uniform(angle_min, angle_max)

            task = Task(
                task_id=tid,
                earliest_start=earliest,
                latest_end=latest,
                duration=duration,
                value=_rint(rng, value_min, value_max),
                cpu=_rint(rng, 0, cst["cpu_capacity"]),
                gpu=_rint(rng, 0, cst["gpu_capacity"]),
                memory=_rint(rng, 0, cst["memory_capacity"]),
                storage=_rint(rng, 0, cst["storage_capacity"]),
                bus=_rint(rng, 0, cst["bus_capacity"]),
                concurrency_cores=_rint(rng, 0, cst["max_concurrency_cores"]),
                power=_rint(rng, 0, cst["power_capacity"]),
                thermal_load=_rint(rng, 0, cst["thermal_capacity"]),
                payload_type_requirements=payload_type_req,
                payload_id_requirements=payload_id_req,
                predecessors=preds,
                attitude_angle_deg=attitude_angle_deg,
                is_key_task=False,
            )
            tasks.append(task)
            group_task_ids.append(tid)

    key_id = f"{sim['key_task_name']}_0"
    key_task = Task(
        task_id=key_id,
        earliest_start=int(sim.get("key_task_earliest_start", 0)),
        latest_end=min(int(sim.get("key_task_latest_end", 30)), time_horizon),
        duration=int(sim.get("key_task_duration", 5)),
        value=int(sim.get("key_task_value", 100)),
        cpu=min(int(sim.get("key_task_cpu", 1)), cst["cpu_capacity"]),
        gpu=0,
        memory=min(int(sim.get("key_task_memory", 2)), cst["memory_capacity"]),
        storage=min(int(sim.get("key_task_storage", 2)), cst["storage_capacity"]),
        bus=min(int(sim.get("key_task_bus", 1)), cst["bus_capacity"]),
        concurrency_cores=min(int(sim.get("key_task_concurrency_cores", 1)), cst["max_concurrency_cores"]),
        power=min(int(sim.get("key_task_power", 2)), cst["power_capacity"]),
        thermal_load=min(int(sim.get("key_task_thermal_load", 2)), cst["thermal_capacity"]),
        payload_type_requirements=[payload_types[0]],
        payload_id_requirements=critical_payload_ids[:1],
        predecessors=[],
        attitude_angle_deg=float(sim.get("key_task_attitude_angle_deg", 0.0)),
        is_key_task=True,
    )
    tasks.append(key_task)
    return tasks
