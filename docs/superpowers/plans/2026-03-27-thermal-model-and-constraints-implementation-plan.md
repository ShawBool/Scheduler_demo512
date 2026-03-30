# 热模型与热电约束升级 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有静态调度器中落地可插拔热模型、分层温度约束与启发式/CP-SAT 双栈一致热约束，并输出可用于后续多目标优化的热指标。

**Architecture:** 采用“热模型内核 + 两层求解接入 + 输出可观测性”三段式实现：先在独立模块实现半经验热更新和惩罚计算，再在启发式与 CP-SAT 中分别接入硬约束和软惩罚，最后在 pipeline/result_writer 输出热指标与进度日志。配置沿用现有 `config.py` 装载链路，通过新旧字段兼容映射平滑迁移。实现遵循 DRY/YAGNI，避免在两个求解器重复热参数解析逻辑。

**Tech Stack:** Python 3.12, OR-Tools CP-SAT, pytest, JSON/JSONL

---

## Scope Check

本规格属于单一子项目（热模型与热约束升级），不需要拆分为多个独立实施计划。该计划按“配置与模型基础 -> 启发式接入 -> CP-SAT接入与集成验收”三个独立可交付 Chunk 执行，每个 Chunk 都能形成可测试增量。

## Skill References

- `@test-driven-development`
- `@systematic-debugging`
- `@verification-before-completion`
- `@subagent-driven-development`

## 变更文件结构（先读）

- Create: `src/scheduler/thermal_model.py`
  - 职责：定义 `ThermalModelProtocol`、`SemiEmpiricalThermalModelV1`、`NoOpThermalModel`、热特征与热状态更新。
- Create: `tests/test_thermal_model.py`
  - 职责：覆盖热更新公式、并发二次项、连续预警检测、小并发退化规则的纯函数测试。
- Modify: `src/scheduler/config.py`
  - 职责：新增 runtime/constraints 热配置默认值、校验、旧字段兼容映射与冲突告警。
- Modify: `config/runtime.json`
  - 职责：补 `thermal_time_step`、`initial_temperature_fallback`、`thermal_initial_source`、`replan_state_max_age_sec` 示例配置。
- Modify: `config/constraints.json`
  - 职责：补 `constraints.thermal.*` 新结构示例（并保留旧字段兼容）。
- Modify: `src/scheduler/problem_builder.py`
  - 职责：在 `ProblemInstance` 中携带热配置快照和 `C_max`（用于 CP-SAT 线性化）。
- Modify: `src/scheduler/heuristic_scheduler.py`
  - 职责：候选任务评估时做热轨迹滚动预测，执行 danger 硬约束和 warning 软惩罚排序。
- Modify: `src/scheduler/cpsat_improver.py`
  - 职责：加入线性热代理约束、`q_proxy_h` 保守上界、连续预警滑窗约束。
- Modify: `src/scheduler/pipeline.py`
  - 职责：接入热模型初始化链路（last_state -> fallback）、汇总热指标并写入结果。
- Modify: `src/scheduler/result_writer.py`
  - 职责：输出新增热指标字段，必要时补充进度日志热字段。
- Modify: `src/scheduler/models.py`（仅必要时）
  - 职责：补充热相关 dataclass（若 `dict` 不满足可读性时再加）。
- Modify: `tests/test_config_validation.py`
- Modify: `tests/test_heuristic_scheduler.py`
- Modify: `tests/test_cpsat_improver.py`
- Modify: `tests/test_pipeline_integration.py`
- Modify: `tests/test_result_writer.py`

---

## Chunk 1: 配置兼容与热模型内核

### Task 1: 先写配置失败测试（新字段 + 兼容映射）

**Files:**
- Test: `tests/test_config_validation.py`

- [ ] **Step 1: 写失败测试（缺省/越界/冲突）**

