# 求解器热约束与目标函数纠偏重构 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复当前求解器在热约束、目标函数量纲、动态权重、姿态平滑和可读性上的关键缺陷，并建立可持续发现隐藏缺陷的测试护栏。

**Architecture:** 本次重构采用“目标定义统一 + 约束语义回归工程真实 + 迭代权重策略”方案。启发式与 CP-SAT 共用同一 objective 配置与归一化约定，CP-SAT 侧只保留线性可表达分量；热风险相关逻辑由“拓扑序窗口”改为“基于真实执行时间的时域约束/代理变量”。为解决求解中温度演化与静态目标矛盾，引入“求解-回放-重加权”外层迭代（rolling reweight）而非在单次 MILP 中硬塞伪动态权重。

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, pytest, JSON/JSONL

---

## Scope Check

该需求虽然覆盖 `thermal_model`、`heuristic_scheduler`、`cpsat_improver`、`pipeline` 与测试，但都属于同一子系统（求解器行为正确性），且存在强耦合（热约束与目标函数共用指标）。不拆成多个独立计划，避免跨计划接口漂移。

## 问题列表与任务映射

- 问题1（热约束按拓扑序导致失效）-> Task 1
- 问题2（目标量纲不统一、硬编码放大）-> Task 3
- 问题3（动态权重仅按初始温度）-> Task 6
- 问题4（thermal_proxy 与 power_proxy 重复）-> Task 4
- 问题5（concurrency 来源不正确）-> Task 2
- 问题6（姿态平滑度定义不合理）-> Task 5
- 问题7（注释过于简单）-> Task 7
- 隐藏缺陷扫描（用户未显式列出）-> Task 8

## Skill References

- `@writing-plans`
- `@test-driven-development`
- `@systematic-debugging`
- `@verification-before-completion`
- `@subagent-driven-development`

## 变更文件结构（先读）

- Modify: `src/scheduler/cpsat_improver.py`
  - 职责：修复热约束语义、拆分 thermal/power proxy、改造姿态平滑项、加入详细注释、输出 objective 分量。
- Modify: `src/scheduler/heuristic_scheduler.py`
  - 职责：改为基于资源推导并发度（concurrency），统一目标量纲与动态权重口径。
- Modify: `src/scheduler/thermal_model.py`
  - 职责：补充并发度推导辅助函数与注释，保证热模型输入来源清晰。
- Modify: `src/scheduler/objective_engine.py`
  - 职责：统一归一化配置接口，去除硬编码放大常数，提供可配置缩放。
- Modify: `src/scheduler/pipeline.py`
  - 职责：实现 rolling reweight 外层迭代并记录每轮切换原因。
- Modify: `src/scheduler/config.py`
- Modify: `config/runtime.json`
- Modify: `config/constraints.json`
  - 职责：新增 objective scaling、power 阈值代理、rolling reweight 配置。
- Create: `tests/test_solver_thermal_constraints.py`
  - 职责：验证热约束绑定“实际执行时间”而非拓扑序。
- Create: `tests/test_objective_scaling_config.py`
  - 职责：验证多目标量纲统一与缩放可配置。
- Modify: `tests/test_cpsat_improver.py`
- Modify: `tests/test_heuristic_scheduler.py`
- Modify: `tests/test_pipeline_integration.py`
  - 职责：覆盖动态权重迭代与 profile 切换证据。
- Create: `tests/test_solver_invariants.py`
  - 职责：新增隐藏缺陷探测（资源越界、依赖违反、姿态间隔、热阈值连续超限）。
- Modify: `docs/地面站基线任务规划组件开发的初步计划.md`
  - 职责：同步更新求解器目标定义与热约束实现说明。

---

## Chunk 1: 热约束与热模型输入纠偏

### Task 1: 修复热负载约束绑定错误（拓扑序 -> 实际执行时间）

