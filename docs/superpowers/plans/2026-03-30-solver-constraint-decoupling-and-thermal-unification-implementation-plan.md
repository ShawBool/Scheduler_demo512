# Solver Constraint Decoupling and Thermal Unification Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一热约束与各类约束值计算口径（以 `thermal_model.py` 为准），将约束值计算从求解器剥离，并移除动态权重与重复目标分解字段，保证姿态并行语义正确且配置目录精简可维护。

**Architecture:** 新增“约束值计算引擎”模块承接热回放、目标分量与约束分值计算，`heuristic_scheduler.py`、`cpsat_improver.py`、`pipeline.py` 仅做调度编排和求解建模。求解器保留 CP-SAT 必须的变量和线性约束拼装，所有可复用计算通过独立函数完成。配置层同步做瘦身和契约收敛，并补充 JSON 注释文档。

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, pytest, JSON

---

## Scope Check

本需求覆盖求解器、启发式、热模型适配、配置契约和文档，但都围绕“静态基线求解核心”同一子系统，属于可在单计划内完成的耦合重构，不再拆分多个独立计划。

## Skill References

- `@writing-plans`
- `@test-driven-development`
- `@systematic-debugging`
- `@verification-before-completion`

## File Structure Map

### New Files

- Create: `src/scheduler/constraint_value_engine.py`
  - Responsibility: 统一热回放、目标分量计算、约束值计算（供启发式/CP-SAT/pipeline 共同调用）。
- Create: `tests/test_constraint_value_engine.py`
  - Responsibility: 锁定统一热模型口径与约束值计算接口行为。
- Create: `docs/配置文件注释说明.md`
  - Responsibility: 对 `config/*.json` 剩余字段逐项注释（用途、单位、默认值、是否必填、引用代码）。

### Modified Files

- Modify: `src/scheduler/thermal_model.py`
  - Responsibility: 补充热特征标准化辅助函数，作为唯一热计算内核依赖。
- Modify: `src/scheduler/heuristic_scheduler.py`
  - Responsibility: 调用统一约束值引擎，移除动态权重逻辑，支持资源不冲突任务并行放置。
- Modify: `src/scheduler/cpsat_improver.py`
  - Responsibility: 仅保留求解变量/约束组装；移除动态权重与 `objective_breakdown_raw`，引入详细注释。
- Modify: `src/scheduler/pipeline.py`
  - Responsibility: 删除 rolling reweight 流程，改为单轮求解 + 统一后评估。
- Modify: `src/scheduler/objective_engine.py`
  - Responsibility: 去除动态 profile 切换能力，保留纯归一化与打分工具。
- Modify: `src/scheduler/result_writer.py`
  - Responsibility: 同姿态（转姿时长为 0）不插入 ATTITUDE 段。
- Modify: `src/scheduler/config.py`
  - Responsibility: 删除不再使用字段加载与校验，收敛配置契约。
- Modify: `config/runtime.json`
- Modify: `config/constraints.json`
- Modify: `config/logging.json`
- Delete: `config/replan.json`
  - Responsibility: 清理无效/无未来使用字段，保留最小必要配置。

### Test Updates

- Modify: `tests/test_cpsat_improver.py`
- Modify: `tests/test_heuristic_scheduler.py`
- Modify: `tests/test_pipeline_integration.py`
- Modify: `tests/test_result_writer.py`
- Modify: `tests/test_config_validation.py`
- Modify: `tests/test_objective_engine.py`
- Modify: `tests/test_thermal_model.py`
- Modify: `tests/test_solver_invariants.py`
  - Responsibility: 移除动态权重/原始分解相关断言，新增“同姿态并行”“统一热计算”断言。

---

## Chunk 1: 统一热约束与约束值引擎（解耦基础）

### Task 1: 新建统一约束值计算引擎并落地热模型复用