```python
import copy
import pytest

from scheduler.config import load_config, validate_config


def _cfg():
    return copy.deepcopy(load_config("config"))


def test_validate_config_requires_positive_thermal_time_step():
    cfg = _cfg()
    cfg["runtime"]["thermal_time_step"] = 0
    with pytest.raises(ValueError, match="runtime.thermal_time_step"):
        validate_config(cfg)


def test_validate_config_rejects_warning_not_less_than_danger():
    cfg = _cfg()
    cfg["constraints"].setdefault("thermal", {})
    cfg["constraints"]["thermal"].update({"warning_threshold": 100, "danger_threshold": 100})
    with pytest.raises(ValueError, match="warning_threshold"):
        validate_config(cfg)


def test_validate_config_uses_new_field_when_old_and_new_conflict(caplog):
    cfg = _cfg()
    cfg["constraints"]["thermal_capacity"] = 80
    cfg["constraints"].setdefault("thermal", {})
    cfg["constraints"]["thermal"]["danger_threshold"] = 90
    validate_config(cfg)
    assert any("thermal_capacity" in r.message for r in caplog.records)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_config_validation.py -k "thermal_time_step or warning_not_less or conflict" -v`
Expected: FAIL（字段未校验或映射缺失）

- [ ] **Step 3: 提交最小实现（仅补校验/映射，不改求解器）**

```python
# src/scheduler/config.py
runtime.setdefault("thermal_time_step", int(runtime.get("time_step", 1)))
runtime.setdefault("initial_temperature_fallback", 25.0)
runtime.setdefault("thermal_initial_source", "last_state_first")
runtime.setdefault("replan_state_max_age_sec", 600)

constraints.setdefault("thermal", {})
thermal_cfg = constraints["thermal"]
if "danger_threshold" not in thermal_cfg and "thermal_capacity" in constraints:
    thermal_cfg["danger_threshold"] = float(constraints["thermal_capacity"])

thermal_cfg.setdefault("warning_threshold", float(thermal_cfg["danger_threshold"]) - 10.0)
thermal_cfg.setdefault("max_warning_duration", 60)
thermal_cfg.setdefault("env_temperature", 20.0)
thermal_cfg.setdefault("coefficients", {
    "a_p": 0.002,
    "a_c": 0.03,
    "lambda_concurrency": 0.01,
    "a_cpu": 0.2,
    "a_gpu": 0.25,
    "a_mem": 0.15,
    "a_s": 0.1,
    "k_cool": 0.005,
    "b_att": 0.0,
})

if float(runtime["thermal_time_step"]) <= 0:
        raise ValueError("runtime.thermal_time_step must be positive")
```

```json
// config/constraints.json（示例）
{
    "thermal_capacity": 100,
    "thermal": {
        "warning_threshold": 90,
        "danger_threshold": 100,
        "max_warning_duration": 60,
        "env_temperature": 20,
        "coefficients": {
            "a_p": 0.002,
            "a_c": 0.03,
            "lambda_concurrency": 0.01,
            "a_cpu": 0.2,
            "a_gpu": 0.25,
            "a_mem": 0.15,
            "a_s": 0.1,
            "k_cool": 0.005,
            "b_att": 0.0
        }
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_config_validation.py -k "thermal_time_step or warning_not_less or conflict" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/config.py tests/test_config_validation.py config/runtime.json config/constraints.json
git commit -m "扩展热配置校验与兼容映射，原因：为热约束实现提供稳定配置输入"
```

### Task 2: 热模型纯函数内核（先单测后实现）

**Files:**
- Create: `src/scheduler/thermal_model.py`
- Test: `tests/test_thermal_model.py`

- [ ] **Step 1: 写失败测试（更新方程 + 连续预警）**

