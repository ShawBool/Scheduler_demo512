from scheduler.models import (
    DangerRule,
    LinkWindow,
    ResourceSnapshot,
    ScheduleItem,
    ScheduleResult,
    Task,
)


def test_models_can_be_instantiated_and_contain_chinese_docs():
    task = Task(
        task_id="t1",
        earliest_start=0,
        latest_end=20,
        duration=5,
        value=10,
        cpu=1,
        gpu=0,
        memory=2,
        storage=3,
        bus=1,
        container_slots=1,
        power=2,
        thermal_load=3,
        payload_type_requirements=["camera"],
        payload_id_requirements=["P1"],
        predecessors=[],
        attitude_mode="earth",
        comm_kind="downlink",
        is_key_task=True,
    )
    snapshot = ResourceSnapshot(
        timestamp=5,
        cpu=1,
        gpu=0,
        memory=2,
        storage=3,
        bus=1,
        container=1,
        power=2,
        thermal=3,
    )
    window = LinkWindow(kind="downlink", start=0, end=50, bandwidth=1)
    rule = DangerRule(
        rule_id="r1",
        min_power=10,
        min_thermal=10,
        forbidden_attitudes=["agile"],
        description="高热高功率下禁止敏捷姿态",
    )
    item = ScheduleItem(task_id="t1", start=0, end=5, attitude_mode="earth", comm_kind="downlink", value=10)
    result = ScheduleResult(
        scheduled_items=[item],
        unscheduled_tasks=[],
        objective_value=10,
        constraint_stats={"scheduled_count": 1},
    )

    assert task.task_id == "t1"
    assert snapshot.container == 1
    assert window.end == 50
    assert "高热" in rule.description
    assert result.objective_value == 10
    assert "任务" in (Task.__doc__ or "")
    assert "计划" in (ScheduleItem.__doc__ or "")
    assert "资源" in (ResourceSnapshot.__doc__ or "")