**Files:**
- Create: `src/scheduler/constraint_value_engine.py`
- Test: `tests/test_constraint_value_engine.py`
- Modify: `src/scheduler/thermal_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_constraint_value_engine.py

from scheduler.constraint_value_engine import simulate_task_trace_with_thermal_model
from scheduler.models import Task


def test_thermal_trace_uses_same_model_kernel_as_thermal_model_module():
    task = Task(
        task_id="t1",
        duration=3,
        value=1,
        cpu=2,
        gpu=1,
        memory=1,
        power=10,
        thermal_load=2,
    )
    trace = simulate_task_trace_with_thermal_model(
        task=task,
        initial_temperature=25.0,
        capacities={"cpu": 4, "gpu": 2},
        thermal_cfg={
            "thermal_time_step": 1.0,
            "env_temperature": 20.0,
            "coefficients": {"a_p": 0.002, "a_c": 0.03, "lambda_concurrency": 0.01, "k_cool": 0.005},
        },
    )

    assert len(trace) == 3
    assert trace[-1] > trace[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_constraint_value_engine.py::test_thermal_trace_uses_same_model_kernel_as_thermal_model_module -v`
Expected: FAIL with `ModuleNotFoundError` for `constraint_value_engine`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/constraint_value_engine.py

from __future__ import annotations

from .models import Task
from .thermal_model import SemiEmpiricalThermalModelV1, ThermalCoefficients


def _build_model(thermal_cfg: dict) -> SemiEmpiricalThermalModelV1:
    coeff = thermal_cfg.get("coefficients", {})
    return SemiEmpiricalThermalModelV1(
        ThermalCoefficients(
            a_p=float(coeff.get("a_p", 0.0)),
            a_c=float(coeff.get("a_c", 0.0)),
            lambda_concurrency=float(coeff.get("lambda_concurrency", 0.0)),
            k_cool=float(coeff.get("k_cool", 0.0)),
        ),
        env_temperature=float(thermal_cfg.get("env_temperature", 20.0)),
    )


def simulate_task_trace_with_thermal_model(*, task: Task, initial_temperature: float, capacities: dict[str, int], thermal_cfg: dict) -> list[float]:
    model = _build_model(thermal_cfg)
    dt = float(thermal_cfg.get("thermal_time_step", 1.0))
    state = {"temperature": float(initial_temperature)}
    out: list[float] = []
    for _ in range(int(task.duration)):
        state = model.update(
            state,
            {
                "power_total": float(task.power),
                "cpu_used": float(task.cpu),
                "gpu_used": float(task.gpu),
                "cpu_capacity": max(float(capacities.get("cpu", 1)), 1.0),
                "gpu_capacity": max(float(capacities.get("gpu", 1)), 1.0),
            },
            dt,
        )
        out.append(float(state["temperature"]))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_constraint_value_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/constraint_value_engine.py src/scheduler/thermal_model.py tests/test_constraint_value_engine.py
git commit -m "新增统一约束值计算引擎，变更原因：热计算口径需与thermal_model完全一致"
```

### Task 2: 将启发式中的热评估和目标分量迁移到统一引擎

**Files:**
- Modify: `src/scheduler/heuristic_scheduler.py`
- Test: `tests/test_heuristic_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_heuristic_scheduler.py

