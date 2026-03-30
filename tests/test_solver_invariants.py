from scheduler.config import load_config
from scheduler.data_loader import load_static_task_bundle
from scheduler.pipeline import run_pipeline


def check_all_invariants(
    out: dict,
    *,
    task_map: dict,
    capacities: dict[str, int],
    max_warning_duration: float,
) -> bool:
    schedule = [x for x in out.get("schedule", []) if x.get("item_type") == "BUSINESS"]
    if not schedule:
        return False

    if any(int(x.get("start", 0)) >= int(x.get("end", 0)) for x in schedule):
        return False

    ids = [x.get("task_id") for x in schedule]
    if len(set(ids)) != len(ids):
        return False

    usage: dict[int, dict[str, int]] = {}
    for item in schedule:
        task = task_map.get(item["task_id"])
        if task is None:
            return False
        for t in range(int(item["start"]), int(item["end"])):
            point = usage.setdefault(t, {"cpu": 0, "gpu": 0, "memory": 0, "power": 0})
            point["cpu"] += int(task.cpu)
            point["gpu"] += int(task.gpu)
            point["memory"] += int(task.memory)
            point["power"] += int(task.power)
            if point["cpu"] > int(capacities["cpu"]):
                return False
            if point["gpu"] > int(capacities["gpu"]):
                return False
            if point["memory"] > int(capacities["memory"]):
                return False
            if point["power"] > int(capacities["power"]):
                return False

    start_map = {x["task_id"]: int(x["start"]) for x in schedule}
    end_map = {x["task_id"]: int(x["end"]) for x in schedule}
    for tid, start in start_map.items():
        for pred in task_map[tid].predecessors:
            if pred in end_map and end_map[pred] > start:
                return False

    actual_warning = float(out.get("metrics", {}).get("max_continuous_warning_duration", 0.0))
    if actual_warning > float(max_warning_duration) + 1e-6:
        return False

    return True


def test_solution_invariants_no_capacity_violation_and_dependency_break(tmp_path):
    cfg = load_config("config")
    out = run_pipeline("config", seed=666, output_dir=tmp_path.as_posix())
    tasks, _, _ = load_static_task_bundle(cfg)
    task_map = {task.task_id: task for task in tasks}
    capacities = {
        "cpu": int(cfg["constraints"]["cpu_capacity"]),
        "gpu": int(cfg["constraints"]["gpu_capacity"]),
        "memory": int(cfg["constraints"]["memory_capacity"]),
        "power": int(cfg["constraints"]["power_capacity"]),
    }
    max_warning_duration = float(cfg["constraints"]["thermal"]["max_warning_duration"])

    assert check_all_invariants(
        out,
        task_map=task_map,
        capacities=capacities,
        max_warning_duration=max_warning_duration,
    )
