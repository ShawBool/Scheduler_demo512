from collections import defaultdict, deque

from scheduler.config import load_config
from scheduler.simulation import generate_task_pool


def _has_cycle(tasks):
    graph = defaultdict(list)
    indeg = defaultdict(int)
    ids = {t.task_id for t in tasks}
    for t in tasks:
        indeg.setdefault(t.task_id, 0)
        for p in t.predecessors:
            if p in ids:
                graph[p].append(t.task_id)
                indeg[t.task_id] += 1
    q = deque([n for n, d in indeg.items() if d == 0])
    seen = 0
    while q:
        n = q.popleft()
        seen += 1
        for nxt in graph[n]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    return seen != len(indeg)


def test_generate_task_pool_meets_ranges_and_constraints():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=7)

    assert cfg["simulation"]["task_count_min"] <= len(tasks) <= cfg["simulation"]["task_count_max"]
    assert not _has_cycle(tasks)

    key_name = cfg["simulation"]["key_task_name"]
    key_tasks = [t for t in tasks if t.task_id.startswith(key_name)]
    assert key_tasks
    assert all(t.is_key_task for t in key_tasks)

    c = cfg["constraints"]
    for t in tasks:
        assert 1 <= t.cpu <= c["cpu_capacity"]
        assert 0 <= t.gpu <= c["gpu_capacity"]
        assert 1 <= t.memory <= c["memory_capacity"]
        assert 1 <= t.storage <= c["storage_capacity"]
        assert 1 <= t.bus <= c["bus_capacity"]
        assert 1 <= t.concurrency_cores <= c["cpu_capacity"]
        assert 1 <= t.power <= c["power_capacity"]
        assert 1 <= t.thermal_load <= c["thermal_capacity"]
        assert 0.0 <= t.attitude_angle_deg < 360.0


def test_generate_task_pool_has_parallel_sequences_and_dag_chains():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=9)
    non_key = [t for t in tasks if not t.is_key_task and t.task_id.startswith("seq")]
    seq_index: dict[str, list] = defaultdict(list)
    for t in non_key:
        seq_id = t.task_id.split("_")[0]
        seq_index[seq_id].append(t)

    assert 2 <= len(seq_index) <= 3
    for seq_tasks in seq_index.values():
        assert 10 <= len(seq_tasks) <= 20

    seq_ids = sorted(seq_index.keys())
    found_parallel_feasible_windows = False
    for i in range(len(seq_ids)):
        for j in range(i + 1, len(seq_ids)):
            for a in seq_index[seq_ids[i]]:
                for b in seq_index[seq_ids[j]]:
                    if a.earliest_start < b.latest_end - b.duration and b.earliest_start < a.latest_end - a.duration:
                        found_parallel_feasible_windows = True
                        break
                if found_parallel_feasible_windows:
                    break
            if found_parallel_feasible_windows:
                break
    assert found_parallel_feasible_windows


def test_generate_task_pool_has_no_dangling_predecessor_after_key_task_injection():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=11)
    ids = {t.task_id for t in tasks}
    for t in tasks:
        for p in t.predecessors:
            assert p in ids


def test_generate_task_pool_dependency_windows_are_schedulable():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=13)
    task_by_id = {t.task_id: t for t in tasks}
    for task in tasks:
        for pred_id in task.predecessors:
            pred = task_by_id[pred_id]
            latest_pred_finish = pred.latest_end
            latest_succ_start = task.latest_end - task.duration
            assert latest_pred_finish <= task.latest_end
            assert pred.earliest_start + pred.duration <= latest_succ_start


def test_generate_task_pool_attitude_and_task_type_are_meaningful():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=21)
    seq_index = defaultdict(list)
    for t in tasks:
        if t.task_id.startswith("seq"):
            seq_index[t.task_id.split("_")[0]].append(t)
    for seq_tasks in seq_index.values():
        ordered = sorted(seq_tasks, key=lambda x: (x.earliest_start, x.task_id))
        for prev, nxt in zip(ordered, ordered[1:]):
            angle_jump = abs(prev.attitude_angle_deg - nxt.attitude_angle_deg)
            angle_jump = min(angle_jump, 360.0 - angle_jump)
            assert angle_jump <= 75.0

    by_type = defaultdict(list)
    for t in tasks:
        if t.payload_type_requirements:
            by_type[t.payload_type_requirements[0]].append(t)

    assert {"camera", "radar", "relay"} <= set(by_type.keys())
    assert any(t.gpu >= 1 and t.cpu >= 2 for t in by_type["radar"])
    assert any(t.storage >= 2 and t.bus >= 2 for t in by_type["camera"])
    assert all(t.bus >= 2 for t in by_type["relay"])


def test_generate_task_pool_has_flexible_tasks_with_and_without_dependencies():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=31)
    horizon = cfg["runtime"]["time_horizon"]
    flex_tasks = [t for t in tasks if t.task_id.startswith("flex_")]
    assert flex_tasks
    assert all(t.earliest_start == 0 for t in flex_tasks)
    assert all(t.latest_end == horizon for t in flex_tasks)
    assert any(t.predecessors for t in flex_tasks)
    assert any(not t.predecessors for t in flex_tasks)
