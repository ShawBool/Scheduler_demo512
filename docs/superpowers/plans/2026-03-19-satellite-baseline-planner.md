# Satellite Baseline Planner Implementation Plan / 卫星基线规划器实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.  
> **给智能体执行者：** 必须使用 `superpowers:subagent-driven-development`（若可用）或 `superpowers:executing-plans` 执行本计划，步骤采用 `- [ ]` 勾选语法追踪进度。

**Goal:** Build a runnable Python 3.12 ground baseline scheduler prototype that ingests unsorted tasks, enforces hard constraints, optimizes objective value, and outputs logs/tests for future onboard replanning data use.  
**目标：** 构建可运行的 Python 3.12 地面基线调度原型，读取无序任务池，满足硬约束并优化目标函数，同时输出可用于后续星上重规划与强化学习的数据日志与测试。

**Architecture:** Config-first modular pipeline: config schema → domain models (task/schedule/resource/link/safety) → realistic simulation → CP-SAT feasibility + optimization → schedule and cycle logs export. Hard constraints are mandatory; soft objective is weighted maximization over feasible solutions.  
**架构：** 配置优先的模块化流水线：配置模式 → 领域模型（任务/计划/资源/链路/安全）→ 真实感仿真 → CP-SAT 先可行后优化 → 计划与周期日志导出。硬约束必须满足，软目标在可行域内加权最大化。

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, pytest, dataclasses, json/jsonl logging  
**技术栈：** Python 3.12、OR-Tools CP-SAT、pytest、dataclasses、json/jsonl 日志

---

## Chunk 1: Structure, config schema, and front-loaded modeling / 结构、配置模式与前置建模

### Task 1: Create project skeleton and strict config schema / 创建工程骨架与严格配置模式

**Files:**
- Create: `src/scheduler/__init__.py`
- Create: `src/scheduler/config.py`
- Create: `config/planner_config.json`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing config schema test / 先写配置模式失败测试**

```python
from scheduler.config import load_config, validate_config


def test_config_contains_required_schema_sections():
    cfg = load_config("config/planner_config.json")
    validate_config(cfg)
    assert "runtime" in cfg
    assert "simulation" in cfg
    assert "constraints" in cfg
    assert "objective_weights" in cfg
    assert "logging" in cfg
```

- [ ] **Step 2: Run test to verify fail / 运行并确认失败**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_config.py -q`  
Expected: FAIL (`ImportError` or missing validator)

- [ ] **Step 3: Implement minimal loader + validator / 最小实现加载与校验**

Include:
- required keys
- key numeric ranges (`task_count_min<=task_count_max`, capacities > 0)
- default fallback for optional values

- [ ] **Step 4: Re-run test to pass / 复测通过**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_config.py -q`  
Expected: PASS

- [ ] **Step 5: Commit milestone / 里程碑提交**

```bash
git add config/planner_config.json src/scheduler/config.py src/scheduler/__init__.py tests/test_config.py
git commit -m "里程碑1：建立配置模式与校验，确保参数外置并降低硬编码风险"
```

### Task 2: Build full data models (with Chinese field annotations) / 构建完整数据模型（含中文字段注释）

**Files:**
- Create: `src/scheduler/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing model completeness test / 先写模型完整性失败测试**

Test must instantiate and validate these entities:
- `Task`（任务）
- `ResourceSnapshot`（资源快照）
- `LinkWindow`（通信窗口）
- `DangerRule`（危险组合规则）
- `ScheduleItem`（计划项）
- `ScheduleResult`（计划结果，含未规划任务池）

- [ ] **Step 2: Run test to fail / 运行并失败**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_models.py -q`  
Expected: FAIL

- [ ] **Step 3: Implement dataclasses with Chinese comments / 实现 dataclass 并添加中文注释**

`Task` fields include (with Chinese comments/docstrings):
- `task_id` 任务唯一标识
- `earliest_start` 最早开始时刻
- `latest_end` 最晚结束时刻
- `duration` 执行时长
- `value` 任务收益
- `cpu/gpu/memory/storage/bus/container_slots` 资源占用
- `power/thermal_load` 功率与热负载
- `payload_type_requirements/payload_id_requirements` 载荷类型/特定载荷约束
- `predecessors` 前置依赖
- `attitude_mode` 姿态模式
- `comm_kind` 任务通信类型
- `is_key_task` 是否关键任务（必须规划）

`ScheduleResult` includes:
- `scheduled_items`
- `unscheduled_tasks`（未规划任务池）
- `objective_value`
- `constraint_stats`

- [ ] **Step 4: Re-run model test / 复测模型测试**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_models.py -q`  
Expected: PASS

## Chunk 2: Simulation + CP-SAT planner + objective/log contracts / 仿真+规划+目标与日志契约

### Task 3: Implement realistic simulation generator / 实现真实感仿真生成器

**Files:**
- Create: `src/scheduler/simulation.py`
- Test: `tests/test_simulation.py`

- [ ] **Step 1: Write failing simulation tests / 先写仿真失败测试**

Tests verify:
- task count in [50, 100]
- DAG group count in [5, 10]
- no dependency cycle
- key task (`position_service`) exists and is marked key
- payload type/id constraints are populated
- resource/power/thermal values within config ranges

- [ ] **Step 2: Run tests to fail / 运行并失败**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_simulation.py -q`  
Expected: FAIL

