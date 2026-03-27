# Copilot Instructions

## Build and Test

- Install dependencies: `pip install -r requirements.txt`
- Run planner once: `python main.py --config config --seed 666`
- Run full tests: `pytest tests/`
- Prefer focused tests while iterating, then run full suite before completion.

中文说明：

- 安装依赖：`pip install -r requirements.txt`
- 执行一次规划：`python main.py --config config --seed 666`
- 运行全部测试：`pytest tests/`
- 开发过程中可先跑定向测试，交付前必须回归全量测试。

## Architecture

- Entry and orchestration: `main.py`, `src/scheduler/pipeline.py`
- Core modules: `src/scheduler/models.py`, `src/scheduler/data_loader.py`, `src/scheduler/problem_builder.py`
- Solvers: `src/scheduler/heuristic_scheduler.py` (initial feasible schedule), `src/scheduler/cpsat_improver.py` (CP-SAT improvement)
- Output writer: `src/scheduler/result_writer.py`

中文说明：

- 入口与编排：`main.py`、`src/scheduler/pipeline.py`
- 核心模块：`src/scheduler/models.py`、`src/scheduler/data_loader.py`、`src/scheduler/problem_builder.py`
- 求解模块：`src/scheduler/heuristic_scheduler.py`（初始可行解）、`src/scheduler/cpsat_improver.py`（CP-SAT 优化）
- 输出模块：`src/scheduler/result_writer.py`

## Project Conventions

### Worktree and Delivery Rules

- Make code changes only in branch `feature/ai-develop` under `.worktrees/ai-develop`; do not modify the main branch working directory directly.
- Use milestone commits. Commit messages must be Chinese and include the reason for the change.
- At delivery time, output only merge strategy and commands; do not auto-run merge commands.

中文说明：

- 仅允许在 `.worktrees/ai-develop` 的 `feature/ai-develop` 分支修改代码，禁止直接改 main 工作目录。
- 按里程碑提交，提交信息必须为中文且包含“变更原因”。
- 交付时仅输出合并方案与命令，不自动执行合并。

### Constraint Placement Rule

- For task-related hard constraints, prefer enforcing them in simulation/data generation rather than duplicating them in the solver.
- Keep the solver as generic as possible for search and optimization.
- If simulation already constrains tasks within visibility windows, avoid re-adding task-window ∩ visibility-window constraints in solver logic.

中文说明：

- 与任务相关的硬约束，优先在仿真/数据生成阶段落实，避免在求解器中重复实现。
- 求解器尽量保持通用搜索与优化职责。
- 若仿真已将任务约束在可见窗口内，求解器无需再做“任务窗 ∩ 可见窗”的重复约束。

### Markdown Language Rule

- For AI-oriented Markdown documents, if the main text is English, provide paired Chinese translation or Chinese annotations.
- Applies to newly created Markdown docs and major rewrites.
- Chinese-primary docs do not require extra translation.

中文说明：

- 面向 AI 阅读的 Markdown 文档中，若正文以英文为主，必须提供配套中文翻译或中文注释。
- 本规则适用于新建 Markdown 文档及大幅改写场景。
- 若文档本身主要为中文，则无需额外翻译。

## Link, Don't Embed

- Planning context: `docs/卫星任务规划开发的初步计划.md`
- Ground baseline plan: `docs/地面站基线任务规划组件开发的初步计划.md`
- Redesign design spec: `docs/superpowers/specs/2026-03-25-static-baseline-redesign-design.md`
- Redesign implementation plan: `docs/superpowers/plans/2026-03-25-static-baseline-redesign-implementation-plan.md`

中文说明：

- 说明或决策时优先链接现有文档，不复制大段内容。
- 需要细节时引用上述文档作为权威来源，避免在指令文件中重复维护。
