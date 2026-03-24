from collections import defaultdict, deque
from copy import deepcopy

from scheduler.config import load_config
from scheduler.simulation import generate_simulation_snapshot, generate_task_pool


def _task_domain(task, horizon: int) -> tuple[int, int]:
    if task.visibility_window is None:
        return 0, horizon
    return task.visibility_window.start, task.visibility_window.end


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

    key_tasks = [t for t in tasks if t.is_key_task]
    assert len(key_tasks) <= cfg["simulation"]["max_hard_key_tasks"]

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
        if t.visibility_window is not None:
            assert t.visibility_window.start < t.visibility_window.end
            assert t.duration <= (t.visibility_window.end - t.visibility_window.start)


def test_generate_task_pool_has_parallel_sequences_and_dag_chains():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=9)

    payload_tasks = [t for t in tasks if t.payload_type_requirements]
    free_tasks = [t for t in tasks if not t.payload_type_requirements]
    assert payload_tasks
    assert free_tasks

    ratio = len(payload_tasks) / len(tasks)
    expected = cfg["simulation"]["structured_task_ratio"]
    assert abs(ratio - expected) <= 0.2


def test_structured_task_ratio_controls_payload_task_share():
    cfg = load_config("config")

    cfg_low = deepcopy(cfg)
    cfg_low["simulation"]["structured_task_ratio"] = 0.3
    low_tasks = generate_task_pool(cfg_low, seed=33)
    low_payload = sum(1 for t in low_tasks if t.payload_type_requirements)

    cfg_high = deepcopy(cfg)
    cfg_high["simulation"]["structured_task_ratio"] = 0.8
    high_tasks = generate_task_pool(cfg_high, seed=33)
    high_payload = sum(1 for t in high_tasks if t.payload_type_requirements)

    assert high_payload > low_payload


def test_structured_task_ratio_zero_is_guarded_to_keep_payload_tasks():
    cfg = load_config("config")

    cfg_zero = deepcopy(cfg)
    cfg_zero["simulation"]["structured_task_ratio"] = 0.0
    tasks = generate_task_pool(cfg_zero, seed=33)

    assert tasks
    structured_count = sum(1 for t in tasks if t.payload_type_requirements)
    assert (structured_count / len(tasks)) >= 0.6


def test_dependency_density_controls_extra_predecessors():
    cfg = load_config("config")

    cfg_sparse = deepcopy(cfg)
    cfg_sparse["simulation"]["dependency_density"] = 0.0
    sparse_tasks = generate_task_pool(cfg_sparse, seed=27)
    sparse_predecessors = sum(len(t.predecessors) for t in sparse_tasks if t.payload_type_requirements)

    cfg_dense = deepcopy(cfg)
    cfg_dense["simulation"]["dependency_density"] = 0.95
    dense_tasks = generate_task_pool(cfg_dense, seed=27)
    dense_predecessors = sum(len(t.predecessors) for t in dense_tasks if t.payload_type_requirements)

    assert dense_predecessors > sparse_predecessors


def test_window_reuse_target_controls_window_task_density():
    cfg = load_config("config")

    def _avg_window_occupancy(tasks):
        counts = defaultdict(int)
        for task in tasks:
            if task.visibility_window is not None and task.payload_type_requirements:
                counts[task.visibility_window.window_id] += 1
        if not counts:
            return 0.0
        return sum(counts.values()) / len(counts)

    low_scores = []
    high_scores = []
    for seed in (41, 42, 43, 44, 45):
        cfg_low = deepcopy(cfg)
        cfg_low["simulation"]["window_reuse_target"] = 1.0
        low_scores.append(_avg_window_occupancy(generate_task_pool(cfg_low, seed=seed)))

        cfg_high = deepcopy(cfg)
        cfg_high["simulation"]["window_reuse_target"] = 5.0
        high_scores.append(_avg_window_occupancy(generate_task_pool(cfg_high, seed=seed)))

    assert sum(high_scores) / len(high_scores) > sum(low_scores) / len(low_scores)


def test_generate_task_pool_has_no_dangling_predecessor_after_key_task_injection():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=11)
    ids = {t.task_id for t in tasks}
    for t in tasks:
        for p in t.predecessors:
            assert p in ids


