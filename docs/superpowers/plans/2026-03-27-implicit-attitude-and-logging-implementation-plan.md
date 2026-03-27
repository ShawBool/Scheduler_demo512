# 隐式姿态约束与日志增强 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将调度器从“显式 ATT 输入/建模”迁移到“启发式与 CP-SAT 统一隐式姿态约束 + 输出后物化 ATT”，并补齐阶段化日志与全量解日志。

**Architecture:** 在 `heuristic_scheduler` 与 `cpsat_improver` 内部统一采用姿态状态机/转姿时间约束，不在求解阶段动态增删 ATT 任务变量；在 `result_writer` 中基于最终序列回放并物化 ATT 记录。配置由 `runtime.json` 与 `constraints.json` 增强后统一在 `config.py` 校验，`pipeline.py` 负责跨阶段日志聚合与事件化写出。

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, pytest, JSON/JSONL 日志

---

## 变更文件结构（先读）

- Modify: `src/scheduler/config.py`
  - 职责：新增与校验 `initial_attitude_angle_deg`、`heuristic_log_every_n`、`cpsat_log_every_n`、`log_full_solution_content`、`attitude_power_reserve`。
- Modify: `src/scheduler/heuristic_scheduler.py`
  - 职责：移除显式 ATT 插入逻辑，改为隐式姿态状态机可行性检查；输出 `heuristic_initial_solution` / `heuristic_final_solution`。
- Modify: `src/scheduler/cpsat_improver.py`
  - 职责：增加隐式转姿约束（含初始姿态约束、候选任务对剪枝与功率保留量约束）；按 `cpsat_log_every_n` 输出摘要。
- Modify: `src/scheduler/result_writer.py`
  - 职责：新增“输出后物化 ATT”函数；支持 `solver_progress.jsonl` 事件化 schema。
- Modify: `src/scheduler/pipeline.py`
  - 职责：整合启发式/CPSAT日志事件，控制终态 `terminal` 写出，串联 ATT 物化。
- Modify: `src/scheduler/models.py`（仅在必要时）
  - 职责：补充日志事件模型或输出结构字段。
- Test: `tests/test_heuristic_scheduler.py`
- Test: `tests/test_cpsat_improver.py`
- Test: `tests/test_result_writer.py`
- Test: `tests/test_pipeline_integration.py`
- Test: `tests/test_data_loader_static.py`（必要时）

---

## Chunk 1: 配置与日志契约落地

### Task 1: 扩展运行时配置模型与校验

**Files:**
- Modify: `src/scheduler/config.py`
- Test: `tests/test_data_loader_static.py`

- [ ] **Step 1: 写失败测试（新增配置字段缺失/越界）**

```python

def test_runtime_requires_initial_attitude_angle_deg(runtime_cfg_factory):
    cfg = runtime_cfg_factory()
    del cfg["initial_attitude_angle_deg"]
    with pytest.raises(ValueError):
        load_runtime_config(cfg)


def test_initial_attitude_angle_deg_range(runtime_cfg_factory):
    cfg = runtime_cfg_factory(initial_attitude_angle_deg=361)
    with pytest.raises(ValueError):
        load_runtime_config(cfg)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_data_loader_static.py -k "initial_attitude or heuristic_log_every_n or cpsat_log_every_n" -v`
Expected: FAIL（字段不存在或未校验）

- [ ] **Step 3: 最小实现配置字段与校验**

```python
# config.py 伪代码要点
initial = runtime["initial_attitude_angle_deg"]
if not (0 <= initial <= 360):
    raise ValueError("initial_attitude_angle_deg out of range")
heuristic_log_every_n = int(runtime.get("heuristic_log_every_n", 10))
cpsat_log_every_n = int(runtime.get("cpsat_log_every_n", 10))
if heuristic_log_every_n < 1 or cpsat_log_every_n < 1:
    raise ValueError("log_every_n must be >= 1")
log_full_solution_content = bool(runtime.get("log_full_solution_content", True))
attitude_power_reserve = float(constraints.get("attitude_power_reserve", 0.0))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_data_loader_static.py -k "initial_attitude or heuristic_log_every_n or cpsat_log_every_n" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/config.py tests/test_data_loader_static.py
git commit -m "完善配置校验，原因：支持隐式姿态与分阶段日志参数"
```

### Task 2: 统一 solver_progress 事件化 schema

