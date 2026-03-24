# Shared Visibility Window Task Model Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.
> **给智能体执行者：** 必须使用 superpowers:subagent-driven-development（若可用）或 superpowers:executing-plans 执行本计划，步骤采用 `- [ ]` 勾选语法追踪。

**Goal:** Refactor simulation and planner so tasks are generated from a shared visibility-window pool, tasks no longer store earliest_start/latest_end, and unconstrained free tasks are represented by visibility_window=None.
**目标：** 重构仿真与求解链路：先生成可见窗口池，再由窗口派生任务，任务模型移除 earliest_start/latest_end，自由任务用 visibility_window=None 表示无时间约束。

**Architecture:** Keep solver generic by deriving time-domain constraints from visibility_window at planning time. Simulation becomes a three-phase generator: (1) window-pool generation over the full horizon, (2) dependent tasks attached to existing windows (multi-task shared windows), (3) free tasks without any window/time bounds. This is feasible and should not be rejected because CP-SAT can express both bounded and unbounded tasks with optional intervals.
**架构：** 保持求解器通用性，在求解时从 visibility_window 推导时间域。仿真改为三阶段：(1) 全周期窗口池生成，(2) 基于已有窗口生成依赖任务（支持多任务共享窗口），(3) 生成无窗口自由任务。该方案可行，不驳回。

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, pytest, dataclasses, json
**技术栈：** Python 3.12、OR-Tools CP-SAT、pytest、dataclasses、json

---

## Chunk 1: Model Contract and Config Baseline

### Task 1: Remove earliest_start/latest_end from Task model and lock new contract with tests

**Files:**
- Modify: `src/scheduler/models.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_logging_utils.py`

- [ ] **Step 1: Write failing tests for the new Task constructor contract**

```python
from scheduler.models import Task, VisibilityWindow


def test_task_without_time_fields_uses_visibility_window_only():
    task = Task(
        task_id="t1",
        duration=5,
        value=10,
        cpu=1,
        gpu=0,
        memory=2,
        storage=1,
        bus=1,
        concurrency_cores=1,
        power=1,
        thermal_load=1,
        payload_type_requirements=["camera"],
        payload_id_requirements=[],
        predecessors=[],
        attitude_angle_deg=30.0,
        is_key_task=False,
        visibility_window=VisibilityWindow("vw_1", 10, 40, "camera"),
    )
    assert task.visibility_window is not None


def test_free_task_can_have_no_visibility_window():
    task = Task(
        task_id="free_1",
        duration=4,
        value=8,
        cpu=1,
        gpu=0,
        memory=1,
        storage=1,
        bus=1,
        concurrency_cores=1,
        power=1,
        thermal_load=1,
        payload_type_requirements=[],
        payload_id_requirements=[],
        predecessors=[],
        attitude_angle_deg=0.0,
        is_key_task=False,
        visibility_window=None,
    )
    assert task.visibility_window is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_models.py tests/test_logging_utils.py -q`
Expected: FAIL with `TypeError` (missing/extra Task args due old signature).

- [ ] **Step 3: Implement minimal model changes**

```python
@dataclass(slots=True)
class Task:
    task_id: str
    duration: int
    value: int
    cpu: int
    gpu: int
    memory: int
    storage: int
    bus: int
    concurrency_cores: int
    power: int
    thermal_load: int
    payload_type_requirements: list[str] = field(default_factory=list)
    payload_id_requirements: list[str] = field(default_factory=list)
    predecessors: list[str] = field(default_factory=list)
    attitude_angle_deg: float = 0.0
    is_key_task: bool = False
    visibility_window: VisibilityWindow | None = None
```

- [ ] **Step 4: Re-run tests to verify pass**

Run: `python -m pytest tests/test_models.py tests/test_logging_utils.py -q`
Expected: PASS.

- [ ] **Step 5: Commit milestone**

```bash
git add src/scheduler/models.py tests/test_models.py tests/test_logging_utils.py
git commit -m "里程碑1：收敛任务时间语义到可见窗口，变更原因：消除双时间字段与窗口语义重复"
```

### Task 2: Extend simulation config for window-pool generation

**Files:**
- Modify: `config/simulation.json`
- Modify: `src/scheduler/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing config validation tests for new keys**

```python
def test_validate_config_rejects_invalid_visibility_window_ranges():
    cfg = _minimal_valid_cfg()
    cfg["simulation"]["visibility_window_count_min"] = 5
    cfg["simulation"]["visibility_window_count_max"] = 3
    with pytest.raises(ValueError, match="visibility_window_count_min must be <= visibility_window_count_max"):
        validate_config(cfg)
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL because validator does not check new window-pool keys.

- [ ] **Step 3: Implement minimal config support**

```python
_ensure_positive(sim.get("visibility_window_count_min"), "visibility_window_count_min")
_ensure_positive(sim.get("visibility_window_count_max"), "visibility_window_count_max")
if sim["visibility_window_count_min"] > sim["visibility_window_count_max"]:
    raise ValueError("visibility_window_count_min must be <= visibility_window_count_max")
```