def test_generate_task_pool_only_payload_tasks_require_visibility_window():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=17)
    for t in tasks:
        if t.payload_type_requirements:
            assert t.visibility_window is not None
        else:
            assert t.visibility_window is None


def test_simulation_generates_window_pool_before_tasks_and_reuses_windows():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=42)

    payload_tasks = [t for t in tasks if t.payload_type_requirements]
    assert payload_tasks

    shared: dict[str, int] = {}
    for t in payload_tasks:
        assert t.visibility_window is not None
        shared.setdefault(t.visibility_window.window_id, 0)
        shared[t.visibility_window.window_id] += 1

    assert any(cnt >= 2 for cnt in shared.values())


def test_simulation_shared_window_supports_mixed_payload_types():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=42)

    payload_tasks = [t for t in tasks if t.payload_type_requirements and t.visibility_window is not None]
    by_window: dict[str, set[str]] = defaultdict(set)
    for t in payload_tasks:
        by_window[t.visibility_window.window_id].add(t.payload_type_requirements[0])

    assert any(len(payload_types) >= 2 for payload_types in by_window.values())


def test_generate_task_pool_dependency_windows_are_schedulable():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=13)
    task_by_id = {t.task_id: t for t in tasks}
    for task in tasks:
        for pred_id in task.predecessors:
            pred = task_by_id[pred_id]
            pred_start, _ = _task_domain(pred, cfg["runtime"]["time_horizon"])
            _, succ_end = _task_domain(task, cfg["runtime"]["time_horizon"])
            latest_succ_start = succ_end - task.duration
            assert pred_start + pred.duration <= latest_succ_start


def test_shared_window_dependency_duration_is_feasible():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=23)
    task_by_id = {t.task_id: t for t in tasks}

    for t in tasks:
        if t.visibility_window is None:
            continue
        for pred_id in t.predecessors:
            pred = task_by_id[pred_id]
            if pred.visibility_window is None:
                continue
            if pred.visibility_window.window_id == t.visibility_window.window_id:
                window_span = t.visibility_window.end - t.visibility_window.start
                assert pred.duration + t.duration <= window_span


def test_generate_task_pool_attitude_and_task_type_are_meaningful():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=21)
    seq_index = defaultdict(list)
    for t in tasks:
        if t.task_id.startswith("seq"):
            seq_index[t.task_id.split("_")[0]].append(t)
    for seq_tasks in seq_index.values():
        ordered = sorted(
            seq_tasks,
            key=lambda x: (
                x.visibility_window.start if x.visibility_window is not None else 0,
                x.task_id,
            ),
        )
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
    flex_tasks = [t for t in tasks if t.task_id.startswith("flex_")]
    assert flex_tasks
    assert all(t.visibility_window is None for t in flex_tasks)
    assert any(t.predecessors for t in flex_tasks)
    assert any(not t.predecessors for t in flex_tasks)


def test_free_tasks_have_no_window_and_no_explicit_time_bounds():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=99)
    free_tasks = [t for t in tasks if t.task_id.startswith("flex_")]
    assert free_tasks
    assert all(t.visibility_window is None for t in free_tasks)


def test_generate_task_pool_gpu_can_be_zero_when_capacity_is_zero():
    cfg = load_config("config")
    cfg = deepcopy(cfg)
    cfg["constraints"]["gpu_capacity"] = 0

    tasks = generate_task_pool(cfg, seed=7)

    assert tasks
    assert all(t.gpu == 0 for t in tasks)


def test_generate_task_pool_handles_empty_visibility_windows(monkeypatch):
    cfg = load_config("config")
    cfg = deepcopy(cfg)

    def _empty_windows(*_args, **_kwargs):
        return []

    monkeypatch.setattr("scheduler.simulation._generate_visibility_windows", _empty_windows)
    tasks = generate_task_pool(cfg, seed=19)

    payload_tasks = [t for t in tasks if t.payload_type_requirements]
    assert payload_tasks
    assert all(t.visibility_window is not None for t in payload_tasks)


