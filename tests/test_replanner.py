from scheduler.config import load_config
from scheduler.replanner import evaluate_replan_trigger


def test_replanner_triggers_immediately_for_l3():
    cfg = load_config("config")
    decision = evaluate_replan_trigger({"temp": 90, "power": 80}, cfg, predicted_gain=0)
    assert decision["trigger"] is True
    assert decision["level"] == "L3"
    assert decision["window_count"] >= 1


def test_replanner_respects_gain_threshold_for_non_l3():
    cfg = load_config("config")
    decision = evaluate_replan_trigger({"temp": 83, "power": 70}, cfg, predicted_gain=10)
    assert decision["trigger"] is False
    assert decision["level"] == "L2"
    assert decision["reason"] == "below-gain-threshold"


def test_replanner_no_disturbance_returns_none_level():
    cfg = load_config("config")
    decision = evaluate_replan_trigger({"temp": 50, "power": 40}, cfg, predicted_gain=100)
    assert decision["trigger"] is False
    assert decision["level"] == "NONE"

