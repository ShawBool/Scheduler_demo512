from scheduler.models import ResourceSnapshot, ScheduleItem, ScheduleResult, Task, VisibilityWindow


def test_models_can_be_instantiated_and_contain_chinese_docs():
    task = Task(
        task_id="t1",
        duration=5,
        value=10,
        cpu=1,
        gpu=0,
        memory=2,
        storage=3,
        bus=1,
        concurrency_cores=1,
        power=2,
        thermal_load=3,
        payload_type_requirements=["camera"],
        payload_id_requirements=["P1"],
        predecessors=[],
        attitude_angle_deg=30.0,
        is_key_task=True,
        visibility_window=VisibilityWindow("vw_t1", 0, 20),
    )
    snapshot = ResourceSnapshot(
        timestamp=5,
        cpu=1,
        gpu=0,
        memory=2,
        storage=3,
        bus=1,
        concurrency_cores=1,
        attitude_angle_deg=15.0,
        power=2,
        thermal=3,
    )
    item = ScheduleItem(task_id="t1", start=0, end=5, attitude_angle_deg=30.0, value=10)
    result = ScheduleResult(
        scheduled_items=[item],
        unscheduled_tasks=[],
        objective_value=10,
        constraint_stats={"scheduled_count": 1},
    )

    assert task.task_id == "t1"
    assert task.visibility_window is not None
    assert task.visibility_window.window_id == "vw_t1"
    assert snapshot.concurrency_cores == 1
    assert snapshot.attitude_angle_deg == 15.0
    assert result.objective_value == 10
    assert "任务" in (Task.__doc__ or "")
    assert "计划" in (ScheduleItem.__doc__ or "")
    assert "资源" in (ResourceSnapshot.__doc__ or "")


def test_task_without_visibility_window_is_free_task():
    task = Task(
        task_id="free_t1",
        duration=3,
        value=6,
        cpu=1,
        gpu=0,
        memory=1,
        storage=1,
        bus=1,
        concurrency_cores=1,
        power=1,
        thermal_load=1,
    )

    assert task.visibility_window is None


def test_visibility_window_contains_only_id_start_end_fields():
    window = VisibilityWindow(window_id="vw_simple", start=1, end=9)

    assert window.window_id == "vw_simple"
    assert window.start == 1
    assert window.end == 9
    assert set(window.__slots__) == {"window_id", "start", "end"}