```python
from scheduler.thermal_model import SemiEmpiricalThermalModelV1, ThermalCoefficients


def test_update_temperature_includes_quadratic_concurrency_term():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(a_p=0.1, a_c=0.0, lambda_concurrency=0.2, a_cpu=0, a_gpu=0, a_mem=0, a_s=0, k_cool=0, b_att=0),
        env_temperature=20,
    )
    nxt = model.update(
        state={"temperature": 30.0},
        features={"power_total": 1.0, "concurrency": 2, "cpu_util": 0, "gpu_util": 0, "memory_util": 0, "attitude_switch_rate": 0, "attitude_cooling_disturbance": 0},
        dt=1,
    )
    assert nxt["temperature"] == 30.0 + (0.1 * 1 + 0.2 * 4)


def test_max_continuous_warning_duration_is_detected():
    flags = [0, 1, 1, 1, 0, 1]
    assert SemiEmpiricalThermalModelV1.max_continuous_warning_steps(flags) == 3


def test_temperature_keeps_when_at_env_and_no_heat_gen():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(a_p=0, a_c=0, lambda_concurrency=0, a_cpu=0, a_gpu=0, a_mem=0, a_s=0, k_cool=0.1, b_att=0),
        env_temperature=20,
    )
    nxt = model.update(
        state={"temperature": 20.0},
        features={"power_total": 0.0, "concurrency": 0, "cpu_util": 0, "gpu_util": 0, "memory_util": 0, "attitude_switch_rate": 0, "attitude_cooling_disturbance": 0},
        dt=1,
    )
    assert nxt["temperature"] == 20.0


def test_attitude_cooling_disturbance_hook_affects_temperature():
    model = SemiEmpiricalThermalModelV1(
        ThermalCoefficients(a_p=0, a_c=0, lambda_concurrency=0, a_cpu=0, a_gpu=0, a_mem=0, a_s=0, k_cool=0, b_att=1.0),
        env_temperature=20,
    )
    nxt = model.update(
        state={"temperature": 30.0},
        features={"power_total": 0.0, "concurrency": 0, "cpu_util": 0, "gpu_util": 0, "memory_util": 0, "attitude_switch_rate": 0, "attitude_cooling_disturbance": 2.0},
        dt=1,
    )
    assert nxt["temperature"] == 28.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_thermal_model.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写最小实现（协议 + V1 + NoOp）**

```python
# src/scheduler/thermal_model.py
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ThermalCoefficients:
    a_p: float
    a_c: float
    lambda_concurrency: float
    a_cpu: float
    a_gpu: float
    a_mem: float
    a_s: float
    k_cool: float
    b_att: float


class ThermalModelProtocol(Protocol):
    def update(self, state: dict[str, float], features: dict[str, float], dt: float) -> dict[str, float]: ...


class SemiEmpiricalThermalModelV1:
    ...


# config.py 中增加系数映射 helper，避免求解器重复解析
def build_thermal_coefficients(cfg: dict) -> ThermalCoefficients:
    ...
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_thermal_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/thermal_model.py tests/test_thermal_model.py
git commit -m "新增热模型内核模块，原因：沉淀可复用热更新与惩罚计算逻辑"
```

---

## Chunk 2: 启发式热约束接入

### Task 3: 启发式 danger 硬约束（TDD）

**Files:**
- Modify: `src/scheduler/heuristic_scheduler.py`
- Modify: `src/scheduler/problem_builder.py`
- Test: `tests/test_heuristic_scheduler.py`

- [ ] **Step 1: 写失败测试（超 danger 的候选任务不可行）**

```python
import pytest


@pytest.fixture
def problem_fixture():
    # 构造包含 HOT_TASK / COOLER_TASK 的最小问题实例
    # HOT_TASK: 热负载高，预测将触发 danger
    # COOLER_TASK: 热负载低，可保持可行
    ...


def test_heuristic_rejects_candidate_when_danger_threshold_would_be_exceeded(problem_fixture):
    result = build_initial_schedule(problem_fixture, seed=1, initial_attitude_angle_deg=0)
    assert all(item.task_id != "HOT_TASK" for item in result.schedule)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "danger_threshold" -v`
Expected: FAIL（当前未做热硬约束）

- [ ] **Step 3: 最小实现硬约束筛选**

```python
# src/scheduler/heuristic_scheduler.py
predicted_trace = thermal_model.simulate_task(task, start=candidate, state=current_thermal_state, dt=thermal_dt)
warning_flags = [1 if warning_threshold <= t < danger_threshold else 0 for t in predicted_trace["temperatures"]]
too_hot = any(temp >= danger_threshold for temp in predicted_trace["temperatures"])
too_long_warning = thermal_model.max_continuous_warning_steps(warning_flags) * thermal_time_step > max_warning_duration
if too_hot or too_long_warning:
    continue

