import inspect

from scheduler import planner


def test_planner_uses_typed_builder_wrappers_for_cpmodel_methods():
    source = inspect.getsource(planner)
    assert "model.NewBoolVar(" not in source
    assert "model.NewIntVar(" not in source
    assert "model.new_bool_var(" in source
    assert "model.new_int_var(" in source
    assert "model.new_optional_interval_var(" in source
    assert "_task_numeric_attr(" in source


def test_planner_does_not_depend_on_legacy_task_fields():
    source = inspect.getsource(planner)
    assert "storage" not in source
    assert "bus" not in source
    assert "concurrency_cores" not in source
    assert "thermal_load" not in source
    assert "payload_id_requirements" not in source