**Files:**
- Modify: `src/scheduler/result_writer.py`
- Modify: `src/scheduler/models.py`（如已有日志事件类型则仅增量）
- Test: `tests/test_result_writer.py`

- [ ] **Step 1: 写失败测试（不同 event_type 不同 payload）**

```python

def test_progress_event_schema_supports_metrics_and_solution(tmp_path):
    write_progress_event(tmp_path, {
        "event_type": "heuristic_iteration_summary",
        "phase": "heuristic",
        "metrics": {"score": 10}
    })
    write_progress_event(tmp_path, {
        "event_type": "heuristic_initial_solution",
        "phase": "heuristic",
        "solution": {"items": []}
    })
    rows = read_jsonl(tmp_path)
    assert "metrics" in rows[0]
    assert "solution" in rows[1]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_result_writer.py -k "event_schema or progress" -v`
Expected: FAIL

- [ ] **Step 3: 实现事件化 schema 写入**

```python
# result_writer.py 伪代码要点
base = {"timestamp": now, "event_type": event_type, "phase": phase, "iteration": iteration}
if "metrics" in payload:
    base["metrics"] = payload["metrics"]
if "solution" in payload:
    base["solution"] = payload["solution"]
append_jsonl(base)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_result_writer.py -k "event_schema or progress" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/result_writer.py src/scheduler/models.py tests/test_result_writer.py
git commit -m "统一进度日志契约，原因：支持摘要与全量解并存"
```

---

## Chunk 2: 启发式与 CP-SAT 隐式姿态约束

### Task 3: 启发式改为隐式姿态状态机

**Files:**
- Modify: `src/scheduler/heuristic_scheduler.py`
- Test: `tests/test_heuristic_scheduler.py`

- [ ] **Step 1: 写失败测试（姿态变化可行性）**

```python

def test_heuristic_respects_attitude_transition_time(problem_fixture):
    result = build_initial_schedule(problem_fixture)
    assert all_transition_time_feasible(result.items)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "attitude_transition or implicit" -v`
Expected: FAIL

- [ ] **Step 3: 实现最小隐式姿态状态机**

```python
# heuristic_scheduler.py 伪代码要点
delta = min(abs(current_att - target_att), 360 - abs(current_att - target_att))
transition = math.ceil(delta / rate) + buffer
candidate_start = max(window_start, now + transition)
# 可行才接受；接受后更新 current_att
# 无姿态任务不更新 current_att（姿态透传）
```

- [ ] **Step 4: 写并通过日志全量解测试**

```python

def test_heuristic_emits_initial_and_final_solution_events(progress_rows):
    event_types = [r["event_type"] for r in progress_rows]
    assert "heuristic_initial_solution" in event_types
    assert "heuristic_final_solution" in event_types
```

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "initial_solution or final_solution or attitude_transition" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/heuristic_scheduler.py tests/test_heuristic_scheduler.py
git commit -m "改造启发式姿态建模，原因：改为隐式转姿并补充全量解日志"
```

### Task 4: CP-SAT 增加隐式转姿约束与剪枝

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Test: `tests/test_cpsat_improver.py`

- [ ] **Step 1: 写失败测试（顺序变化后仍满足转姿约束）**

```python

def test_cpsat_solution_respects_transition_after_reorder(problem_fixture):
    improved = improve_schedule(problem_fixture)
    assert all_transition_time_feasible(improved.items)


def test_cpsat_respects_initial_attitude_for_first_task(problem_fixture):
    problem_fixture.runtime.initial_attitude_angle_deg = 180
    improved = improve_schedule(problem_fixture)
    assert first_task_respects_initial_transition(improved.items, 180)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "transition or reorder or initial_attitude" -v`
Expected: FAIL

- [ ] **Step 3: 实现最小约束（含初始姿态、剪枝、功率保留）**

```python
# cpsat_improver.py 伪代码要点
def _get_candidate_pairs(tasks, windows):
    # 仅保留窗口可重叠/可串接且存在姿态竞争的任务对
    # 预过滤掉硬时间窗下不可达的任务对
    return filtered_pairs


for (i, j) in _get_candidate_pairs(tasks, windows):
    tij = transition_time(i, j)
    # y_ij = 1 -> j after i + tij
    model.Add(start[j] >= end[i] + tij).OnlyEnforceIf(y_ij)