def test_heuristic_uses_constraint_value_engine_for_thermal_scoring(monkeypatch, composite_problem_fixture):
    import scheduler.constraint_value_engine as cve

    called = {"hit": False}

    def fake_score_task_candidate(*args, **kwargs):
        called["hit"] = True
        return {"total_score": 1.0, "objective_breakdown": {"thermal_safety": 1.0}}

    monkeypatch.setattr(cve, "score_task_candidate", fake_score_task_candidate)
    build_initial_schedule(composite_problem_fixture, seed=1, initial_attitude_angle_deg=0)

    assert called["hit"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py::test_heuristic_uses_constraint_value_engine_for_thermal_scoring -v`
Expected: FAIL because `score_task_candidate` is not used yet.

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/heuristic_scheduler.py (replace local duplicated raw/scoring blocks)
from .constraint_value_engine import score_task_candidate, replay_idle_thermal_state

# in candidate loop
state_at_candidate = replay_idle_thermal_state(
    model=thermal_model,
    state=current_thermal_state,
    idle_duration=max(0, candidate - current_time),
    dt=thermal_time_step,
)
score_detail = score_task_candidate(
    task=task,
    state_at_candidate=state_at_candidate,
    capacities=problem.capacities,
    thermal_cfg=problem.thermal_config,
    objective_ranges=objective_ranges,
    weights=base_weights,
    transition_time=transition,
)
score = float(score_detail["total_score"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "constraint_value_engine or thermal" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/heuristic_scheduler.py tests/test_heuristic_scheduler.py
git commit -m "启发式接入统一约束值引擎，变更原因：消除热与目标分量计算重复实现"
```

---

## Chunk 2: 求解器瘦身、姿态并行修正、动态权重移除

### Task 3: 求解器中移除动态权重并删除 objective_breakdown_raw

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Modify: `src/scheduler/objective_engine.py`
- Modify: `src/scheduler/pipeline.py`
- Test: `tests/test_cpsat_improver.py`
- Test: `tests/test_pipeline_integration.py`
- Test: `tests/test_objective_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_integration.py

def test_solver_summary_does_not_expose_objective_breakdown_raw(tmp_path):
    out = run_pipeline("config", seed=42, output_dir=tmp_path.as_posix())
    assert "objective_breakdown_raw" not in out["solver_summary"]


# tests/test_objective_engine.py

def test_objective_engine_no_longer_exports_dynamic_profile_selector():
    import scheduler.objective_engine as engine
    assert not hasattr(engine, "select_active_weights")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py::test_solver_summary_does_not_expose_objective_breakdown_raw tests/test_objective_engine.py::test_objective_engine_no_longer_exports_dynamic_profile_selector -v`
Expected: FAIL because pipeline still emits `objective_breakdown_raw` and objective engine still has dynamic selector.

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/cpsat_improver.py
@dataclass(slots=True)
class ImproveResult:
    schedule: list[ScheduleItem]
    unscheduled: list[UnscheduledItem]
    solver_status: str
    objective_value: float
    iteration_log_count: int
    runtime_ms: int
    objective_breakdown: dict[str, float]

# remove fields:
# - objective_breakdown_raw
# - active_weight_profile
# - switch_reason
# remove parameter: active_profile
# remove dynamic profile branch; use static base weights only
```

```python
# src/scheduler/pipeline.py
# remove rolling reweight loop and related fields:
# - dynamic_weight_enable
# - thermal_weight_trigger_ratio
# - max_reweight_rounds
# - weight_profile_history
# - objective_breakdown_raw
# single call improve_schedule(
#     problem,
#     warm,
#     log_path=progress_file,
#     timeout_sec=float(cfg["runtime"]["solver_timeout_sec"]),
#     progress_every_n=int(cfg["runtime"]["cpsat_log_every_n"]),
#     key_task_bonus=float(cfg["objective_weights"]["key_task_bonus"]),
# )
```

```python
# src/scheduler/objective_engine.py
# remove select_active_weights() and dynamic-profile-only utilities
# keep: build_scale_config(), normalize_to_scale(), score_candidate()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py tests/test_pipeline_integration.py tests/test_objective_engine.py -v`
Expected: PASS with no references to `objective_breakdown_raw` or dynamic profile switching.

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py src/scheduler/objective_engine.py src/scheduler/pipeline.py tests/test_cpsat_improver.py tests/test_pipeline_integration.py tests/test_objective_engine.py
git commit -m "删除动态权重与重复目标分解字段，变更原因：静态求解阶段不需要实时重加权"
```

### Task 4: 姿态并行语义修正（同姿态不插入 ATTITUDE，且允许并行）

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Modify: `src/scheduler/result_writer.py`
- Modify: `src/scheduler/heuristic_scheduler.py`
- Test: `tests/test_result_writer.py`
- Test: `tests/test_cpsat_improver.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_result_writer.py

def test_materialize_skips_attitude_item_when_transition_is_zero():
    schedule = [ScheduleItem(task_id="t_same", start=10, end=15, value=1, is_key_task=False, visibility_window_id="w")]
    task_map = {
        "t_same": Task(task_id="t_same", duration=5, value=1, cpu=1, gpu=0, memory=1, power=1, thermal_load=1, attitude_angle_deg=0)
    }
    out = materialize_att_segments(
        schedule,
        task_map=task_map,
        initial_attitude_angle_deg=0,
        attitude_time_per_degree=1.0,
    )
    assert len([x for x in out if x.item_type == "ATTITUDE"]) == 0


# tests/test_cpsat_improver.py

def test_same_attitude_tasks_can_overlap_when_resources_allow(tmp_path):
    window = VisibilityWindow(window_id="w1", start=0, end=50)
    tasks = [
        Task("a", 10, 10, 1, 0, 1, 1, 1, attitude_angle_deg=30, visibility_window=window),
        Task("b", 10, 10, 1, 0, 1, 1, 1, attitude_angle_deg=30, visibility_window=window),
    ]
    problem = build_problem(
        tasks,
        {"w1": window},
        horizon=60,
        capacities={"cpu": 4, "gpu": 1, "memory": 32, "power": 10},
        attitude_time_per_degree=1.0,
        thermal_config={"thermal_time_step": 1.0},
    )
    warm = build_initial_schedule(problem, seed=1)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    result = improve_schedule(problem, warm, log_path=log_path, timeout_sec=2, progress_every_n=1, key_task_bonus=0)
    selected = [item for item in result.schedule if item.task_id in {"a", "b"}]
    assert len(selected) == 2
    assert selected[0].start == selected[1].start
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_result_writer.py::test_materialize_skips_attitude_item_when_transition_is_zero tests/test_cpsat_improver.py::test_same_attitude_tasks_can_overlap_when_resources_allow -v`
Expected: FAIL because当前实现对同姿态仍串行化并插入 ATTITUDE。

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/result_writer.py
if target_att is not None:
    transition = _transition_duration(current_attitude, target_att, attitude_time_per_degree)
    if transition > 0:
        # only then add ATTITUDE item
        materialized.append(
            ScheduleItem(
                task_id=f"{item.task_id}_att",
                start=item.start - transition,
                end=item.start,
                value=0,
                is_key_task=False,
                visibility_window_id=item.visibility_window_id,
                item_type="ATTITUDE",
            )
        )
```

```python
# src/scheduler/cpsat_improver.py
# in pairwise attitude constraints:
if lr_gap == 0 and rl_gap == 0:
    # same attitude, no ordering constraint; allow overlap by resource cumulative
    continue
# otherwise keep disjunctive ordering constraints
```

```python
# src/scheduler/heuristic_scheduler.py
# remove hard serialization by global current_time when selecting earliest start,
# use predecessor/window/resource feasibility as primary gate
earliest = 0 if not task.predecessors else max(finished_at[p] for p in task.predecessors)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_result_writer.py tests/test_cpsat_improver.py tests/test_heuristic_scheduler.py -k "attitude or overlap or parallel" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py src/scheduler/result_writer.py src/scheduler/heuristic_scheduler.py tests/test_result_writer.py tests/test_cpsat_improver.py tests/test_heuristic_scheduler.py
git commit -m "修正姿态并行语义，变更原因：同姿态任务无需转姿且应在资源允许时并行"
```

### Task 5: 求解器约束值计算彻底解耦并补充可读注释

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Modify: `src/scheduler/constraint_value_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cpsat_improver.py

def test_solver_calls_constraint_value_engine_for_objective_coefficients(monkeypatch, tmp_path):
    from scheduler.models import Task, VisibilityWindow
    from scheduler.problem_builder import build_problem
    from scheduler.heuristic_scheduler import build_initial_schedule
    from scheduler.result_writer import initialize_iteration_log
    from scheduler.cpsat_improver import improve_schedule
    import scheduler.constraint_value_engine as cve

    called = {"hit": False}

    def fake_build_solver_coefficients(*args, **kwargs):
        called["hit"] = True
        tasks = kwargs["tasks"]
        return {
            "task_value": {task.task_id: 1 for task in tasks},
            "completion_step": 1,
            "association": {task.task_id: 1 for task in tasks},
            "thermal_proxy": {task.task_id: 1 for task in tasks},
            "power_proxy": {task.task_id: 0 for task in tasks},
            "utilization": {task.task_id: 1 for task in tasks},
            "smoothness_scale": 1,
        }

    monkeypatch.setattr(cve, "build_solver_coefficients", fake_build_solver_coefficients)

    w = VisibilityWindow(window_id="w", start=0, end=30)
    tasks = [Task("x", 5, 10, 1, 0, 1, 1, 1, attitude_angle_deg=0, visibility_window=w)]
    problem = build_problem(
        tasks,
        {"w": w},
        horizon=30,
        capacities={"cpu": 2, "gpu": 1, "memory": 10, "power": 10},
        attitude_time_per_degree=0.1,
        thermal_config={"thermal_time_step": 1.0},
    )
    warm = build_initial_schedule(problem, seed=1)
    log_path = initialize_iteration_log(tmp_path / "solver_progress.jsonl")
    improve_schedule(problem, warm, log_path=log_path, timeout_sec=1, progress_every_n=1, key_task_bonus=0)

    assert called["hit"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py::test_solver_calls_constraint_value_engine_for_objective_coefficients -v`
Expected: FAIL because求解器仍内联计算系数。

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/constraint_value_engine.py

def build_solver_coefficients(*, tasks, capacities, thermal_cfg, key_task_bonus, objective_ranges, component_scale):
    max_value = max((float(t.value) for t in tasks), default=1.0)
    task_value = {t.task_id: int(round(component_scale * (float(t.value) + key_task_bonus * float(t.is_key_task)) / max_value)) for t in tasks}
    association = {t.task_id: int(round(component_scale * min(len(t.predecessors), 1))) for t in tasks}
    thermal_proxy = {t.task_id: int(round(component_scale * float(t.thermal_load) / max(max((x.thermal_load for x in tasks), default=1), 1))) for t in tasks}
    power_proxy = {t.task_id: int(round(component_scale * max(0.0, float(t.power) - 0.7 * float(capacities["power"])) / max(float(capacities["power"]), 1.0))) for t in tasks}
    utilization = {t.task_id: int(round(component_scale * min(1.0, float(t.cpu) / max(float(capacities["cpu"]), 1.0) + float(t.gpu) / max(float(capacities["gpu"]), 1.0)))) for t in tasks}
    return {
        "task_value": task_value,
        "completion_step": max(1, int(round(component_scale / max(len(tasks), 1)))),
        "association": association,
        "thermal_proxy": thermal_proxy,
        "power_proxy": power_proxy,
        "utilization": utilization,
        "smoothness_scale": max(1, int(round(component_scale / 180.0))),
    }

# src/scheduler/cpsat_improver.py
# replace in-function coefficient math with call to build_solver_coefficients()
# add block comments for each constraint group:
# - dependency constraints
# - initial attitude constraints
# - attitude ordering constraints
# - thermal concurrency constraints
# - resource cumulative constraints
# - objective term assembly
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "constraint_value_engine or objective" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py src/scheduler/constraint_value_engine.py tests/test_cpsat_improver.py
git commit -m "完成求解器约束值计算解耦并增强注释，变更原因：避免各处约束计算口径分歧"
```

---

## Chunk 3: 配置清理、配置文档化与全量回归

### Task 6: 清理配置目录无效字段并收敛配置加载契约

**Files:**
- Modify: `src/scheduler/config.py`
- Modify: `config/runtime.json`
- Modify: `config/constraints.json`
- Modify: `config/logging.json`
- Delete: `config/replan.json`
- Modify: `tests/test_config_validation.py`
- Modify: `tests/test_pipeline_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_validation.py

def test_validate_config_rejects_removed_runtime_dynamic_weight_fields():
    cfg = load_config("config")
    assert "dynamic_weight_enable" not in cfg["runtime"]
    assert "thermal_weight_trigger_ratio" not in cfg["runtime"]
    assert "max_reweight_rounds" not in cfg["runtime"]


def test_validate_config_no_longer_requires_replan_section():
    cfg = load_config("config")
    cfg.pop("replan", None)
    validate_config(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_config_validation.py -k "removed_runtime_dynamic_weight_fields or no_longer_requires_replan" -v`
Expected: FAIL because旧字段/旧校验仍存在。

- [ ] **Step 3: Write minimal implementation**

```python
# src/scheduler/config.py
# remove reading and validation for:
# - runtime.python_path
# - runtime.dynamic_weight_enable
# - runtime.thermal_weight_trigger_ratio
# - runtime.max_reweight_rounds
# - runtime.solver_progress_enable
# - runtime.log_full_solution_content
# - constraints.attitude_power_reserve
# - constraints.thermal_capacity (legacy mapping)
# - constraints.thermal.payload_mix_factor
# - constraints.thermal.eclipse_factor
# - constraints.critical_payload_ids
# - constraints.payload_type_capacity
# - constraints.objective_profiles (动态配置删除后仅保留静态 objective_weights)
# remove required section: replan
```

```json
// config/runtime.json (after cleanup)
{
  "input_mode": "static",
  "data_dir": "data",
  "tasks_file": "small_tasks_pool_48_withoutAtt.json",
  "windows_file": "latest_windows.json",
  "seed": 666,
  "time_horizon": 240,
  "solver_timeout_sec": 60,
  "initial_attitude_angle_deg": 0,
  "thermal_time_step": 1,
  "initial_temperature_fallback": 25.0,
  "thermal_initial_source": "last_state_first",
  "replan_state_max_age_sec": 600,
  "heuristic_log_every_n": 10,
  "cpsat_log_every_n": 5,
  "solver_progress_every_n_solutions": 5
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_config_validation.py tests/test_pipeline_integration.py -v`
Expected: PASS and no dependency on removed config fields.

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/config.py config/runtime.json config/constraints.json config/logging.json config/replan.json tests/test_config_validation.py tests/test_pipeline_integration.py
git commit -m "清理无效配置字段并收敛配置契约，变更原因：避免配置膨胀与伪开关误导"
```

### Task 7: 为所有 JSON 配置文件输出注释文档

**Files:**
- Create: `docs/配置文件注释说明.md`
- Modify: `docs/地面站基线任务规划组件开发的初步计划.md`

- [ ] **Step 1: Write the failing test (doc contract)**

```python
# tests/test_pipeline_integration.py
from pathlib import Path


def test_config_comment_doc_covers_all_json_configs():
    text = Path("docs/配置文件注释说明.md").read_text(encoding="utf-8")
    assert "runtime.json" in text
    assert "constraints.json" in text
    assert "logging.json" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py::test_config_comment_doc_covers_all_json_configs -v`
Expected: FAIL because文档尚不存在。

- [ ] **Step 3: Write minimal implementation**

```markdown
# docs/配置文件注释说明.md

## runtime.json
| 字段 | 类型 | 单位 | 必填 | 默认值 | 作用 | 代码引用 |
|---|---|---|---|---|---|---|
| time_horizon | int | 秒 | 是 | 240 | 求解时域上界 | src/scheduler/pipeline.py |
| solver_timeout_sec | number | 秒 | 是 | 60 | CP-SAT 求解超时 | src/scheduler/cpsat_improver.py |
| thermal_time_step | number | 秒 | 是 | 1 | 热模型离散步长 | src/scheduler/thermal_model.py |

## constraints.json
| 字段 | 类型 | 单位 | 必填 | 默认值 | 作用 | 代码引用 |
|---|---|---|---|---|---|---|
| cpu_capacity | int | 核 | 是 | 4 | CPU 累积资源上限 | src/scheduler/cpsat_improver.py |
| gpu_capacity | int | 卡 | 是 | 2 | GPU 累积资源上限 | src/scheduler/cpsat_improver.py |
| thermal.warning_threshold | number | ℃ | 是 | 90 | 热预警阈值 | src/scheduler/constraint_value_engine.py |

## logging.json
| 字段 | 类型 | 单位 | 必填 | 默认值 | 作用 | 代码引用 |
|---|---|---|---|---|---|---|
| output_dir | string | 路径 | 否 | output | 主结果输出目录（由 CLI `--output-dir` 覆盖） | main.py |

## 变更历史
- 2026-03-30: 删除动态权重与 replan 相关配置。
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py::test_config_comment_doc_covers_all_json_configs -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add docs/配置文件注释说明.md docs/地面站基线任务规划组件开发的初步计划.md tests/test_pipeline_integration.py
git commit -m "新增配置注释文档，变更原因：提升配置可读性并避免无效字段回流"
```

### Task 8: 全量回归与端到端验收

**Files:**
- Modify: `output/` (仅运行产物，不纳入提交)

- [ ] **Step 1: Run focused regression suites**

Run: `cd .worktrees/ai-develop; pytest tests/test_constraint_value_engine.py tests/test_thermal_model.py tests/test_cpsat_improver.py tests/test_heuristic_scheduler.py tests/test_result_writer.py tests/test_config_validation.py -v`
Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `cd .worktrees/ai-develop; pytest tests/ -v`
Expected: PASS (0 failed).

- [ ] **Step 3: Run end-to-end planner**

Run: `cd .worktrees/ai-develop; E:/Softwares/miniconda3/python.exe main.py --config config --seed 666 --output-dir output`
Expected: Exit code 0，输出 `schedule_*.json`，`solver_summary` 仅含 `objective_breakdown`（不含 `objective_breakdown_raw`）。

- [ ] **Step 4: Verify schema contract by command line**

Run: 

```powershell
cd .worktrees/ai-develop
$f = Get-ChildItem output\schedule_*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$j = Get-Content $f.FullName -Raw | ConvertFrom-Json
$j.solver_summary.PSObject.Properties.Name
```

Expected: 不包含 `objective_breakdown_raw`、`weight_profile_history`、`active_weight_profile`、`switch_reason`。

- [ ] **Step 5: Commit (if any test/doc fixups were needed)**

```bash
cd .worktrees/ai-develop
git add tests docs src/scheduler
git commit -m "完成全量回归与契约验收，变更原因：确保约束解耦与配置清理后的稳定性"
```

---

## Plan Review Loop (Per Chunk)

对每个 `Chunk` 完成后执行：

1. 调用 plan-document-reviewer 子代理审阅当前 chunk 文本（仅传 chunk 内容与本计划路径）。
2. 若返回 ❌，立刻修复并重复审阅。
3. 同一 chunk 最多循环 5 次，超限升级人工决策。

## Done Criteria

- 热约束及热目标计算统一走 `thermal_model.py` 内核路径。
- 求解器中仅保留变量建模与线性约束拼装，不再内联通用约束值计算。
- 同姿态任务不插入 ATTITUDE 段，且资源允许时可并行。
- 动态权重策略及其配置完全移除。
- `ImproveResult` 与输出中不再包含 `objective_breakdown_raw`。
- `config` 目录无无效字段，且有完备注释文档。
- 全量测试 + 端到端运行通过。

Plan complete and saved to `docs/superpowers/plans/2026-03-30-solver-constraint-decoupling-and-thermal-unification-implementation-plan.md`. Ready to execute?