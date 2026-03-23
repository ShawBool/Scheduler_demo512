from scheduler.models import Task
from scheduler.planner import plan_baseline


def _base_config():
    return {
        "runtime": {"time_horizon": 60, "time_step": 1, "solver_timeout_sec": 5},
        "constraints": {
            "cpu_capacity": 3,
            "gpu_capacity": 1,
            "memory_capacity": 10,
            "storage_capacity": 10,
            "bus_capacity": 5,
            "power_capacity": 4,
            "thermal_capacity": 4,
            "attitude_time_per_degree": 0.1,
            "critical_payload_ids": ["P1"],
            "payload_type_capacity": {"camera": 1},
        },
        "objective_weights": {"task_value": 100, "lateness_penalty": 1},
    }


def _sample_tasks():
    return [
        Task("key", 0, 12, 4, 50, 1, 0, 2, 1, 1, 1, 1, 1, ["camera"], ["P1"], [], 10.0, True),
        Task("pre", 0, 20, 4, 10, 1, 0, 2, 1, 1, 1, 1, 1, [], [], [], 20.0, False),
        Task("succ", 2, 30, 5, 20, 1, 0, 2, 1, 1, 1, 1, 1, [], [], ["pre"], 50.0, False),
        Task("switch1", 5, 35, 5, 15, 1, 0, 2, 1, 1, 1, 1, 1, [], [], [], 60.0, False),
        Task("switch2", 5, 45, 5, 30, 1, 0, 2, 1, 1, 1, 1, 1, [], [], [], 180.0, False),
        Task("too_heavy", 0, 25, 4, 80, 10, 0, 2, 1, 1, 1, 1, 1, [], [], [], 5.0, False),
    ]


def test_planner_enforces_hard_constraints_and_reports_unscheduled():
    result = plan_baseline(_sample_tasks(), _base_config())

    scheduled = {i.task_id: i for i in result.scheduled_items}
    unscheduled = {t.task_id for t in result.unscheduled_tasks}

    assert "key" in scheduled
    assert "too_heavy" in unscheduled

    for item in result.scheduled_items:
        task = next(t for t in _sample_tasks() if t.task_id == item.task_id)
        assert task.earliest_start <= item.start
        assert item.end <= task.latest_end

    assert scheduled["succ"].start >= scheduled["pre"].end

    ordered = sorted(result.scheduled_items, key=lambda x: x.start)
    for a, b in zip(ordered, ordered[1:]):
        at = next(t for t in _sample_tasks() if t.task_id == a.task_id)
        bt = next(t for t in _sample_tasks() if t.task_id == b.task_id)
        angle_delta = abs(at.attitude_angle_deg - bt.attitude_angle_deg)
        angle_delta = min(angle_delta, 360.0 - angle_delta)
        expected_gap = int(round(angle_delta * _base_config()["constraints"]["attitude_time_per_degree"]))
        assert b.start >= a.end + expected_gap

    assert "scheduled_count" in result.constraint_stats
    assert "unscheduled_count" in result.constraint_stats


def test_planner_concurrency_core_limit():
    cfg = _base_config()
    cfg["constraints"]["cpu_capacity"] = 2
    tasks = [
        Task("key", 0, 40, 2, 1, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], 0.0, True),
        Task("c1", 0, 40, 10, 20, 1, 0, 1, 1, 1, 2, 1, 1, [], [], [], 20.0, False),
        Task("c2", 0, 40, 10, 20, 1, 0, 1, 1, 1, 2, 1, 1, [], [], [], 40.0, False),
    ]

    result = plan_baseline(tasks, cfg)
    items = [i for i in result.scheduled_items if i.task_id in {"c1", "c2"}]
    for t in range(cfg["runtime"]["time_horizon"] + 1):
        active = [
            next(task for task in tasks if task.task_id == item.task_id)
            for item in items
            if item.start <= t < item.end
        ]
        assert sum(x.cpu for x in active) <= cfg["constraints"]["cpu_capacity"]


def test_planner_derives_rolling_segments_from_position_service_and_dag_sources():
    cfg = _base_config()
    tasks = [
        Task("position_service_0", 0, 20, 5, 100, 1, 0, 1, 1, 1, 1, 1, 1, ["camera"], ["P1"], [], 0.0, True),
        Task("src_A", 20, 40, 5, 20, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], 10.0, False),
        Task("src_B", 45, 55, 5, 20, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], 20.0, False),
        Task("dep_B", 50, 60, 5, 10, 1, 0, 1, 1, 1, 1, 1, 1, [], [], ["src_B"], 40.0, False),
    ]
    result = plan_baseline(tasks, cfg)
    assert result.rolling_segments
    starts = [segment["start"] for segment in result.rolling_segments]
    assert 0 in starts
    assert 20 in starts
    assert 45 in starts

