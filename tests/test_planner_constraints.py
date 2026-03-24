from scheduler.models import Task, VisibilityWindow
from scheduler.planner import plan_baseline


def _base_config():
    return {
        "runtime": {"time_horizon": 60, "time_step": 1, "solver_timeout_sec": 5},
        "constraints": {
            "cpu_capacity": 3,
            "gpu_capacity": 1,
            "memory_capacity": 10,
            "power_capacity": 4,
            "attitude_time_per_degree": 0.1,
            "payload_type_capacity": {"camera": 1},
        },
        "objective_weights": {"task_value": 100, "lateness_penalty": 1},
    }


def _sample_tasks():
    return [
        Task(
            task_id="key",
            duration=4,
            value=50,
            cpu=1,
            gpu=0,
            memory=2,
            power=1,
            payload_type_requirements=["camera"],
            predecessors=[],
            attitude_angle_deg=10.0,
            is_key_task=True,
            visibility_window=VisibilityWindow("vw_key", 0, 12),
        ),
        Task(
            task_id="pre",
            duration=4,
            value=10,
            cpu=1,
            gpu=0,
            memory=2,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=20.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_pre", 0, 20),
        ),
        Task(
            task_id="succ",
            duration=5,
            value=20,
            cpu=1,
            gpu=0,
            memory=2,
            power=1,
            payload_type_requirements=[],
            predecessors=["pre"],
            attitude_angle_deg=50.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_succ", 2, 30),
        ),
        Task(
            task_id="switch1",
            duration=5,
            value=15,
            cpu=1,
            gpu=0,
            memory=2,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=60.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_sw1", 5, 35),
        ),
        Task(
            task_id="switch2",
            duration=5,
            value=30,
            cpu=1,
            gpu=0,
            memory=2,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=180.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_sw2", 5, 45),
        ),
        Task(
            task_id="too_heavy",
            duration=4,
            value=80,
            cpu=10,
            gpu=0,
            memory=2,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=5.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_heavy", 0, 25),
        ),
    ]


def test_planner_accepts_latest_task_shape_without_legacy_fields():
    cfg = {
        "runtime": {"time_horizon": 40, "time_step": 1, "solver_timeout_sec": 5},
        "constraints": {
            "cpu_capacity": 2,
            "gpu_capacity": 1,
            "memory_capacity": 8,
            "power_capacity": 3,
            "attitude_time_per_degree": 0.2,
            "payload_type_capacity": {"camera": 1},
        },
        "objective_weights": {"task_value": 10, "lateness_penalty": 0},
    }
    tasks = [
        Task(
            task_id="a",
            duration=5,
            value=20,
            cpu=1,
            gpu=0,
            memory=2,
            power=1,
            payload_type_requirements=["camera"],
            predecessors=[],
            attitude_angle_deg=10.0,
            is_key_task=True,
            visibility_window=VisibilityWindow("vw_a", 0, 20),
        ),
        Task(
            task_id="b",
            duration=4,
            value=15,
            cpu=1,
            gpu=0,
            memory=2,
            power=1,
            payload_type_requirements=["camera"],
            predecessors=["a"],
            attitude_angle_deg=30.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_b", 5, 30),
        ),
    ]

    result = plan_baseline(tasks, cfg)

    assert any(item.task_id == "a" for item in result.scheduled_items)


def test_planner_enforces_hard_constraints_and_reports_unscheduled():
    result = plan_baseline(_sample_tasks(), _base_config())

    scheduled = {i.task_id: i for i in result.scheduled_items}
    unscheduled = {t.task_id for t in result.unscheduled_tasks}

    assert "key" in scheduled
    assert "too_heavy" in unscheduled

    for item in result.scheduled_items:
        task = next(t for t in _sample_tasks() if t.task_id == item.task_id)
        if task.visibility_window is not None:
            assert task.visibility_window.start <= item.start
            assert item.end <= task.visibility_window.end

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
        Task(
            task_id="key",
            duration=2,
            value=1,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=0.0,
            is_key_task=True,
            visibility_window=VisibilityWindow("vw_key", 0, 40),
        ),
        Task(
            task_id="c1",
            duration=10,
            value=20,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=20.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_c1", 0, 40),
        ),
        Task(
            task_id="c2",
            duration=10,
            value=20,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=40.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_c2", 0, 40),
        ),
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


def test_planner_derives_rolling_segments_from_key_tasks_and_dag_sources():
    cfg = _base_config()
    tasks = [
        Task(
            task_id="key_0",
            duration=5,
            value=100,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            payload_type_requirements=["camera"],
            predecessors=[],
            attitude_angle_deg=0.0,
            is_key_task=True,
            visibility_window=VisibilityWindow("vw_key_0", 0, 20),
        ),
        Task(
            task_id="src_A",
            duration=5,
            value=20,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=10.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_src_A", 20, 40),
        ),
        Task(
            task_id="src_B",
            duration=5,
            value=20,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            payload_type_requirements=[],
            predecessors=[],
            attitude_angle_deg=20.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_src_B", 45, 55),
        ),
        Task(
            task_id="dep_B",
            duration=5,
            value=10,
            cpu=1,
            gpu=0,
            memory=1,
            power=1,
            payload_type_requirements=[],
            predecessors=["src_B"],
            attitude_angle_deg=40.0,
            is_key_task=False,
            visibility_window=VisibilityWindow("vw_dep_B", 50, 60),
        ),
    ]
    result = plan_baseline(tasks, cfg)
    assert result.rolling_segments
    starts = [segment["start"] for segment in result.rolling_segments]
    assert 0 in starts
    assert 20 in starts
    assert 45 in starts


def test_planner_respects_visibility_window_if_present():
    cfg = _base_config()
    task = Task(
        task_id="w1",
        duration=4,
        value=10,
        cpu=1,
        gpu=0,
        memory=1,
        power=1,
        payload_type_requirements=["camera"],
        predecessors=[],
        attitude_angle_deg=0.0,
        is_key_task=False,
        visibility_window=VisibilityWindow("vw1", 10, 20),
    )
    result = plan_baseline([task], cfg)
    item = next(i for i in result.scheduled_items if i.task_id == "w1")
    assert 10 <= item.start
    assert item.end <= 20


def test_planner_treats_none_window_as_full_horizon():
    cfg = _base_config()
    task = Task(
        task_id="free",
        duration=4,
        value=10,
        cpu=1,
        gpu=0,
        memory=1,
        power=1,
        payload_type_requirements=[],
        predecessors=[],
        attitude_angle_deg=0.0,
        is_key_task=False,
        visibility_window=None,
    )
    result = plan_baseline([task], cfg)
    assert any(i.task_id == "free" for i in result.scheduled_items)

