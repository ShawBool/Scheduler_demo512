# 多目标归一化与动态权重切换 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前以 `value` 为主的目标函数升级为“0-100 归一化多目标 + 配置驱动动态权重切换”，并在高热场景自动提高热安全权重。

**Architecture:** 在 `objective_engine` 中集中实现“指标计算、归一化、动态权重策略、总分聚合”，启发式和 CP-SAT 统一调用同一套目标定义，避免双实现漂移。启发式阶段用于候选排序与软约束评分，CP-SAT 阶段通过线性可表达项构建近似多目标并以整数缩放实现。`pipeline` 负责输出目标分解、权重快照与触发原因，保证可观测与可回放。

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, pytest, JSON/JSONL

---

## Scope Check

该需求属于同一子系统（目标函数层），与已完成热约束能力强耦合，适合单计划执行。为控制风险，按三段拆分：
1. 目标引擎与配置契约。
2. 启发式接入。
3. CP-SAT 接入与集成输出。

## Skill References

- `@test-driven-development`
- `@systematic-debugging`
- `@verification-before-completion`
- `@subagent-driven-development`

## 变更文件结构（先读）

- Create: `src/scheduler/objective_engine.py`
  - 职责：定义多目标指标、0-100 归一化、动态权重切换（含热阈值触发）。
- Create: `tests/test_objective_engine.py`
  - 职责：覆盖归一化正确性、权重总和、动态切换触发与回退。
- Modify: `src/scheduler/config.py`
  - 职责：新增 objective profiles、动态策略阈值、权重校验。
- Modify: `config/runtime.json`
  - 职责：新增动态权重策略开关、热触发阈值配置。
- Modify: `config/constraints.json`
  - 职责：新增多目标权重默认配置。
- Modify: `src/scheduler/heuristic_scheduler.py`
  - 职责：候选排序改为调用 objective_engine 的综合分数。
- Modify: `src/scheduler/cpsat_improver.py`
  - 职责：将目标从单一 `value` 扩展为可线性表达的多目标加权和。
- Modify: `src/scheduler/pipeline.py`
  - 职责：输出 objective_breakdown、active_weight_profile、switch_reason。
- Modify: `tests/test_config_validation.py`
- Modify: `tests/test_heuristic_scheduler.py`
- Modify: `tests/test_cpsat_improver.py`
- Modify: `tests/test_pipeline_integration.py`

---

## Chunk 1: 目标引擎与配置契约

### Task 1: 先写目标引擎失败测试（归一化 + 动态切换）

**Files:**
- Create: `tests/test_objective_engine.py`

- [ ] **Step 1: Write the failing test**

```python
from scheduler.objective_engine import normalize_0_100, select_active_weights


def test_normalize_clamps_into_0_100():
    assert normalize_0_100(raw=120, lower=0, upper=100) == 100.0
    assert normalize_0_100(raw=-10, lower=0, upper=100) == 0.0


def test_dynamic_weights_switch_to_thermal_profile_when_hot_ratio_high():
    base = {"task_value": 0.4, "completion": 0.2, "thermal_safety": 0.2, "power_smoothing": 0.2}
    thermal = {"task_value": 0.2, "completion": 0.2, "thermal_safety": 0.4, "power_smoothing": 0.2}
    active, reason = select_active_weights(
        base_weights=base,
        thermal_weights=thermal,
        thermal_ratio=0.81,
        trigger_threshold=0.80,
    )
    assert active["thermal_safety"] == 0.4
    assert reason == "thermal_ratio_triggered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_objective_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: scheduler.objective_engine`

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/objective_engine.py