Also add defaults in `config/simulation.json`:
- `visibility_window_count_min/max`
- `visibility_window_duration_min/max`
- `window_share_task_min/max`
- `free_task_ratio`

- [ ] **Step 4: Re-run test to verify pass**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit milestone**

```bash
git add config/simulation.json src/scheduler/config.py tests/test_config.py
git commit -m "里程碑2：补齐窗口池生成配置，变更原因：为共享可见窗口任务生成提供参数基线"
```

## Chunk 2: Simulation Refactor (Window Pool -> Window Tasks -> Free Tasks)

### Task 3: Generate visibility-window pool for the whole cycle and attach multiple tasks to each window

**Files:**
- Modify: `src/scheduler/simulation.py`
- Modify: `tests/test_simulation.py`

- [ ] **Step 1: Write failing tests for shared-window behavior and generation order**

```python
def test_simulation_generates_window_pool_before_tasks_and_reuses_windows():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=42)

    payload_tasks = [t for t in tasks if t.payload_type_requirements]
    assert payload_tasks

    shared = {}
    for t in payload_tasks:
        assert t.visibility_window is not None
        shared.setdefault(t.visibility_window.window_id, 0)
        shared[t.visibility_window.window_id] += 1

    assert any(cnt >= 2 for cnt in shared.values())
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_simulation.py::test_simulation_generates_window_pool_before_tasks_and_reuses_windows -q`
Expected: FAIL because current simulation mostly creates one window per task.

- [ ] **Step 3: Implement minimal window-pool-first generator**

```python
def _generate_visibility_windows(config: dict, rng: random.Random, horizon: int) -> list[VisibilityWindow]:
    # 先生成窗口池，供多个任务复用
    ...


def _sample_window_tasks(...):
    # 从已有窗口分配任务，允许多个任务共享同一窗口
    ...
```

Implementation rules:
- 先生成多个 `VisibilityWindow`（覆盖整个 horizon，含 camera/radar/relay 类型）。
- 再按窗口生成任务，并以 `window_id` 共享（同一窗口至少允许 2 个任务，比例可配置）。
- 依赖关系仅在窗口任务层构建，且保证 DAG 无环。
- 对共享同一窗口的依赖链（A -> B）增加可行性约束：`A.duration + B.duration <= window.end - window.start`。

- [ ] **Step 4: Re-run test to verify pass**

Run: `python -m pytest tests/test_simulation.py::test_simulation_generates_window_pool_before_tasks_and_reuses_windows -q`
Expected: PASS.

- [ ] **Step 5: Commit milestone**

```bash
git add src/scheduler/simulation.py tests/test_simulation.py
git commit -m "里程碑3：实现窗口池优先生成，变更原因：支持多任务共享同一可见窗口"
```

### Task 4: Add free tasks with no time/window constraints and adapt dependency feasibility checks

**Files:**
- Modify: `src/scheduler/simulation.py`
- Modify: `tests/test_simulation.py`

- [ ] **Step 1: Write failing tests for free-task semantics**

```python
def test_free_tasks_have_no_window_and_no_explicit_time_bounds():
    cfg = load_config("config")
    tasks = generate_task_pool(cfg, seed=99)
    free_tasks = [t for t in tasks if t.task_id.startswith("flex_")]
    assert free_tasks
    assert all(t.visibility_window is None for t in free_tasks)
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_simulation.py::test_free_tasks_have_no_window_and_no_explicit_time_bounds -q`
Expected: FAIL because current flex tasks may still carry horizon-derived temporal semantics.

- [ ] **Step 3: Implement minimal free-task generation update**

```python
free_task = Task(
    task_id=tid,
    duration=duration,
    value=value,
    cpu=cpu,
    gpu=gpu,
    memory=memory,
    storage=storage,
    bus=bus,
    concurrency_cores=cores,
    power=power,
    thermal_load=thermal,
    payload_type_requirements=[],
    payload_id_requirements=[],
    predecessors=predecessors,
    attitude_angle_deg=angle,
    is_key_task=False,
    visibility_window=None,
)
```

Dependency feasibility rule update:
- 不再依赖 `pred.latest_end` / `succ.earliest_start`。
- 改为使用窗口可行域推导：若前后任务均有窗口，则保证存在 `pred_start + pred.duration <= succ_start` 的可行区间；若任一方无窗口，则按 `[0, horizon]` 处理。

- [ ] **Step 4: Re-run simulation suite**

Run: `python -m pytest tests/test_simulation.py -q`
Expected: PASS.

- [ ] **Step 5: Commit milestone**

```bash
git add src/scheduler/simulation.py tests/test_simulation.py
git commit -m "里程碑4：引入自由任务无窗口语义，变更原因：明确无约束任务并简化时间语义"
```

