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
    cfg = load_config("config/planner_config.json")
    tasks = generate_task_pool(cfg, seed=7)

    assert cfg["simulation"]["task_count_min"] <= len(tasks) <= cfg["simulation"]["task_count_max"]
    assert not _has_cycle(tasks)

    key_name = cfg["simulation"]["key_task_name"]
    key_tasks = [t for t in tasks if t.task_id.startswith(key_name)]
    assert key_tasks
    assert all(t.is_key_task for t in key_tasks)

    non_key_tasks = [t for t in tasks if not t.is_key_task]
    groups = {t.task_id.split("_")[0] for t in non_key_tasks}
    assert cfg["simulation"]["dag_group_min"] <= len(groups) <= cfg["simulation"]["dag_group_max"]

    assert any(t.payload_type_requirements for t in tasks)
    assert any(t.payload_id_requirements for t in tasks)

    c = cfg["constraints"]
    for t in tasks:
        assert 0 <= t.cpu <= c["cpu_capacity"]
        assert 0 <= t.gpu <= c["gpu_capacity"]
        assert 0 <= t.memory <= c["memory_capacity"]
        assert 0 <= t.storage <= c["storage_capacity"]
        assert 0 <= t.bus <= c["bus_capacity"]
        assert 0 <= t.concurrency_cores <= c["max_concurrency_cores"]
        assert 0 <= t.power <= c["power_capacity"]
        assert 0 <= t.thermal_load <= c["thermal_capacity"]
        assert 0.0 <= t.attitude_angle_deg < 360.0


def test_generate_task_pool_has_no_dangling_predecessor_after_key_task_injection():
    cfg = load_config("config/planner_config.json")
    tasks = generate_task_pool(cfg, seed=11)
    ids = {t.task_id for t in tasks}
    for t in tasks:
        for p in t.predecessors:
            assert p in ids
