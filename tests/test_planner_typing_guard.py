import inspect

from scheduler import planner


def test_planner_uses_typed_builder_wrappers_for_cpmodel_methods():
    source = inspect.getsource(planner)
    assert "model.NewBoolVar(" not in source
    assert "model.NewIntVar(" not in source
    assert "_new_bool_var(" in source
    assert "_new_int_var(" in source