def normalize_0_100(raw: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    ratio = (raw - lower) / (upper - lower)
    return max(0.0, min(100.0, ratio * 100.0))


def select_active_weights(base_weights, thermal_weights, thermal_ratio, trigger_threshold):
    if thermal_ratio >= trigger_threshold:
        return thermal_weights, "thermal_ratio_triggered"
    return base_weights, "base_profile"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_objective_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/objective_engine.py tests/test_objective_engine.py
git commit -m "新增目标引擎基础能力，原因：支持归一化与动态权重切换"
```

### Task 2: 配置新增 objective_profiles 与动态策略校验

**Files:**
- Modify: `src/scheduler/config.py`
- Modify: `config/runtime.json`
- Modify: `config/constraints.json`
- Modify: `tests/test_config_validation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_validate_config_rejects_objective_weights_not_sum_to_one():
    cfg = _base_cfg()
    cfg["constraints"]["objective_profiles"] = {
        "base": {"task_value": 0.6, "completion": 0.6},
        "thermal": {"task_value": 0.3, "completion": 0.7},
    }
    with pytest.raises(ValueError, match="sum to 1"):
        validate_config(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_config_validation.py -k "objective_weights_not_sum" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# config.py
constraints.setdefault("objective_profiles", {
  "base": {...},
  "thermal": {...}
})
runtime.setdefault("dynamic_weight_enable", True)
runtime.setdefault("thermal_weight_trigger_ratio", 0.8)

required_profiles = {"base", "thermal"}
if not required_profiles.issubset(set(constraints["objective_profiles"].keys())):
    raise ValueError("constraints.objective_profiles must contain base and thermal")

for profile_name, weights in constraints["objective_profiles"].items():
    total = sum(float(v) for v in weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"constraints.objective_profiles.{profile_name} weights must sum to 1")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_config_validation.py -k "objective_weights_not_sum" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/config.py config/runtime.json config/constraints.json tests/test_config_validation.py
git commit -m "扩展多目标配置契约，原因：支持配置化权重与动态切换阈值"
```

---

## Chunk 2: 启发式接入多目标评分

### Task 3: 启发式排序改为 objective_engine 综合分

**Files:**
- Modify: `src/scheduler/heuristic_scheduler.py`
- Modify: `tests/test_heuristic_scheduler.py`
- Modify: `src/scheduler/objective_engine.py`

- [ ] **Step 1: Write the failing test**

```python
def test_heuristic_prefers_higher_composite_score_over_raw_value(problem_fixture):
    result = build_initial_schedule(problem_fixture, seed=7, initial_attitude_angle_deg=0)
    # 期望“收益略低但热安全/功率波动更优”的任务先入选
    assert result.schedule[0].task_id == "BALANCED_TASK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "composite_score_over_raw_value" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# heuristic_scheduler.py
score_detail = objective_engine.score_candidate(
    task=task,
    predicted_temperatures=temperatures,
    predicted_power_series=predicted_power,
    resource_usage=usage_snapshot,
    context={...}
)
candidate_score = score_detail.total_score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "composite_score_over_raw_value" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/heuristic_scheduler.py src/scheduler/objective_engine.py tests/test_heuristic_scheduler.py
git commit -m "启发式接入多目标评分，原因：由单一收益排序升级为综合软约束排序"
```

### Task 4: 高热场景动态切换权重（启发式）

**Files:**
- Modify: `src/scheduler/heuristic_scheduler.py`
- Modify: `src/scheduler/objective_engine.py`
- Modify: `tests/test_heuristic_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
def test_heuristic_switches_to_thermal_weights_when_ratio_reaches_threshold(problem_fixture_hot):
    result = build_initial_schedule(problem_fixture_hot, seed=8, initial_attitude_angle_deg=0)
    assert result.solver_metadata["active_weight_profile"] == "thermal"
    assert result.solver_metadata["switch_reason"] == "thermal_ratio_triggered"


def test_heuristic_switches_back_to_base_when_thermal_ratio_recovers(problem_fixture_recover):
  result = build_initial_schedule(problem_fixture_recover, seed=9, initial_attitude_angle_deg=0)
  assert result.solver_metadata["active_weight_profile"] == "base"
  assert result.solver_metadata["switch_reason"] == "base_profile"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "switches_to_thermal_weights" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
thermal_ratio = current_temp / max(danger_threshold, 1e-6)
active_weights, reason = select_active_weights(..., thermal_ratio=thermal_ratio, trigger_threshold=cfg_trigger)
metadata["active_weight_profile"] = "thermal" if reason != "base_profile" else "base"
metadata["switch_reason"] = reason
# 推荐口径：使用“候选任务执行后预测峰值温度”计算thermal_ratio，而非仅当前温度
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "switches_to_thermal_weights" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/heuristic_scheduler.py src/scheduler/objective_engine.py tests/test_heuristic_scheduler.py
git commit -m "实现启发式动态权重切换，原因：高热场景自动提升热安全目标占比"
```

---

## Chunk 3: CP-SAT 接入多目标与集成输出

### Task 5: CP-SAT 目标函数改为多目标加权和（0-100缩放）

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Modify: `src/scheduler/objective_engine.py`
- Modify: `tests/test_cpsat_improver.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cpsat_objective_uses_multiple_components_not_only_value(tmp_path, problem_fixture):
    result = improve_schedule(...)
    assert result.objective_breakdown["task_value"] >= 0
    assert result.objective_breakdown["thermal_safety"] >= 0
    assert result.objective_breakdown["power_smoothing"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "objective_uses_multiple_components" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# cpsat_improver.py
# 各目标分量使用整数缩放到[0,10000]后做线性加权
# 对非线性项采用线性近似：
# 1) power_variation 使用L1近似: sum |p_t - p_{t-1}|（AddAbsEquality）
# 2) 姿态切换平滑项使用顺序二值变量计数
multi_obj = (
    w_task * obj_task_value
    + w_completion * obj_completion
    + w_assoc * obj_association
    + w_thermal * obj_thermal_margin_proxy
    - w_power_peak * obj_power_peak
    - w_power_var * obj_power_variation
    + w_util * obj_resource_util
    - w_smooth * obj_attitude_switch_count
)
model.Maximize(multi_obj)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "objective_uses_multiple_components" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py src/scheduler/objective_engine.py tests/test_cpsat_improver.py
git commit -m "升级CP-SAT多目标函数，原因：引入归一化分量加权优化"
```

### Task 6: pipeline 输出目标分解与权重切换证据

**Files:**
- Modify: `src/scheduler/pipeline.py`
- Modify: `tests/test_pipeline_integration.py`
- Modify: `src/scheduler/result_writer.py`（如需）

- [ ] **Step 1: Write the failing test**

```python
def test_pipeline_outputs_objective_breakdown_and_active_profile(tmp_path):
    out = run_pipeline("config", seed=42, output_dir=tmp_path.as_posix())
    assert "objective_breakdown" in out["solver_summary"]
    assert "active_weight_profile" in out["solver_summary"]
    assert "switch_reason" in out["solver_summary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "objective_breakdown_and_active_profile" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
solver_summary.update({
  "objective_breakdown": improve.objective_breakdown,
  "objective_breakdown_raw": improve.objective_breakdown_raw,
  "active_weight_profile": improve.active_weight_profile,
  "switch_reason": improve.switch_reason,
  "solver_status": improve.solver_status,
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "objective_breakdown_and_active_profile" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/pipeline.py tests/test_pipeline_integration.py src/scheduler/result_writer.py
git commit -m "补齐目标函数可观测输出，原因：支持多目标权重切换追踪与复盘"
```

### Task 7: 端到端回归与参数敏感性验证

**Files:**
- Modify: `tests/test_pipeline_integration.py`
- Modify: `tests/test_cpsat_improver.py`

- [ ] **Step 1: Write the failing test**

```python
def test_thermal_profile_increases_thermal_safety_weight_effect(tmp_path):
    # 同一数据下，触发热阈值前后，thermal_safety分量权重变化可观测
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "thermal_profile_increases_thermal_safety_weight_effect" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# 通过配置注入两组trigger_ratio并对比输出summary中的active_weight_profile与objective_breakdown
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py tests/test_cpsat_improver.py -v`
Expected: PASS

Run: `cd .worktrees/ai-develop; pytest tests/ -v`
Expected: PASS

Run: `cd .worktrees/ai-develop; python main.py --config config --seed 666`
Expected: Exit Code 0，输出包含 objective_breakdown / active_weight_profile

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add tests/test_pipeline_integration.py tests/test_cpsat_improver.py
git commit -m "完成多目标动态权重回归验证，原因：确保高热触发与归一化目标行为稳定"
```

---

## 执行顺序与检查点

1. 先完成 Chunk 1（目标引擎与配置），确认归一化和动态切换策略可单测复现。
2. Chunk 2 仅处理启发式，确保排序逻辑切换后仍保持可行解构建稳定。
3. Chunk 3 再接入 CP-SAT 和集成输出，避免一次性改动过大。
4. 每个 Task 必须先红后绿，再提交；提交信息必须中文且包含“原因”。

## 完成定义（DoD）

- 目标函数从单一 value 升级为多目标归一化（0-100）聚合。
- 支持配置化权重，并可按热阈值（默认 0.8）动态切换 profile。
- 启发式与 CP-SAT 都使用同一目标定义来源（允许线性近似形式不同）。
- 输出中可见 objective_breakdown（scaled/raw）、active_weight_profile、switch_reason、solver_status。
- `pytest tests/ -v` 全绿，`python main.py --config config --seed 666` 可运行。

## 审阅循环执行说明（按 Chunk）

- 每个 Chunk 完成后，调用子代理做计划审阅。
- 审阅若有阻断项，先修订该 Chunk，再复审。
- 同一 Chunk 最多 5 轮，超过则升级人工决策。

Plan complete and saved to `docs/superpowers/plans/2026-03-28-multi-objective-normalization-and-dynamic-weights-implementation-plan.md`. Ready to execute?
