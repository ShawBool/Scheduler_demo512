# Static Baseline Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a clean, test-driven static baseline scheduler from scratch on feature/ai-develop, using heuristic warm-start + CP-SAT improvement with mandatory iteration observability.

**Architecture:** The pipeline is rebuilt around focused units: input validation, problem building, heuristic initial schedule, CP-SAT bounded improvement, and standardized result/log writing. Hard constraints are split between pre-validation and solver layers without duplicate encoding. Delivery is milestone-based with small TDD tasks and frequent commits.

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, pytest, JSON/JSONL outputs.

---

## Scope Check

This plan targets one subsystem only: static baseline planning. Replan runtime logic remains out of scope; only a reserved interface is included.

## File Structure Map

### Core files

- Modify: src/scheduler/models.py
  - Responsibility: domain models aligned to current static data schema.
- Create: src/scheduler/errors.py
  - Responsibility: explicit input/planning/system exception classes.
- Create: src/scheduler/problem_builder.py
  - Responsibility: build dependency graph, execution domains, attitude transition matrix, solver-ready problem object.
- Create: src/scheduler/heuristic_scheduler.py
  - Responsibility: fast feasible warm-start with key-task priority.
- Create: src/scheduler/cpsat_improver.py
  - Responsibility: bounded CP-SAT optimization and iteration-summary callbacks.
- Create: src/scheduler/result_writer.py
  - Responsibility: write schedule result + unscheduled reasons + metrics + jsonl iteration logs.
- Create: src/scheduler/pipeline.py
  - Responsibility: orchestration for input -> preprocess -> heuristic -> CP-SAT -> output.
- Create: src/scheduler/replan_interface.py
  - Responsibility: reserved interface/data contracts for future replan.

### Existing adapters/entry files

- Modify: src/scheduler/data_loader.py
  - Responsibility: strict static data loading and normalization for models.
- Modify: src/scheduler/config.py
  - Responsibility: runtime/logging knobs used by new pipeline only.
- Modify: src/scheduler/__init__.py
  - Responsibility: export only rebuilt interfaces.
- Modify: main.py
  - Responsibility: call new pipeline and print execution summary.

### Tests

- Create: tests/test_models_contract.py
- Create: tests/test_data_loader_static.py
- Create: tests/test_problem_builder.py
- Create: tests/test_heuristic_scheduler.py
- Create: tests/test_cpsat_improver.py
- Create: tests/test_result_writer.py
- Create: tests/test_pipeline_integration.py

### Docs

- Modify: docs/地面站基线任务规划组件开发的初步计划.md
  - Responsibility: sync algorithm choice, logging contract, and one-phase scope.

---

## Chunk 1: Contracts And Preprocessing

### Task 1: Lock model and schema contracts

**Files:**
- Modify: src/scheduler/models.py
- Test: tests/test_models_contract.py

- [ ] **Step 1: Write the failing test for task schema compatibility**

```python
from scheduler.models import Task


def test_task_accepts_current_static_fields():
    task = Task(
        task_id="t1",
        duration=3,
        value=10,
        cpu=1,
        gpu=0,
        memory=2,
        power=1,
        thermal_load=1,
        payload_type_requirements=["camera"],
        predecessors=[],
        attitude_angle_deg=None,
        is_key_task=False,
        visibility_window=None,
    )
    assert task.thermal_load == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: pytest tests/test_models_contract.py::test_task_accepts_current_static_fields -v  
Expected: FAIL due to missing/invalid field mapping in model.

- [ ] **Step 3: Implement minimal model alignment**

```python
@dataclass(slots=True)
class Task:
    ...
    thermal_load: int
    attitude_angle_deg: float | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: pytest tests/test_models_contract.py::test_task_accepts_current_static_fields -v  
Expected: PASS.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/models.py tests/test_models_contract.py
git commit -m "里程碑M1: 对齐任务模型字段契约，变更原因：匹配静态任务池schema并消除加载歧义"
```

### Task 2: Rebuild static data loader with strict validation

**Files:**
- Modify: src/scheduler/data_loader.py
- Create: src/scheduler/errors.py
- Test: tests/test_data_loader_static.py

- [ ] **Step 1: Write failing tests for validation paths**

```python
import pytest
from scheduler.data_loader import load_static_task_bundle