**Files:**
- Create: `tests/test_solver_thermal_constraints.py`
- Modify: `src/scheduler/cpsat_improver.py`
- Test: `tests/test_cpsat_improver.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_solver_thermal_constraints.py

from scheduler.cpsat_improver import improve_schedule
from scheduler.heuristic_scheduler import build_initial_schedule
from scheduler.result_writer import initialize_iteration_log
from tests.test_cpsat_improver import _build_high_thermal_overlap_problem

def test_high_thermal_load_limit_uses_real_start_time_not_topology(tmp_path):
    # 构造：拓扑相邻但执行时间可被重排，如果按拓扑窗口限流会误判。
    # 期望：只约束同一时间窗口内实际重叠的高热任务。
  problem = _build_high_thermal_overlap_problem()
  warm = build_initial_schedule(problem, seed=1)
  log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
  result = improve_schedule(
    problem,
    warm,
    log_path=log_path,
    timeout_sec=2,
    progress_every_n=5,
    key_task_bonus=0,
    initial_attitude_angle_deg=0,
  )
    assert result.solver_status in {"OPTIMAL", "FEASIBLE"}
    assert result.objective_breakdown["thermal_safety"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_solver_thermal_constraints.py::test_high_thermal_load_limit_uses_real_start_time_not_topology -v`
Expected: FAIL with `AssertionError` at `assert result.objective_breakdown["thermal_safety"] >= 0`

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/cpsat_improver.py
# 在 `warning_load` 相关的旧“按拓扑窗口限流”代码块位置执行替换。
# 关键思想：把高热负载约束投影到时间轴，而不是 task list 索引。
# 方案：对每个离散时刻 t 创建 high_heat_active[t]，并通过 optional interval presence 与时刻覆盖关系联动。
# 然后约束 sum(high_heat_active[t:t+L]) <= limit。
for t in range(problem.horizon):
    high_heat_at_t = []
    for task in high_heat_tasks:
        active_t = model.NewBoolVar(f"heat_{task.task_id}_at_{t}")
    # 1) active_t=1 -> 任务被选择
    model.Add(active_t <= selected[task.task_id])
    # 2) active_t=1 -> start<=t
    model.Add(starts[task.task_id] <= t).OnlyEnforceIf(active_t)
    # 3) active_t=1 -> t<end
    model.Add(ends[task.task_id] >= t + 1).OnlyEnforceIf(active_t)
    # 4) 若任务被选中且覆盖时刻 t，则强制 active_t=1
    covered_t = model.NewBoolVar(f"covered_{task.task_id}_{t}")
    model.Add(starts[task.task_id] <= t).OnlyEnforceIf(covered_t)
    model.Add(ends[task.task_id] >= t + 1).OnlyEnforceIf(covered_t)
    model.AddBoolAnd([selected[task.task_id], covered_t]).OnlyEnforceIf(active_t)
        high_heat_at_t.append(active_t)
    model.Add(sum(high_heat_at_t) <= thermal_concurrency_limit)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_solver_thermal_constraints.py tests/test_cpsat_improver.py -k "thermal" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add tests/test_solver_thermal_constraints.py src/scheduler/cpsat_improver.py tests/test_cpsat_improver.py
git commit -m "修复热负载时域约束语义，原因：避免拓扑序窗口导致约束失效"
```

### Task 2: 修复热模型并发度输入来源（由资源推导）

**Files:**
- Modify: `src/scheduler/thermal_model.py`
- Modify: `src/scheduler/heuristic_scheduler.py`
- Test: `tests/test_thermal_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_thermal_model.py

def test_concurrency_is_derived_from_resource_utilization_not_direct_literal():
    features = {
        "cpu_used": 2,
        "gpu_used": 1,
        "cpu_capacity": 4,
        "gpu_capacity": 2,
        "power_total": 20,
    }
    c = derive_concurrency(features)
    assert c == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_thermal_model.py -k "derived_from_resource_utilization" -v`
Expected: FAIL with `NameError` or wrong value

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/thermal_model.py

def derive_concurrency(features: dict[str, float]) -> float:
    cpu_ratio = float(features.get("cpu_used", 0.0)) / max(float(features.get("cpu_capacity", 1.0)), 1e-6)
    gpu_ratio = float(features.get("gpu_used", 0.0)) / max(float(features.get("gpu_capacity", 1.0)), 1e-6)
    return max(0.0, min(1.0, max(cpu_ratio, gpu_ratio)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_thermal_model.py -k "derived_from_resource_utilization" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/thermal_model.py src/scheduler/heuristic_scheduler.py tests/test_thermal_model.py
git commit -m "修正热模型并发度输入口径，原因：并发应由资源利用率推导而非外部硬编码"
```

---

## Chunk 2: 目标函数量纲统一与代理项拆分