## Chunk 3: Planner and End-to-End Adaptation

### Task 5: Planner derives time bounds only from visibility_window (or full horizon when None)

**Files:**
- Modify: `src/scheduler/planner.py`
- Modify: `tests/test_planner_constraints.py`

- [ ] **Step 1: Write failing planner tests for window-derived constraints**

```python
def test_planner_respects_visibility_window_if_present():
    cfg = _base_config()
    task = Task(
        "w1", 4, 10, 1, 0, 1, 1, 1, 1, 1, 1,
        ["camera"], ["P1"], [], 0.0, False,
        VisibilityWindow("vw1", 10, 20, "camera"),
    )
    result = plan_baseline([task], cfg)
    item = next(i for i in result.scheduled_items if i.task_id == "w1")
    assert 10 <= item.start
    assert item.end <= 20


def test_planner_treats_none_window_as_full_horizon():
    cfg = _base_config()
    task = Task("free", 4, 10, 1, 0, 1, 1, 1, 1, 1, 1, [], [], [], 0.0, False, None)
    result = plan_baseline([task], cfg)
    assert any(i.task_id == "free" for i in result.scheduled_items)
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_planner_constraints.py -q`
Expected: FAIL due planner still reading removed fields.

- [ ] **Step 3: Implement minimal planner adaptation**

```python
def _task_time_domain(task: Task, horizon: int, time_step: int) -> tuple[int, int]:
    if task.visibility_window is None:
        return 0, horizon
    return max(0, task.visibility_window.start), min(horizon, task.visibility_window.end)
```

Use this helper for:
- `start/end` variable domains
- infeasible-window pruning (`window_end - window_start < duration`)
- lateness penalty baseline (use window start or 0)
- rolling segment boundaries (`key_task` / DAG source with window start else 0)

- [ ] **Step 4: Re-run planner tests**

Run: `python -m pytest tests/test_planner_constraints.py tests/test_planner_typing_guard.py -q`
Expected: PASS.

- [ ] **Step 5: Commit milestone**

```bash
git add src/scheduler/planner.py tests/test_planner_constraints.py tests/test_planner_typing_guard.py
git commit -m "里程碑5：求解器改为窗口驱动时间域，变更原因：兼容共享窗口与无窗口自由任务"
```

### Task 6: Update cross-module tests and run full verification

**Files:**
- Modify: `src/scheduler/pipeline.py` (verify no hidden dependency on removed fields)
- Modify: `main.py` (verify CLI path does not construct old Task signature)
- Modify: `tests/test_pipeline.py` (if needed for contract assertions)
- Modify: `tests/test_logging_utils.py` (Task constructor updates)
- Modify: `tests/test_models.py`
- Modify: `docs/运行说明.md`

- [ ] **Step 1: Add/adjust end-to-end assertions for new task schema**

```python
def test_task_pool_payload_tasks_have_window_or_free_task_has_none():
    payload = json.loads(task_pool_path.read_text(encoding="utf-8"))
    for t in payload["tasks"]:
        if t["payload_type_requirements"]:
            assert t["visibility_window"] is not None
        else:
            assert t["visibility_window"] is None
```

- [ ] **Step 1.5: Audit pipeline and CLI integration points**

Run:
- `python -m pytest tests/test_pipeline.py -q`
- `python main.py --seed 7`

Expected:
- no `TypeError` related to old `Task(earliest_start/latest_end, ...)` signature.
- pipeline output schema remains backward-compatible except the two removed task fields.

- [ ] **Step 2: Run full tests to verify failures are resolved**

Run: `python -m pytest -q`
Expected: PASS (all existing and new tests pass).

- [ ] **Step 3: Run pipeline smoke test**

Run: `python main.py --seed 42`
Expected:
- 输出 `output/latest_task_pool.json` 中任务不含 `earliest_start/latest_end` 字段。
- 存在多个 payload 任务共享同一个 `visibility_window.window_id`。
- 自由任务 `visibility_window` 为 `null`。

- [ ] **Step 4: Update run doc with new semantics**

Document in `docs/运行说明.md`:
- “窗口任务”与“自由任务”定义
- 可见窗口共享机制
- 无窗口任务在求解器中默认时间域 `[0, time_horizon]`

- [ ] **Step 5: Commit milestone**

```bash
git add tests docs/运行说明.md
git commit -m "里程碑6：完成联调验证与文档更新，变更原因：确保新任务语义可测试可运行"
```

## Execution Notes

- 该改造不是独立子系统拆分需求，属于同一调度域模型到仿真和求解链路的纵向重构，单一计划即可闭环。
- 严格执行 TDD：每个任务先失败测试，再最小实现，再回归。
- 遵循约束放置原则：任务可行性塑形优先在仿真侧完成，求解器只做通用约束表达。
- 所有提交在 `feature/ai-develop` 分支完成，不在主工作目录直接改动。