def test_loader_rejects_unknown_visibility_window(tmp_path):
    cfg = {"runtime": {"static_tasks_file": str(tmp_path / "t.json"), "static_windows_file": str(tmp_path / "w.json")}}
    # Build minimal invalid files in test fixture helpers.
    with pytest.raises(ValueError, match="unknown visibility_window"):
        load_static_task_bundle(cfg)
```

- [ ] **Step 2: Run tests to verify failures**

Run: pytest tests/test_data_loader_static.py -v  
Expected: FAIL for missing strict validation and/or normalization behavior.

- [ ] **Step 3: Implement strict loader behavior**

```python
def load_static_task_bundle(cfg):
    windows = _load_windows(...)
    tasks = _load_tasks(...)
    _validate_references(tasks, windows)
    return tasks, windows, meta
```

- [ ] **Step 4: Run tests to verify pass**

Run: pytest tests/test_data_loader_static.py -v  
Expected: PASS for valid/invalid scenarios.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/data_loader.py src/scheduler/errors.py tests/test_data_loader_static.py
git commit -m "里程碑M1: 重建静态数据加载与校验，变更原因：前置输入约束并提升失败可诊断性"
```

### Task 3: Build problem builder unit

**Files:**
- Create: src/scheduler/problem_builder.py
- Test: tests/test_problem_builder.py

- [ ] **Step 1: Write failing tests for dependency DAG and attitude matrix**

```python
from scheduler.problem_builder import build_problem


def test_build_problem_computes_topological_order(sample_tasks, sample_windows):
    problem = build_problem(sample_tasks, sample_windows, horizon=240)
    assert problem.topological_tasks[0].endswith("_att")
```

- [ ] **Step 2: Run tests to verify fail**

Run: pytest tests/test_problem_builder.py -v  
Expected: FAIL because builder is not implemented.

- [ ] **Step 3: Implement minimal problem builder**

```python
def build_problem(tasks, windows, horizon):
    graph = _build_graph(tasks)
    topo = _topological_sort(graph)
    transitions = _compute_attitude_transition(tasks)
    return ProblemInstance(...)
```

- [ ] **Step 4: Run tests to verify pass**

Run: pytest tests/test_problem_builder.py -v  
Expected: PASS with deterministic outputs.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/problem_builder.py tests/test_problem_builder.py
git commit -m "里程碑M2: 新增问题构建器，变更原因：统一启发式与CP-SAT输入并固化约束边界"
```

### Task 4: Wire entry surface for rebuilt modules

**Files:**
- Modify: src/scheduler/__init__.py
- Modify: main.py
- Test: tests/test_pipeline_integration.py

- [ ] **Step 1: Write failing smoke test for main entry import path**

```python
def test_main_uses_scheduler_pipeline_module():
    import main
    assert hasattr(main, "main")
```

- [ ] **Step 2: Run test to verify fail**

Run: pytest tests/test_pipeline_integration.py::test_main_uses_scheduler_pipeline_module -v  
Expected: FAIL if legacy imports still break.

- [ ] **Step 3: Apply minimal wiring for new exports only**

```python
__all__ = [
    "Task",
    "VisibilityWindow",
    "load_static_task_bundle",
]
```

- [ ] **Step 4: Run smoke tests**

Run: pytest tests/test_pipeline_integration.py::test_main_uses_scheduler_pipeline_module -v  
Expected: PASS.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/__init__.py main.py tests/test_pipeline_integration.py
git commit -m "里程碑M2: 收敛入口与导出面，变更原因：隔离旧实现并确保新链路可加载"
```

---

## Chunk 2: Heuristic, Output Contract, And Observability

### Task 5: Implement heuristic warm-start scheduler

**Files:**
- Create: src/scheduler/heuristic_scheduler.py
- Test: tests/test_heuristic_scheduler.py

- [ ] **Step 1: Write failing tests for key-task-first behavior**

```python
from scheduler.heuristic_scheduler import build_initial_schedule


def test_heuristic_prioritizes_key_tasks(sample_problem):
    result = build_initial_schedule(sample_problem, seed=666)
    assert result.key_task_scheduled_count >= 1
```

- [ ] **Step 2: Run test to verify fail**