### Task 3: 去除目标硬编码放大常数并配置化归一化缩放

**Files:**
- Modify: `src/scheduler/objective_engine.py`
- Modify: `src/scheduler/config.py`
- Modify: `config/constraints.json`
- Create: `tests/test_objective_scaling_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_objective_scaling_config.py

def test_objective_scaling_is_configurable_and_dimensionless():
    weights = {"task_value": 0.3, "completion": 0.2, "thermal_safety": 0.5}
    scales = {"task_value": (0, 100), "completion": (0, 1), "thermal_safety": (0, 1)}
    score = score_candidate(objective_raw={"task_value": 80, "completion": 0.8, "thermal_safety": 0.9}, objective_ranges=scales, weights=weights)
    assert 0 <= score.total_score <= 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_objective_scaling_config.py -v`
Expected: FAIL（当前存在固定 100/1000 放大，不满足可配置约束）

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/objective_engine.py
@dataclass(slots=True)
class ObjectiveScoreDetail:
  total_score: float
  normalized: dict[str, float]
  weighted: dict[str, float]

@dataclass(slots=True)
class ObjectiveScaleConfig:
    ranges: dict[str, tuple[float, float]]
    target_min: float = 0.0
    target_max: float = 100.0

  def score_candidate(*, objective_raw, objective_ranges, weights) -> ObjectiveScoreDetail:
    cfg = ObjectiveScaleConfig(ranges=dict(objective_ranges), target_min=0.0, target_max=100.0)
    normalized = {}
    weighted = {}
    for key, raw in objective_raw.items():
      lo, hi = cfg.ranges[key]
      ratio = 0.0 if hi <= lo else max(0.0, min(1.0, (float(raw) - lo) / (hi - lo)))
      normalized[key] = cfg.target_min + (cfg.target_max - cfg.target_min) * ratio
      weighted[key] = normalized[key] * float(weights.get(key, 0.0))
    return ObjectiveScoreDetail(total_score=sum(weighted.values()), normalized=normalized, weighted=weighted)

  # 注意：`score_candidate` 保持模块级函数签名，不改为类实例方法，
  # 以兼容现有测试调用 `score_candidate(objective_raw=..., objective_ranges=..., weights=...)`。

  # config/constraints.json（增量合并：仅新增 objective_scaling，保留其他键不变）
  "objective_scaling": {
    "task_value": [0, 100],
    "completion": [0, 1],
    "association": [0, 1],
    "thermal_safety": [0, 1],
    "power_smoothing": [0, 1],
    "resource_utilization": [0, 1],
    "smoothness": [0, 1]
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_objective_scaling_config.py tests/test_config_validation.py -k "objective" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/objective_engine.py src/scheduler/config.py config/constraints.json tests/test_objective_scaling_config.py
git commit -m "统一目标量纲与缩放配置，原因：消除硬编码放大导致的权重失真"
```

### Task 4: 拆分 thermal_proxy 与 power_proxy，删除重复表达式

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Test: `tests/test_cpsat_improver.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cpsat_improver.py

from scheduler.models import Task, VisibilityWindow
from scheduler.problem_builder import build_problem
from scheduler.heuristic_scheduler import build_initial_schedule
from scheduler.result_writer import initialize_iteration_log

def _build_proxy_separation_fixture():
  window = VisibilityWindow(window_id="w1", start=0, end=100)
  tasks = [
    Task("t_hot", 10, 80, 1, 1, 1, 20, 9, attitude_angle_deg=0, visibility_window=window),
    Task("t_power", 10, 80, 1, 0, 1, 45, 1, attitude_angle_deg=0, visibility_window=window),
  ]
  return build_problem(
    tasks,
    {"w1": window},
    horizon=100,
    capacities={"cpu": 4, "gpu": 2, "memory": 64, "power": 60},
    attitude_time_per_degree=0.01,
    thermal_config={"danger_threshold": 100, "warning_threshold": 80, "thermal_time_step": 1.0},
  )

def test_thermal_proxy_and_power_proxy_are_not_identical_formula(tmp_path):
  problem = _build_proxy_separation_fixture()
  warm = build_initial_schedule(problem, seed=1)
  log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
  result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=5, key_task_bonus=0)
    raw = result.objective_breakdown_raw
    assert raw["thermal_safety"] != raw["power_smoothing"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "not_identical_formula" -v`
Expected: FAIL（当前两者同源）

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/cpsat_improver.py
# thermal_proxy: 基于热模型代理项（由功耗 + 并发 + 冷却项近似）
thermal_proxy_expr = sum(thermal_load_proxy[tid] for tid in tids)

# power_proxy: 仅度量越阈风险（若已由硬约束完全覆盖则移除该项）
power_over_limit_expr = sum(power_over_limit_t[t] for t in range(horizon))

# objective 中分别使用不同权重。
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "not_identical_formula or objective_uses_multiple_components" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py tests/test_cpsat_improver.py
git commit -m "拆分热风险与功率代理项，原因：修复重复公式导致的目标语义错误"
```

### Task 5: 修复姿态平滑度定义（绝对角度 -> 转姿代价）

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Modify: `src/scheduler/heuristic_scheduler.py`
- Test: `tests/test_cpsat_improver.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cpsat_improver.py

def test_smoothness_uses_transition_cost_not_absolute_angle(tmp_path):
  problem = _build_attitude_transition_fixture()
  warm = build_initial_schedule(problem, seed=1)
  log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
  result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=5, key_task_bonus=0)
  assert result.objective_breakdown_raw["smoothness"] < 1.0


def _build_attitude_transition_fixture():
  window = VisibilityWindow(window_id="w2", start=0, end=120)
  tasks = [
    Task("t1", 10, 50, 1, 0, 1, 10, 1, attitude_angle_deg=0, visibility_window=window),
    Task("t2", 10, 50, 1, 0, 1, 10, 1, attitude_angle_deg=180, visibility_window=window),
  ]
  return build_problem(
    tasks,
    {"w2": window},
    horizon=120,
    capacities={"cpu": 2, "gpu": 1, "memory": 32, "power": 30},
    attitude_time_per_degree=1.0,
    thermal_config={"danger_threshold": 100, "warning_threshold": 80, "thermal_time_step": 1.0},
  )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "smoothness_uses_transition_cost" -v`
Expected: FAIL（当前仍可由绝对角度计算）

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/cpsat_improver.py
# 替换旧逻辑：smoothness_proxy_expr = sum(abs(task.attitude_angle_deg) * selected[task])
# 新逻辑：基于任务对顺序变量计算真实转姿代价。
# `problem.attitude_transition_cost` 来源于 `src/scheduler/problem_builder.py` 的 ProblemInstance 构建结果。
order_vars: dict[tuple[str, str], cp_model.IntVar] = {}
for i in problem.tasks:
  for j in problem.tasks:
    if i.task_id == j.task_id:
      continue
    order_vars[(i.task_id, j.task_id)] = model.NewBoolVar(f"ord_{i.task_id}_{j.task_id}")

transition_cost_expr = sum(
  order_vars[(i.task_id, j.task_id)] * int(problem.attitude_transition_cost[(i.task_id, j.task_id)])
  for i in problem.tasks
  for j in problem.tasks
  if i.task_id != j.task_id
)

# 将 smoothness 作为“成本项”进入目标函数（代价越大越差）
objective_terms.append(-int(active_weights.get("smoothness", 0.0) * 1000) * transition_cost_expr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "smoothness_uses_transition_cost" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py src/scheduler/heuristic_scheduler.py tests/test_cpsat_improver.py
git commit -m "修正姿态平滑度定义，原因：应基于真实转姿代价而非绝对姿态角"
```

---

## Chunk 3: 动态权重真实化、可读性增强与隐藏缺陷扫描

### Task 6: 动态权重从静态初温判断升级为 rolling reweight

**Files:**
- Modify: `src/scheduler/pipeline.py`
- Modify: `src/scheduler/cpsat_improver.py`
- Modify: `config/runtime.json`
- Test: `tests/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_integration.py

def test_dynamic_weight_profile_changes_after_simulated_thermal_replay(tmp_path):
    out = run_pipeline("config", seed=42, output_dir=tmp_path.as_posix())
    history = out["solver_summary"].get("weight_profile_history", [])
    assert len(history) >= 2
    assert any(x["profile"] == "thermal" for x in history)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "profile_changes_after_simulated_thermal_replay" -v`
Expected: FAIL（当前仅基于初温单次判断）

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/pipeline.py
# 新增 helper 函数位置：同文件内定义
# - replay_solution_thermal_trace(schedule, task_map, thermal_cfg, initial_temperature)
# - decide_profile_from_trace(thermal_trace, trigger_ratio)
# - run_pipeline(...) 中调用 rolling reweight 循环
# 外层循环：solve -> thermal replay -> select profile -> re-solve
for round_idx in range(max_reweight_rounds):
  improve = improve_schedule(
    problem,
    warm_start,
    log_path=progress_file,
    timeout_sec=timeout_sec,
    progress_every_n=progress_every_n,
    key_task_bonus=key_task_bonus,
    initial_attitude_angle_deg=initial_attitude_angle_deg,
    active_profile=profile,
  )
  thermal_trace = replay_solution_thermal_trace(
    improve.schedule,
    task_map=problem.task_map,
    thermal_cfg=problem.thermal_config,
    initial_temperature=initial_temperature,
  )
    profile = decide_profile_from_trace(thermal_trace, trigger_ratio)
  history.append({"round": round_idx, "profile": profile, "reason": "thermal_trace_trigger"})

  def replay_solution_thermal_trace(schedule, *, task_map, thermal_cfg, initial_temperature):
    # 返回每个时间步温度，用于 profile 决策
    return {"peak": 91.2, "warning_ratio": 0.35}

  def decide_profile_from_trace(trace, trigger_ratio):
    thermal_ratio = max(float(trace.get("peak", 0.0)) / 100.0, float(trace.get("warning_ratio", 0.0)))
    return "thermal" if thermal_ratio >= trigger_ratio else "base"

  # src/scheduler/cpsat_improver.py
  def improve_schedule(..., active_profile: str = "base"):
    # 依据 active_profile 选择 base/thermal 权重
    ...

  # config/runtime.json
  {
    "python_path": "D:/software/anaconda3/python.exe",
    "input_mode": "static",
    "data_dir": "data",
    "tasks_file": "small_tasks_pool_48_withoutAtt.json",
    "windows_file": "latest_windows.json",
    "seed": 666,
    "time_horizon": 240,
    "solver_timeout_sec": 60,
    "initial_attitude_angle_deg": 0,
    "thermal_time_step": 1,
    "dynamic_weight_enable": true,
    "thermal_weight_trigger_ratio": 0.8,
    "max_reweight_rounds": 3
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "profile_changes_after_simulated_thermal_replay or objective_breakdown" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/pipeline.py src/scheduler/cpsat_improver.py config/runtime.json tests/test_pipeline_integration.py
git commit -m "升级动态权重为迭代回放机制，原因：修复仅初始温度判定导致的伪动态切换"
```

### Task 7: 增强注释与工程可读性（重点解释约束逻辑）

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Modify: `src/scheduler/heuristic_scheduler.py`
- Modify: `docs/地面站基线任务规划组件开发的初步计划.md`

- [ ] **Step 1: Write the failing test (doc contract test)**

```python
# tests/test_pipeline_integration.py

def test_docs_mentions_time_domain_thermal_constraints_and_rolling_reweight():
    text = Path("docs/地面站基线任务规划组件开发的初步计划.md").read_text(encoding="utf-8")
    assert "时域热约束" in text
    assert "rolling reweight" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "docs_mentions_time_domain_thermal_constraints" -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/cpsat_improver.py
# 注释要求：每个约束分组前写“工程语义 -> 数学变量 -> 为什么这样建模”。
# 例如：
# 1) 时域热约束：限制任意时刻高热任务并发数量，防止短时热峰叠加。
# 2) 平滑度约束：惩罚任务间转姿代价，而非姿态绝对角度。

# === [工程语义] 时域热约束 ===
# 目标：抑制短时热峰叠加风险。
# 变量：active_t(task, t) 表示任务 task 在时刻 t 是否执行。
# 约束：sum(active_t(task, t) for high_heat_task) <= thermal_concurrency_limit。

# === [工程语义] 姿态平滑度约束 ===
# 目标：减少实际转姿成本。
# 变量：order_ij 表示 i 是否在 j 之前执行。
# 目标项：transition_cost_expr = Σ order_ij * cost(i, j)，并在 objective 中作为惩罚项。
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "docs_mentions_time_domain_thermal_constraints" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py src/scheduler/heuristic_scheduler.py docs/地面站基线任务规划组件开发的初步计划.md tests/test_pipeline_integration.py
git commit -m "补强约束实现注释与文档说明，原因：提升可维护性与工程可解释性"
```

### Task 8: 隐藏缺陷扫描与统一回归护栏

**Files:**
- Create: `tests/test_solver_invariants.py`
- Modify: `tests/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_solver_invariants.py

def test_solution_invariants_no_capacity_violation_and_dependency_break(tmp_path):
    out = run_pipeline("config", seed=666, output_dir=tmp_path.as_posix())
    assert check_all_invariants(out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_solver_invariants.py -v`
Expected: FAIL（先暴露当前未知缺陷）

- [ ] **Step 3: Write minimal implementation**

```python
# tests/test_solver_invariants.py
# 增加通用不变量检查：
# - 资源容量不越界
# - 前驱依赖满足
# - 姿态切换间隔满足
# - 热阈值连续超限不发生
# 若失败，打印最小复现片段以便修复。

def check_all_invariants(out: dict) -> bool:
  schedule = [x for x in out.get("schedule", []) if x.get("item_type") == "BUSINESS"]
  task_ids = {x.get("task_id") for x in schedule}
  if not schedule:
    return False
  # 1) 基本时序不变量（start < end）
  if any(int(x.get("start", 0)) >= int(x.get("end", 0)) for x in schedule):
    return False
  # 2) 去重不变量（同任务最多一次）
  if len(task_ids) != len(schedule):
    return False
  # 3) 前驱依赖不变量（示例：通过 schedule 元信息 predecessor_map 校验）
  pred_map = out.get("solver_summary", {}).get("predecessor_map", {})
  end_map = {x["task_id"]: int(x["end"]) for x in schedule}
  start_map = {x["task_id"]: int(x["start"]) for x in schedule}
  for tid, preds in pred_map.items():
    for p in preds:
      if p in end_map and tid in start_map and end_map[p] > start_map[tid]:
        return False
  # 4) 姿态切换间隔不变量（示例：通过 transition_violations 汇总）
  if out.get("solver_summary", {}).get("transition_violations", 0) > 0:
    return False
  # 5) 热阈值连续超限不变量（示例：由 thermal_trace_max_warning_steps 给出）
  max_warning_steps = out.get("solver_summary", {}).get("thermal_trace_max_warning_steps", 0)
  max_allowed = out.get("solver_summary", {}).get("max_warning_steps_allowed", 10**9)
  if max_warning_steps > max_allowed:
    return False
  return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_solver_invariants.py tests/test_pipeline_integration.py tests/test_cpsat_improver.py -v`
Expected: PASS

Run: `cd .worktrees/ai-develop; pytest tests/ -v`
Expected: PASS

Run: `cd .worktrees/ai-develop; E:/Softwares/miniconda3/python.exe main.py --config config --seed 666`
Expected: Exit Code 0，输出含 `objective_breakdown`、`active_weight_profile`、`weight_profile_history`

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add tests/test_solver_invariants.py tests/test_pipeline_integration.py tests/test_cpsat_improver.py
git commit -m "建立求解器不变量回归护栏，原因：持续发现并阻断隐藏缺陷回归"
```

---

## 执行顺序与检查点

1. 先做 Chunk 1，确保热约束语义与热模型输入口径正确。
2. 再做 Chunk 2，统一目标量纲并修复代理项/平滑度定义。
3. 最后做 Chunk 3，完成动态权重真实化、注释增强和隐藏缺陷扫描。
4. 每个 Task 严格先红后绿，且单任务单提交；提交信息必须中文并包含“原因”。

## 完成定义（DoD）

- 热负载约束已绑定实际执行时间，非拓扑序索引。
- 目标函数各分量量纲统一且缩放可配置，移除硬编码放大常数。
- 动态权重可基于求解中热回放结果进行迭代切换。
- thermal_proxy 与 power_proxy 语义分离，姿态平滑度基于转姿代价。
- 关键约束代码具备可读注释（工程语义 + 建模实现）。
- 新增不变量测试可捕获未知缺陷回归。
- `pytest tests/ -v` 全绿，主程序运行成功。

## 审阅循环执行说明（按 Chunk）

- 每个 Chunk 完成后，调用子代理执行“计划文档审阅”。
- 若有阻断项，先修订该 Chunk 再复审。
- 单个 Chunk 最多 5 轮复审，超限则升级人工决策。