# 任务接受后必须推进热状态，保证后续候选评估使用最新温度
current_thermal_state = predicted_trace["end_state"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "danger_threshold" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/heuristic_scheduler.py src/scheduler/problem_builder.py tests/test_heuristic_scheduler.py
git commit -m "启发式接入热硬约束，原因：避免生成危险超温初解"
```

### Task 4: 启发式 warning 软惩罚与排序融合

**Files:**
- Modify: `src/scheduler/heuristic_scheduler.py`
- Test: `tests/test_heuristic_scheduler.py`

- [ ] **Step 1: 写失败测试（高温轨迹得分更差）**

```python
def test_heuristic_prefers_lower_thermal_penalty_when_both_feasible(problem_fixture):
    result = build_initial_schedule(problem_fixture, seed=2, initial_attitude_angle_deg=0)
    assert result.schedule[0].task_id == "COOLER_TASK"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "thermal_penalty" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现软惩罚聚合**

```python
penalty_h = w_temp * max(0.0, temp - warning_threshold)
thermal_penalty_total = sum(penalty_h_values)
score = base_score - alpha_thermal * thermal_penalty_total
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "thermal_penalty" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/heuristic_scheduler.py tests/test_heuristic_scheduler.py
git commit -m "启发式融合热软惩罚排序，原因：在可行解中优先低热风险方案"
```

### Task 5: 启发式连续预警硬约束

**Files:**
- Modify: `src/scheduler/heuristic_scheduler.py`
- Test: `tests/test_heuristic_scheduler.py`

- [ ] **Step 1: 写失败测试（超 max_warning_duration 时拒绝）**

```python
def test_heuristic_rejects_candidate_exceeding_max_warning_duration(problem_fixture):
    result = build_initial_schedule(problem_fixture, seed=3, initial_attitude_angle_deg=0)
    assert "LONG_WARNING_TASK" not in {item.task_id for item in result.schedule}


def test_heuristic_allows_candidate_at_warning_duration_boundary(problem_fixture):
    result = build_initial_schedule(problem_fixture, seed=4, initial_attitude_angle_deg=0)
    assert "BOUNDARY_WARNING_TASK" in {item.task_id for item in result.schedule}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "max_warning_duration" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现连续预警判定**

```python
warning_flags = [1 if warning_threshold <= t < danger_threshold else 0 for t in trace_temps]
if max_continuous_warning_steps(warning_flags) * thermal_time_step > max_warning_duration:
    continue
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_heuristic_scheduler.py -k "max_warning_duration" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/heuristic_scheduler.py tests/test_heuristic_scheduler.py
git commit -m "启发式增加连续预警时长硬约束，原因：落实热安全时长边界"
```

---

## Chunk 3: CP-SAT 热约束 + 集成输出

### Task 6: CP-SAT 接入 q_proxy 保守线性化

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Test: `tests/test_cpsat_improver.py`

- [ ] **Step 1: 写失败测试（q_proxy 不低估 c^2）**

```python
def test_cpsat_thermal_linearization_is_conservative(problem_fixture):
    result = improve_schedule(...)
    assert result.solver_status in {"FEASIBLE", "OPTIMAL"}
    # 断言日志/调试导出中的 q_proxy >= c^2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "linearization" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现三段线性 + 小并发退化**

```python
# 三段弦线上界：断点 [0, c1, c2, c_max]，每段 m_i/b_i 由端点计算
c1 = c_max // 3
c2 = (2 * c_max) // 3

if c_max < 3:
    model.Add(q_proxy[h] >= c_max * c[h])
else:
    for m_i, b_i in segments:
        model.Add(q_proxy[h] >= m_i * c[h] + b_i)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "linearization" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py tests/test_cpsat_improver.py
git commit -m "CP-SAT实现热并发保守线性化，原因：防止热生成被低估"
```

### Task 7: CP-SAT 连续预警滑窗硬约束

**Files:**
- Modify: `src/scheduler/cpsat_improver.py`
- Test: `tests/test_cpsat_improver.py`

- [ ] **Step 1: 写失败测试（超过 Lmax 的连续 warning 被禁止）**

```python
def test_cpsat_forbids_warning_runs_longer_than_limit(problem_fixture):
    result = improve_schedule(...)
    assert max_warning_run_in_solution(result) <= expected_lmax
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "warning_runs" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现 w_h + 滑窗约束**

```python
Lmax = int(max_warning_duration // thermal_time_step)
for h in range(0, H - Lmax):
    model.Add(sum(w[k] for k in range(h, h + Lmax + 1)) <= Lmax)

# warning <= T < danger 的线性近似绑定（上界用 danger-eps）
eps = 1e-3
M = danger_threshold - warning_threshold
model.Add(T[h] >= warning_threshold).OnlyEnforceIf(w[h])
model.Add(T[h] <= danger_threshold - eps).OnlyEnforceIf(w[h])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd .worktrees/ai-develop; pytest tests/test_cpsat_improver.py -k "warning_runs" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/cpsat_improver.py tests/test_cpsat_improver.py
git commit -m "CP-SAT增加连续预警滑窗硬约束，原因：落实预警时长上限"
```

### Task 8: Pipeline 与结果输出热指标 + 全量回归

**Files:**
- Modify: `src/scheduler/pipeline.py`
- Modify: `src/scheduler/result_writer.py`
- Modify: `tests/test_pipeline_integration.py`
- Modify: `tests/test_result_writer.py`

- [ ] **Step 1: 写失败测试（热指标写出）**

```python
def test_pipeline_outputs_thermal_metrics(tmp_path):
    out = run_pipeline("config", seed=42, output_dir=tmp_path.as_posix())
    assert "peak_temperature" in out["metrics"]
    assert "thermal_penalty_total" in out["metrics"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd .worktrees/ai-develop; pytest tests/test_pipeline_integration.py -k "thermal_metrics" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现状态来源链路与指标写出**

```python
# pipeline.py
initial_temp = load_last_state_temperature_if_fresh(...) or runtime_cfg["initial_temperature_fallback"]
metrics.update({
    "peak_temperature": peak_temp,
    "min_thermal_margin": danger_threshold - peak_temp,
    "warning_duration": warning_duration_sec,
    "max_continuous_warning_duration": max_warning_duration_sec,
    "thermal_penalty_total": thermal_penalty_total,
})
```

- [ ] **Step 4: 跑定向 + 全量测试并验证主流程**

Run: `cd .worktrees/ai-develop; pytest tests/test_result_writer.py tests/test_pipeline_integration.py -v`
Expected: PASS

Run: `cd .worktrees/ai-develop; pytest tests/ -v`
Expected: PASS

Run: `cd .worktrees/ai-develop; python main.py --config config --seed 666`
Expected: Exit Code 0，输出包含热指标字段

- [ ] **Step 5: Commit**

```bash
cd .worktrees/ai-develop
git add src/scheduler/pipeline.py src/scheduler/result_writer.py tests/test_pipeline_integration.py tests/test_result_writer.py
git commit -m "打通热指标输出链路，原因：支撑下一阶段多目标与对比实验"
```

---

## 执行顺序与检查点

1. 先完成 Chunk 1 并通过其定向测试，再进入 Chunk 2。
2. Chunk 2 任一任务失败时，先修复再继续，不跨 Chunk 带病推进。
3. Chunk 3 完成后必须执行全量测试与一次主程序运行。
4. 每个 Task 都要保持“小步提交 + 单一原因 commit message（中文且包含“原因”）”。

## 完成定义（DoD）

- 新旧热配置都可加载并通过校验。
- 启发式与 CP-SAT 都能阻止危险超温，并约束连续预警时长。
- CP-SAT 线性化满足保守性（不低估热生成）。
- 输出结果包含规格要求的 5 个热指标。
- `pytest tests/` 全绿，`python main.py --config config --seed 666` 成功。

## 审阅循环执行说明（按 Chunk）

- 对每个 Chunk 完成文档后，使用子代理进行计划审阅。
- 若审阅给出阻断问题，先修订该 Chunk 后再复审。
- 同一 Chunk 最多循环 5 次，超过后升级给人工决策。

Plan complete and saved to `docs/superpowers/plans/2026-03-27-thermal-model-and-constraints-implementation-plan.md`. Ready to execute?