# 首任务约束：from initial_attitude_angle_deg
# 功率预留：attitude_power_reserve 并入与任务同一套全局功率约束
# (转姿区间保留量 + 并行任务功率) <= power_capacity
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "transition or reorder or initial_attitude" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py tests/test_cpsat_improver.py
git commit -m "增强CP-SAT转姿约束，原因：顺序变动下保持姿态可行性与资源可行性"
```

---

## Chunk 3: 输出物化 ATT 与端到端回归

### Task 5: 在结果输出层物化 ATT（紧邻绑定）

**Files:**
- Modify: `src/scheduler/result_writer.py`
- Test: `tests/test_result_writer.py`

- [ ] **Step 1: 写失败测试（最终序列物化 ATT）**

```python

def test_materialize_att_before_attitude_tasks(final_schedule):
    materialized = materialize_att_segments(final_schedule)
    assert att_is_adjacent_to_target_task(materialized)
    assert has_leading_att_for_first_task(materialized)
    assert all(item["item_type"] in {"BUSINESS", "ATTITUDE"} for item in materialized)
    assert resource_feasible_after_materialization(materialized)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_result_writer.py -k "materialize_att or adjacent" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现 ATT 物化**

```python
# result_writer.py 伪代码要点
for task in ordered_tasks:
    if task.has_attitude_target:
        append(att_segment(task_prev_att, task.target_att, item_type="ATTITUDE"))
    append(task)

# 首任务也需要从 initial_attitude_angle_deg 到首任务姿态的 ATT 段
# 长空隙场景下，ATT 段贴近目标任务开始时刻，不强制贴近前一任务结束时刻
# 物化后执行一次资源复核，确保不会突破 power_capacity
validate_resource_after_materialization(materialized_items)
# 若资源复核失败，抛出 ResourceConstraintError（不静默降级）

# 函数签名需要显式注入 runtime_config/constraints，避免 result_writer 内部读取全局状态
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_result_writer.py -k "materialize_att or adjacent" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/result_writer.py tests/test_result_writer.py
git commit -m "新增ATT输出物化，原因：保留最终计划可解释性"
```

### Task 6: pipeline 集成与端到端验证

**Files:**
- Modify: `src/scheduler/pipeline.py`
- Test: `tests/test_pipeline_integration.py`

- [ ] **Step 1: 写失败测试（日志 + 终态 + 物化ATT）**

```python

def test_pipeline_outputs_required_progress_and_materialized_att(tmp_path):
    result = run_static_pipeline(...)
    rows = read_progress_jsonl(tmp_path)
    assert any(r["event_type"] == "heuristic_initial_solution" for r in rows)
    assert any(r["event_type"] == "heuristic_final_solution" for r in rows)
    assert any(r["event_type"] == "terminal" for r in rows)
    assert schedule_has_materialized_att(result)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "progress or terminal or materialized_att" -v`
Expected: FAIL

- [ ] **Step 3: 实现最小集成逻辑**

```python
# pipeline.py 伪代码要点
heuristic_result = run_heuristic(...)
emit(heuristic_initial_solution)
emit(heuristic_iteration_summary)
emit(heuristic_final_solution)
cp_result = improve_with_cpsat(...)
emit(cpsat_iteration_summary)
final_schedule = materialize_att(cp_result)
emit(terminal)
```

- [ ] **Step 4: 跑针对性测试 + 全量回归**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "progress or terminal or materialized_att" -v`
Expected: PASS

Run: `cd .worktrees/ai-develop; pytest tests -v`
Expected: 全绿（全部 PASS）

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/pipeline.py tests/test_pipeline_integration.py
git commit -m "完成隐式姿态端到端集成，原因：打通求解与日志输出链路"
```

---

## 交付检查清单

- [ ] `docs/superpowers/specs/2026-03-27-implicit-attitude-and-logging-design.md` 中的验收标准全部映射到测试。
- [ ] `solver_progress.jsonl` 同时存在摘要事件和全量解事件，并可按 `event_type` 正确解析。
- [ ] 最终排程输出中 ATT 记录与业务任务保持紧邻绑定。
- [ ] 关键任务完成率优先级未被收益优化覆盖。

## 实施备注（避免返工）

- 不要在 CP-SAT 单轮求解内做动态增删任务变量。
- 不要恢复对输入 `_att` 任务的硬依赖。
- 不要把 ATT 物化前置到求解阶段。
- 若出现建模规模超时，优先加强候选任务对剪枝，而非放松硬约束。