def test_generate_visibility_windows_accepts_duration_min_equal_one():
    cfg = load_config("config")
    cfg = deepcopy(cfg)
    cfg["simulation"]["visibility_window_duration_min"] = 1
    cfg["simulation"]["visibility_window_duration_max"] = 1

    snapshot = generate_simulation_snapshot(cfg, seed=29)
    assert snapshot["visibility_windows"]
    assert all((w.end - w.start) == 1 for w in snapshot["visibility_windows"])


def test_generate_simulation_snapshot_contains_visibility_windows_and_tasks():
    cfg = load_config("config")
    snapshot = generate_simulation_snapshot(cfg, seed=7)

    assert snapshot["seed"] == 7
    assert snapshot["horizon"] == cfg["runtime"]["time_horizon"]
    assert snapshot["tasks"]
    assert snapshot["visibility_windows"]

    window_ids = {w.window_id for w in snapshot["visibility_windows"]}
    assert window_ids

    for task in snapshot["tasks"]:
        if task.payload_type_requirements:
            assert task.visibility_window is not None
            assert task.visibility_window.window_id in window_ids


def test_generate_task_pool_stays_backward_compatible_with_snapshot():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=15)
    snapshot = generate_simulation_snapshot(cfg, seed=15)

    assert tasks == snapshot["tasks"]


def test_default_free_task_share_is_about_18_percent():
    cfg = load_config("config")

    free_ratios = []
    for seed in (101, 102, 103, 104, 105):
        tasks = generate_task_pool(cfg, seed=seed)
        free_tasks = sum(1 for t in tasks if not t.payload_type_requirements)
        free_ratios.append(free_tasks / len(tasks))

    avg_free_ratio = sum(free_ratios) / len(free_ratios)
    assert 0.15 <= avg_free_ratio <= 0.20


def test_structured_ratio_has_minimum_guard_for_generation():
    cfg = load_config("config")
    cfg = deepcopy(cfg)
    cfg["simulation"]["structured_task_ratio"] = 0.1

    structured_ratios = []
    for seed in (111, 112, 113, 114, 115):
        tasks = generate_task_pool(cfg, seed=seed)
        structured_count = sum(1 for t in tasks if t.payload_type_requirements)
        structured_ratios.append(structured_count / len(tasks))

    avg_structured_ratio = sum(structured_ratios) / len(structured_ratios)
    assert avg_structured_ratio >= 0.6


def test_hard_key_task_count_is_capped_by_max_hard_key_tasks():
    cfg = load_config("config")
    cfg = deepcopy(cfg)
    cfg["simulation"]["key_task_probability"] = 1.0
    cfg["simulation"]["max_hard_key_tasks"] = 1

    tasks = generate_task_pool(cfg, seed=203)

    hard_key_count = sum(1 for t in tasks if t.is_key_task)
    assert hard_key_count <= 1


def test_key_task_probability_reduction_lowers_hard_key_density_across_seeds():
    cfg = load_config("config")
    seeds = list(range(220, 260))

    cfg_high = deepcopy(cfg)
    cfg_high["simulation"]["key_task_probability"] = 0.06
    cfg_high["simulation"]["max_hard_key_tasks"] = 10_000

    cfg_low = deepcopy(cfg)
    cfg_low["simulation"]["key_task_probability"] = 0.01
    cfg_low["simulation"]["max_hard_key_tasks"] = 10_000

    def _avg_hard_key_ratio(local_cfg):
        ratios = []
        for seed in seeds:
            tasks = generate_task_pool(local_cfg, seed=seed)
            hard_key_count = sum(1 for t in tasks if t.is_key_task)
            ratios.append(hard_key_count / len(tasks))
        return sum(ratios) / len(ratios)

    high_ratio = _avg_hard_key_ratio(cfg_high)
    low_ratio = _avg_hard_key_ratio(cfg_low)

    assert low_ratio < high_ratio


def test_flex_value_distribution_has_fewer_low_value_tasks():
    cfg = load_config("config")

    low_value = 0
    total_flex = 0
    for seed in (121, 122, 123, 124, 125, 126, 127, 128):
        tasks = generate_task_pool(cfg, seed=seed)
        flex_values = [t.value for t in tasks if t.task_id.startswith("flex_")]
        total_flex += len(flex_values)
        low_value += sum(1 for value in flex_values if value <= 14)

    assert total_flex > 0
    assert (low_value / total_flex) <= 0.2