- [ ] **Step 3: Implement generator / 实现生成器**

Create `generate_task_pool(config: dict, seed: int) -> list[Task]`:
- split tasks into 5-10 DAG groups
- synthesize different task categories (payload, compute, comm, service)
- ensure dependencies only point from earlier topo layer to later layer

- [ ] **Step 4: Re-run simulation tests / 复测仿真测试**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_simulation.py -q`  
Expected: PASS

### Task 4: Implement CP-SAT baseline planner with hard constraints / 实现含硬约束的 CP-SAT 基线规划器

**Files:**
- Create: `src/scheduler/planner.py`
- Test: `tests/test_planner_constraints.py`

- [ ] **Step 1: Write failing planner constraint tests / 先写约束失败测试**

Cover hard constraints:
- time window
- predecessor completion before successor start
- attitude switch time overhead
- CPU/GPU/memory/storage/bus/container concurrency limits
- communication window coverage for comm tasks
- power and thermal capacity
- danger-rule block (e.g., specific thermal+power+attitude combo forbidden)
- key tasks must be scheduled

- [ ] **Step 2: Write failing optimization/unscheduled tests / 先写优化与未规划池失败测试**

Cover:
- objective value improves versus naive feasible baseline
- infeasible tasks are retained in `unscheduled_tasks` instead of silently dropped

- [ ] **Step 3: Run tests to fail / 运行失败测试**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_planner_constraints.py -q`  
Expected: FAIL

- [ ] **Step 4: Implement minimal solver / 最小实现求解器**

Implement:
- schedule decision var + start/end vars
- optional interval style constraints
- resource limits via discretized capacity checks
- link window eligibility constraints
- weighted objective (`task_value` maximize, lateness penalize)
- explicit extraction of unscheduled tasks

- [ ] **Step 5: Re-run tests to pass / 复测通过**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_planner_constraints.py -q`  
Expected: PASS

### Task 5: Add cycle logger and pipeline entry / 增加周期日志与流水线入口

**Files:**
- Create: `src/scheduler/logging_utils.py`
- Create: `src/scheduler/pipeline.py`
- Create: `main.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing pipeline/log schema tests / 先写流水线日志契约失败测试**

Validate output contracts:
- `output/latest_schedule.json` has `scheduled_items`, `unscheduled_tasks`, `objective_value`, `constraint_stats`
- `output/cycle_log.jsonl` each line has `cycle_id`, `timestamp`, `state_snapshot`, `selected_tasks`, `unscheduled_tasks`, `constraint_violations`, `objective_value`

- [ ] **Step 2: Run tests to fail / 运行失败测试**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_pipeline.py -q`  
Expected: FAIL

- [ ] **Step 3: Implement pipeline and CLI / 实现流水线与命令行入口**

Run command:
`E:\\Softwares\\miniconda3\\python.exe main.py --seed 7`

- [ ] **Step 4: Re-run tests to pass / 复测通过**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest tests/test_pipeline.py -q`  
Expected: PASS

## Chunk 3: Verification, docs, and milestone commits / 验证、文档与里程碑提交

### Task 6: Full verification and smoke run / 全量验证与冒烟运行

**Files:**
- Create: `docs/运行说明.md`
- Test: `tests/*.py`

- [ ] **Step 1: Run full test suite / 运行全量测试**

Run: `E:\\Softwares\\miniconda3\\python.exe -m pytest -q`  
Expected: All tests PASS

- [ ] **Step 2: Run CLI smoke test / 运行命令行冒烟测试**

Run: `E:\\Softwares\\miniconda3\\python.exe main.py --seed 42`  
Expected: output files generated and schedule non-empty when feasible

- [ ] **Step 3: Verify hard constraints and key tasks in output / 验证输出中的硬约束与关键任务**

Run a small verification script or test to assert:
- key task present
- no precedence/time-window violations
- resource snapshots do not exceed capacities

### Task 7: Milestone commits and handoff / 里程碑提交与交付

**Files:**
- Modify: all planned artifacts only

- [ ] **Step 1: Commit implementation milestone / 提交实现里程碑**

```bash
git add src tests main.py config requirements.txt
git commit -m "里程碑2：实现基线规划与仿真日志，满足硬约束并沉淀可复用运行数据"
```

- [ ] **Step 2: Commit docs/verification milestone / 提交文档与验证里程碑**

```bash
git add docs/运行说明.md docs/superpowers/plans/2026-03-19-satellite-baseline-planner.md
git commit -m "里程碑3：补充运行说明与验证约束检查，提升复现性与交接效率"
```

- [ ] **Step 3: Prepare merge/cherry-pick commands / 准备 merge/cherry-pick 命令**

Record only (do not execute merge):
- `git checkout main`
- `git merge feature/ai-develop`
or
- `git cherry-pick <commit-sha-1> <commit-sha-2> <commit-sha-3>`

