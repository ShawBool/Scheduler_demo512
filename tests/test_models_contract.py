from scheduler.models import Task


def test_task_accepts_current_static_fields():
    task = Task(
        task_id="t1",
        duration=3,
        value=10,
        cpu=1,
        gpu=0,
        memory=2,
        power=1,
        thermal_load=1,
        payload_type_requirements=["camera"],
        predecessors=[],
        attitude_angle_deg=None,
        is_key_task=False,
        visibility_window=None,
    )
    assert task.thermal_load == 1
