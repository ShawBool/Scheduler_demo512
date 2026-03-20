from copy import deepcopy

from scheduler.models import DangerRule, LinkWindow, Task
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
            "container_capacity": 2,
            "power_capacity": 4,
            "thermal_capacity": 4,
            "attitude_switch_time": 2,
            "link_windows": [
                {"kind": "uplink", "start": 0, "end": 20},
                {"kind": "downlink", "start": 15, "end": 50},
            ],
            "danger_rules": [
                {
                    "rule_id": "d1",
                    "min_power": 4,
                    "min_thermal": 4,
                    "forbidden_attitudes": ["agile"],
                    "description": "禁止高热高功率敏捷姿态",
                }
            ],
        },
        "objective_weights": {"task_value": 100, "lateness_penalty": 1},
    }


def _sample_tasks():
    return [
        Task("key", 0, 12, 4, 50, 1, 0, 2, 1, 1, 1, 1, 1, ["camera"], ["P1"], [], "earth", None, True),
        Task("pre", 0, 20, 4, 10, 1, 0, 2, 1, 1, 1, 1, 1, [], [], [], "earth", None, False),
        Task("succ", 2, 30, 5, 20, 1, 0, 2, 1, 1, 1, 1, 1, [], [], ["pre"], "earth", None, False),
        Task("comm", 15, 45, 5, 25, 1, 0, 2, 1, 1, 1, 1, 1, [], [], [], "earth", "downlink", False),
        Task("switch1", 5, 35, 5, 15, 1, 0, 2, 1, 1, 1, 1, 1, [], [], [], "earth", None, False),
        Task("switch2", 5, 45, 5, 30, 1, 0, 2, 1, 1, 1, 1, 1, [], [], [], "agile", None, False),
        Task("danger", 0, 30, 4, 100, 1, 0, 2, 1, 1, 1, 4, 4, [], [], [], "agile", None, False),
        Task("too_heavy", 0, 25, 4, 80, 10, 0, 2, 1, 1, 1, 1, 1, [], [], [], "earth", None, False),
    ]


def test_planner_enforces_hard_constraints_and_reports_unscheduled():
    result = plan_baseline(_sample_tasks(), _base_config())

    scheduled = {i.task_id: i for i in result.scheduled_items}
    unscheduled = {t.task_id for t in result.unscheduled_tasks}

    assert "key" in scheduled
    assert "too_heavy" in unscheduled
    assert "danger" in unscheduled

    for item in result.scheduled_items:
        task = next(t for t in _sample_tasks() if t.task_id == item.task_id)
        assert task.earliest_start <= item.start
        assert item.end <= task.latest_end

    assert scheduled["succ"].start >= scheduled["pre"].end

    # 通信任务必须落在窗口内
    comm_item = scheduled["comm"]
    assert 15 <= comm_item.start
    assert comm_item.end <= 50

    # 姿态切换开销
    ordered = sorted(result.scheduled_items, key=lambda x: x.start)
    for a, b in zip(ordered, ordered[1:]):
        at = next(t for t in _sample_tasks() if t.task_id == a.task_id)
        bt = next(t for t in _sample_tasks() if t.task_id == b.task_id)
        if at.attitude_mode != bt.attitude_mode:
            assert b.start >= a.end + _base_config()["constraints"]["attitude_switch_time"]

    assert "scheduled_count" in result.constraint_stats
    assert "unscheduled_count" in result.constraint_stats


def test_planner_objective_beats_naive_and_keeps_infeasible_tasks():
    cfg = _base_config()
    tasks = [
        Task("key", 0, 10, 2, 1, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", None, True),
        Task("low", 0, 6, 6, 5, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", None, False),
        Task("high", 0, 6, 6, 60, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", None, False),
        Task("bad", 0, 6, 3, 100, 9, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", None, False),
    ]
    result = plan_baseline(tasks, cfg)
    assert result.objective_value >= 61
    unscheduled = {t.task_id for t in result.unscheduled_tasks}
    assert "bad" in unscheduled


def test_planner_handles_impossible_window_without_model_invalid():
    cfg = _base_config()
    tasks = [
        Task("key", 0, 10, 3, 20, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", None, True),
        Task("bad_window", 8, 10, 5, 999, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", None, False),
    ]

    result = plan_baseline(tasks, cfg)
    scheduled_ids = {i.task_id for i in result.scheduled_items}
    unscheduled_ids = {t.task_id for t in result.unscheduled_tasks}

    assert "key" in scheduled_ids
    assert "bad_window" in unscheduled_ids
    assert result.constraint_stats.get("solver_status") in {"optimal", "feasible"}


def test_payload_binding_and_bandwidth_budget_constraints():
    cfg = _base_config()
    cfg["constraints"]["payload_type_capacity"] = {"camera": 1}
    cfg["constraints"]["critical_payload_ids"] = ["P1"]
    cfg["constraints"]["link_windows"] = [{"kind": "downlink", "start": 0, "end": 40, "bandwidth": 3}]

    tasks = [
        Task("key", 0, 10, 2, 1, 1, 0, 1, 1, 1, 1, 1, 1, ["camera"], ["P1"], [], "earth", None, True),
        Task("p1", 0, 30, 6, 40, 1, 0, 1, 1, 1, 1, 1, 1, ["camera"], ["P1"], [], "earth", None, False),
        Task("p2", 0, 30, 6, 35, 1, 0, 1, 1, 1, 1, 1, 1, ["camera"], ["P1"], [], "earth", None, False),
        Task("bad_type", 0, 30, 4, 99, 1, 0, 1, 1, 1, 1, 1, 1, ["radar"], [], [], "earth", None, False),
        Task("bad_id", 0, 30, 4, 98, 1, 0, 1, 1, 1, 1, 1, 1, [], ["P2"], [], "earth", None, False),
        Task("comm_a", 0, 40, 10, 30, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", "downlink", False),
        Task("comm_b", 0, 40, 10, 30, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", "downlink", False),
    ]

    result = plan_baseline(tasks, cfg)
    scheduled_ids = {i.task_id for i in result.scheduled_items}
    unscheduled_ids = {t.task_id for t in result.unscheduled_tasks}

    assert "bad_type" in unscheduled_ids
    assert "bad_id" in unscheduled_ids
    payload_items = [i for i in result.scheduled_items if i.task_id in {"p1", "p2"}]
    for t in range(0, cfg["runtime"]["time_horizon"] + 1):
        active_payload = sum(1 for item in payload_items if item.start <= t < item.end)
        assert active_payload <= 1

    comm_items = [i for i in result.scheduled_items if i.comm_kind == "downlink"]
    for t in range(0, cfg["runtime"]["time_horizon"] + 1):
        active = sum(1 for item in comm_items if item.start <= t < item.end)
        assert active <= 3


def test_objective_value_uses_solver_weighted_objective():
    cfg = _base_config()
    cfg["objective_weights"] = {"task_value": 10, "lateness_penalty": 7}
    tasks = [
        Task("key", 0, 10, 2, 1, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", None, True),
        Task("late", 8, 20, 4, 5, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], "earth", None, False),
    ]

    result = plan_baseline(tasks, cfg)
    plain_value_sum = sum(i.value for i in result.scheduled_items)
    assert result.objective_value != plain_value_sum
    assert result.objective_value == 60.0