Run: pytest tests/test_heuristic_scheduler.py::test_heuristic_prioritizes_key_tasks -v  
Expected: FAIL before implementation.

- [ ] **Step 3: Implement minimal heuristic scheduler**

```python
def build_initial_schedule(problem, seed):
    ordered = sort_by_priority(problem.tasks)
    return schedule_greedily(ordered, constraints=problem.constraints)
```

- [ ] **Step 4: Run tests to verify pass**

Run: pytest tests/test_heuristic_scheduler.py -v  
Expected: PASS with deterministic output under fixed seed.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/heuristic_scheduler.py tests/test_heuristic_scheduler.py
git commit -m "里程碑M3: 实现启发式初解，变更原因：先保底可行再进入优化"
```

### Task 6: Implement standardized result and log writer

**Files:**
- Create: src/scheduler/result_writer.py
- Test: tests/test_result_writer.py

- [ ] **Step 1: Write failing tests for output schema and pre-created log file**

```python
from pathlib import Path
from scheduler.result_writer import initialize_iteration_log


def test_iteration_log_file_created_before_solver(tmp_path: Path):
    log_path = tmp_path / "solver_progress.jsonl"
    initialize_iteration_log(log_path)
    assert log_path.exists()
```

- [ ] **Step 2: Run test to verify fail**

Run: pytest tests/test_result_writer.py::test_iteration_log_file_created_before_solver -v  
Expected: FAIL before writer implementation.

- [ ] **Step 3: Implement writer functions**

```python
def initialize_iteration_log(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify pass**

Run: pytest tests/test_result_writer.py -v  
Expected: PASS including final-state summary record check.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/result_writer.py tests/test_result_writer.py
git commit -m "里程碑M4: 实现输出与迭代日志契约，变更原因：满足每10代摘要与终态可观测性"
```

### Task 7: Define reserved replan interface only

**Files:**
- Create: src/scheduler/replan_interface.py
- Test: tests/test_pipeline_integration.py

- [ ] **Step 1: Write failing test for reserved API contract presence**

```python
from scheduler.replan_interface import ReplanRequest, ReplanResponse


def test_replan_contract_types_exist():
    assert ReplanRequest is not None
    assert ReplanResponse is not None
```

- [ ] **Step 2: Run test to verify fail**

Run: pytest tests/test_pipeline_integration.py::test_replan_contract_types_exist -v  
Expected: FAIL before file exists.

- [ ] **Step 3: Implement minimal reserved contract**

```python
@dataclass
class ReplanRequest:
    reason: str
```

- [ ] **Step 4: Run test to verify pass**

Run: pytest tests/test_pipeline_integration.py::test_replan_contract_types_exist -v  
Expected: PASS.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/replan_interface.py tests/test_pipeline_integration.py
git commit -m "里程碑M4: 预留重规划接口契约，变更原因：保持一期边界同时支撑后续扩展"
```

---

## Chunk 3: CP-SAT Improvement, Pipeline Integration, And Final Verification

### Task 8: Implement CP-SAT improver with iteration summaries

**Files:**
- Create: src/scheduler/cpsat_improver.py
- Test: tests/test_cpsat_improver.py

- [ ] **Step 1: Write failing tests for every-10-iteration logging behavior**

```python
from scheduler.cpsat_improver import improve_schedule


def test_improver_emits_periodic_iteration_summary(sample_problem, tmp_path):
    result = improve_schedule(sample_problem, warm_start=None, log_path=tmp_path / "solver_progress.jsonl", progress_every_n=10)
    assert result.iteration_log_count >= 1
```

- [ ] **Step 2: Run tests to verify fail**

Run: pytest tests/test_cpsat_improver.py::test_improver_emits_periodic_iteration_summary -v  
Expected: FAIL before callback and writer wiring.

- [ ] **Step 3: Implement CP-SAT bounded improver**

```python
def improve_schedule(problem, warm_start, log_path, progress_every_n):
    model = build_cp_model(problem)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = problem.timeout_sec
    # callback writes summary every progress_every_n improvements
    return solve_with_callback(...)
```

- [ ] **Step 4: Run tests to verify pass**

Run: pytest tests/test_cpsat_improver.py -v  
Expected: PASS with periodic and terminal summary assertions.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/cpsat_improver.py tests/test_cpsat_improver.py
git commit -m "里程碑M4: 接入CP-SAT限时改进，变更原因：在可行初解基础上提升解质量并输出迭代摘要"
```

### Task 9: Implement end-to-end pipeline orchestration

**Files:**
- Create: src/scheduler/pipeline.py
- Modify: src/scheduler/config.py
- Modify: src/scheduler/__init__.py
- Test: tests/test_pipeline_integration.py

- [ ] **Step 1: Write failing integration test for static end-to-end run**

```python
from scheduler.pipeline import run_pipeline


def test_pipeline_returns_schedule_and_unscheduled_sections(tmp_path):
    result = run_pipeline("config", seed=666, output_dir=str(tmp_path))
    assert "schedule" in result
    assert "unscheduled" in result
```

- [ ] **Step 2: Run test to verify fail**

Run: pytest tests/test_pipeline_integration.py::test_pipeline_returns_schedule_and_unscheduled_sections -v  
Expected: FAIL before orchestration exists.

- [ ] **Step 3: Implement minimal orchestration path**

```python
def run_pipeline(config_path, seed, output_dir):
    cfg = load_config(config_path)
    tasks, windows, _ = load_static_task_bundle(cfg)
    problem = build_problem(tasks, windows, cfg["runtime"]["time_horizon"])
    initial = build_initial_schedule(problem, seed)
    improved = improve_schedule(problem, initial, ...)
    return write_outputs(improved, output_dir, ...)
```

- [ ] **Step 4: Run integration tests to verify pass**

Run: pytest tests/test_pipeline_integration.py -v  
Expected: PASS with reproducible metrics and generated output files.

- [ ] **Step 5: Commit**

Run:
```bash
git add src/scheduler/pipeline.py src/scheduler/config.py src/scheduler/__init__.py tests/test_pipeline_integration.py
git commit -m "里程碑M5: 打通静态规划全链路，变更原因：交付可运行且可诊断的一期基线能力"
```

### Task 10: Sync docs and run full verification

**Files:**
- Modify: docs/地面站基线任务规划组件开发的初步计划.md
- Test: tests/test_models_contract.py
- Test: tests/test_data_loader_static.py
- Test: tests/test_problem_builder.py
- Test: tests/test_heuristic_scheduler.py
- Test: tests/test_cpsat_improver.py
- Test: tests/test_result_writer.py
- Test: tests/test_pipeline_integration.py

- [ ] **Step 1: Write failing doc consistency test or checklist assertion**

```python
def test_doc_mentions_iteration_log_every_10_generations():
    content = Path("docs/地面站基线任务规划组件开发的初步计划.md").read_text(encoding="utf-8")
    assert "每隔10" in content
```

- [ ] **Step 2: Run test to verify fail if docs not synced**

Run: pytest tests/test_pipeline_integration.py::test_doc_mentions_iteration_log_every_10_generations -v  
Expected: FAIL if wording is missing.

- [ ] **Step 3: Update docs and keep wording aligned with spec**

```markdown
- 求解器迭代日志默认每10代输出中间摘要，并始终输出终态摘要。
```

- [ ] **Step 4: Run full verification suite**

Run: pytest tests -v  
Expected: PASS all tests.

- [ ] **Step 5: Commit**

Run:
```bash
git add docs/地面站基线任务规划组件开发的初步计划.md tests
git commit -m "里程碑M5: 同步文档并完成全量验证，变更原因：确保实现与规格及验收口径一致"
```

---

## Implementation Notes

- Apply DRY and YAGNI strictly: do not implement runtime replan behavior in this phase.
- Use @superpowers:test-driven-development for each task cycle.
- Use @superpowers:verification-before-completion before any done claim.
- Keep commits frequent and milestone-scoped.
- Keep each module focused to avoid oversized files.

## Execution Commands Quick List

- Install deps: pip install -r requirements.txt
- Run all tests: pytest tests -v
- Run app: python main.py --config config --seed 666 --output-dir output
- Check changed files: git status --short

## Done Criteria

- All task checkboxes completed.
- All tests pass.
- Output includes schedule, unscheduled, metrics, solver_summary.
- Iteration log file is pre-created and contains periodic + terminal summaries.
- Main path uses rebuilt modules only.
